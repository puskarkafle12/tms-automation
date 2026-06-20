from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from database import SessionLocal
from models.scheduled_order import ScheduledOrder
from schemas.schemas import OrderCreateRequest

logger = logging.getLogger(__name__)

MAX_BATCH_SYMBOLS = 20
PARALLEL_LIMIT = 8


class CustomQueryBatchError(Exception):
    def __init__(self, message: str):
        super().__init__(message)


def _normalize_symbols(symbols: List[str]) -> List[str]:
    seen = set()
    normalized: List[str] = []
    for item in symbols:
        symbol = str(item).strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        normalized.append(symbol)
    if not normalized:
        raise CustomQueryBatchError("At least one symbol is required.")
    if len(normalized) > MAX_BATCH_SYMBOLS:
        raise CustomQueryBatchError(f"A maximum of {MAX_BATCH_SYMBOLS} symbols is supported per batch.")
    return normalized


def _build_order_request(symbol: str, payload: Dict[str, Any]) -> OrderCreateRequest:
    order_fields = dict(payload.get("order_fields") or {})
    security_map = payload.get("security_details_by_symbol") or {}
    security_details = dict(security_map.get(symbol) or security_map.get(symbol.upper()) or {})
    security_details.setdefault("symbol", symbol)
    return OrderCreateRequest(
        client_id=str(payload["client_id"]),
        script_name=symbol,
        order_type=str(order_fields.get("order_type") or payload.get("order_type") or "buy"),
        security_details=security_details,
        price=float(order_fields.get("price") or 0),
        qty=int(order_fields.get("qty") or 0),
        status=str(order_fields.get("status") or "pending"),
        strategy_type=order_fields.get("strategy_type"),
        stop_loss_price=order_fields.get("stop_loss_price"),
        stop_limit_price=order_fields.get("stop_limit_price"),
        book_profit_price=order_fields.get("book_profit_price"),
        profit_target_price=order_fields.get("profit_target_price"),
        trailing_drop_percent=order_fields.get("trailing_drop_percent"),
        stable_band_percent=order_fields.get("stable_band_percent"),
        minimum_wait_minutes=order_fields.get("minimum_wait_minutes"),
        consecutive_drop_checks=order_fields.get("consecutive_drop_checks"),
        activation_price=order_fields.get("activation_price"),
        average_buy_price=order_fields.get("average_buy_price"),
        protected_price=order_fields.get("protected_price"),
        partial_legs=order_fields.get("partial_legs"),
        expiry_time=order_fields.get("expiry_time"),
        expiry_action=order_fields.get("expiry_action"),
        max_allowed_slippage_percent=order_fields.get("max_allowed_slippage_percent"),
        emergency_execution=order_fields.get("emergency_execution"),
        odd_lot_allowed=bool(order_fields.get("odd_lot_allowed")),
        strategy_config=order_fields.get("strategy_config"),
    )


async def _schedule_one_symbol(symbol: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    db: Session = SessionLocal()
    try:
        from main import (
            _apply_schedule_baseline_if_requested,
            _enforce_rule_based_schedule_preflight,
            _persist_order_field_references,
            _validate_sell_lot_against_holdings,
            _validate_strategy_order,
            get_cached_tms_user,
        )
        from models.user import User

        order_data = _build_order_request(symbol, payload)
        incoming_security_details = order_data.security_details or {}
        order_data.security_details = {
            **incoming_security_details,
            "odd_lot_allowed": bool(
                order_data.odd_lot_allowed
                or incoming_security_details.get("odd_lot_allowed")
                or incoming_security_details.get("oddLotAllowed")
            ),
        }
        _validate_strategy_order(order_data)
        await _enforce_rule_based_schedule_preflight(order_data, db)
        await _apply_schedule_baseline_if_requested(order_data, db)

        user = db.query(User).filter(User.client_id == order_data.client_id).first()
        if not user:
            return {"symbol": symbol, "error": "User not found"}

        if order_data.order_type.lower() == "sell":
            tms_user_instance = await get_cached_tms_user(user)
            await _validate_sell_lot_against_holdings(order_data, tms_user_instance)

        order = ScheduledOrder(order_data)
        db.add(order)
        db.flush()
        await _persist_order_field_references(db, order, order_data)
        db.commit()
        return {"symbol": symbol, "order_id": order.order_id}
    except Exception as exc:
        db.rollback()
        message = str(exc)
        if hasattr(exc, "detail"):
            detail = getattr(exc, "detail")
            if isinstance(detail, dict):
                message = str(detail.get("message") or detail)
            elif detail:
                message = str(detail)
        return {"symbol": symbol, "error": message}
    finally:
        db.close()


async def run_custom_query_batch(payload: Dict[str, Any]) -> Dict[str, Any]:
    symbols = _normalize_symbols(list(payload.get("symbols") or []))
    semaphore = asyncio.Semaphore(PARALLEL_LIMIT)

    async def _guarded(symbol: str) -> Dict[str, Any]:
        async with semaphore:
            return await _schedule_one_symbol(symbol, payload)

    results = list(await asyncio.gather(*[_guarded(symbol) for symbol in symbols]))
    scheduled = [item for item in results if item.get("order_id")]
    failed = [item for item in results if item.get("error")]
    logger.info(
        "Custom query batch finished: %s scheduled, %s failed (client=%s)",
        len(scheduled),
        len(failed),
        payload.get("client_id"),
    )
    return {
        "status": "completed",
        "scheduled": scheduled,
        "failed": failed,
        "ready": not failed,
    }


async def run_custom_query_batch_safe(payload: Dict[str, Any]) -> None:
    try:
        result = await run_custom_query_batch(payload)
        if result["failed"]:
            logger.warning("Custom query batch partial failure: %s", result["failed"])
    except Exception:
        logger.exception("Custom query batch crashed for client=%s", payload.get("client_id"))
