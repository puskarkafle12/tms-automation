from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from database import SessionLocal
from models.scheduled_order import ScheduledOrder
from schemas.schemas import OrderCreateRequest
from utils.strategy_builder.schedule_preview_capture import snapshots_complete_for_symbols

logger = logging.getLogger(__name__)

PARALLEL_LIMIT = 12
SCHEDULE_RETRY_ATTEMPTS = 3
SCHEDULE_RETRY_BACKOFF_SECONDS = 0.75
TRANSIENT_SCHEDULE_ERROR_MARKERS = (
    "server disconnected",
    "connection reset",
    "connection aborted",
    "connection closed",
    "timeout",
    "timed out",
    "temporarily unavailable",
)


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


def _batch_label_from_payload(payload: Dict[str, Any]) -> str:
    config = dict((payload.get("order_fields") or {}).get("strategy_config") or {})
    compiled = config.get("compiled_plan") or {}
    rules = compiled.get("rules") or []
    if rules and isinstance(rules[0], dict) and rules[0].get("name"):
        return str(rules[0]["name"]).strip()[:120]
    query = str(config.get("query_text") or "").strip()
    if query:
        first_line = query.splitlines()[0].strip()
        if first_line.upper().startswith("RULE "):
            name_part = first_line[5:].split(" FOR ", 1)[0].strip()
            return name_part.strip('"').strip()[:120]
    return "Custom Query Batch"


def _attach_batch_metadata(order_data: OrderCreateRequest, payload: Dict[str, Any]) -> None:
    batch_id = str(payload.get("schedule_batch_id") or "").strip()
    if not batch_id:
        return
    strategy_config = dict(order_data.strategy_config or {})
    strategy_config["schedule_batch_id"] = batch_id
    strategy_config["schedule_batch_label"] = str(
        payload.get("schedule_batch_label") or "Custom Query Batch"
    ).strip()[:120]
    strategy_config["schedule_batch_symbol_count"] = int(
        payload.get("schedule_batch_symbol_count") or 0
    )
    order_data.strategy_config = strategy_config


def _extract_error_message(exc: Exception) -> str:
    message = str(exc)
    if hasattr(exc, "detail"):
        detail = getattr(exc, "detail")
        if isinstance(detail, dict):
            errors = detail.get("errors")
            if isinstance(errors, list) and errors:
                first = errors[0]
                if isinstance(first, dict) and first.get("message"):
                    return str(first["message"])
            return str(detail.get("message") or detail)
        if detail:
            return str(detail)
    return message


def _is_transient_schedule_error(message: str) -> bool:
    lowered = str(message or "").lower()
    return any(marker in lowered for marker in TRANSIENT_SCHEDULE_ERROR_MARKERS)


async def _preflight_one_symbol(symbol: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    db: Session = SessionLocal()
    try:
        from utils.strategy_builder.schedule_preflight import run_schedule_preflight

        order_data = _build_order_request(symbol, payload)
        config = order_data.strategy_config or {}
        result = await run_schedule_preflight(
            query_text=str(config.get("query_text") or ""),
            compiled_plan=config.get("compiled_plan"),
            strategy_type=order_data.strategy_type,
            client_id=order_data.client_id,
            script_name=symbol,
            db=db,
            capture_reference_ltp=bool(config.get("capture_reference_ltp")),
            drop_percent=float(config.get("drop_percent") or 10),
            fixed_symbols=config.get("fixed_symbols"),
        )
        if result.get("ready"):
            return {"symbol": symbol, "ready": True}
        errors = result.get("errors") or []
        first_error = errors[0] if errors else {}
        message = (
            first_error.get("message")
            or result.get("message")
            or f"Preflight failed for {symbol}."
        )
        return {"symbol": symbol, "ready": False, "message": str(message)}
    except Exception as exc:
        return {"symbol": symbol, "ready": False, "message": _extract_error_message(exc)}
    finally:
        db.close()


async def _preflight_batch(payload: Dict[str, Any], symbols: List[str]) -> Dict[str, Any]:
    db: Session = SessionLocal()
    try:
        from utils.strategy_builder.schedule_preflight import run_schedule_preflight

        first_symbol = symbols[0] if symbols else ""
        order_data = _build_order_request(first_symbol, payload)
        config = order_data.strategy_config or {}
        result = await run_schedule_preflight(
            query_text=str(config.get("query_text") or ""),
            compiled_plan=config.get("compiled_plan"),
            strategy_type=order_data.strategy_type,
            client_id=order_data.client_id,
            script_name=None,
            db=db,
            capture_reference_ltp=bool(config.get("capture_reference_ltp")),
            drop_percent=float(config.get("drop_percent") or 10),
            fixed_symbols=config.get("fixed_symbols"),
        )
        if result.get("ready"):
            return {"ready": True, "failed": []}

        errors = result.get("errors") or []
        per_symbol_messages: Dict[str, str] = {}
        global_message = str(result.get("message") or "Batch preflight failed.")
        for issue in errors:
            if not isinstance(issue, dict):
                continue
            symbol = str(issue.get("symbol") or "").strip().upper()
            message = str(issue.get("message") or global_message)
            if symbol:
                per_symbol_messages[symbol] = message

        failed = []
        if per_symbol_messages:
            for symbol in symbols:
                if symbol in per_symbol_messages:
                    failed.append({"symbol": symbol, "message": per_symbol_messages[symbol]})
        else:
            failed = [{"symbol": symbol, "message": global_message} for symbol in symbols]
        return {"ready": False, "failed": failed, "message": global_message}
    except Exception as exc:
        message = _extract_error_message(exc)
        return {
            "ready": False,
            "failed": [{"symbol": symbol, "message": message} for symbol in symbols],
            "message": message,
        }
    finally:
        db.close()


async def _schedule_one_symbol(
    symbol: str,
    payload: Dict[str, Any],
    *,
    enforce_preflight: bool = True,
    holdings_by_symbol: Optional[Dict[str, int]] = None,
    batch_snapshots: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    db: Session = SessionLocal()
    try:
        from main import (
            _apply_schedule_baseline_if_requested,
            _enforce_rule_based_schedule_preflight,
            _scheduled_order_dedup_key,
            _persist_order_field_references,
            _validate_sell_lot_against_holdings,
            _validate_strategy_order,
            get_cached_tms_user,
        )
        from models.user import User

        order_data = _build_order_request(symbol, payload)
        _attach_batch_metadata(order_data, payload)
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
        if enforce_preflight:
            await _enforce_rule_based_schedule_preflight(order_data, db)
        await _apply_schedule_baseline_if_requested(order_data, db)

        user = db.query(User).filter(User.client_id == order_data.client_id).first()
        if not user:
            return {"symbol": symbol, "error": "User not found"}

        if order_data.order_type.lower() == "sell":
            config = dict(order_data.strategy_config or {})
            skip_holding_recheck = bool(payload.get("skip_preflight")) and bool(
                config.get("schedule_preflight_ready")
            )
            if not skip_holding_recheck:
                tms_user_instance = await get_cached_tms_user(user)
                await _validate_sell_lot_against_holdings(order_data, tms_user_instance)

        order = ScheduledOrder(order_data)
        db.add(order)
        db.flush()
        await _persist_order_field_references(db, order, order_data)
        order.strategy_config = dict(order.strategy_config or {})
        order.strategy_config["schedule_dedup_key"] = _scheduled_order_dedup_key(order_data)
        from utils.strategy_builder.schedule_preview_capture import apply_schedule_preview_snapshot

        batch_holdings = dict(holdings_by_symbol or payload.get("holdings_by_symbol") or {})
        await apply_schedule_preview_snapshot(
            order,
            order_data,
            db,
            holdings_by_symbol=batch_holdings or None,
            batch_snapshots=batch_snapshots,
        )
        db.commit()
        return {"symbol": symbol, "order_id": order.order_id}
    except Exception as exc:
        db.rollback()
        return {"symbol": symbol, "error": _extract_error_message(exc), "message": _extract_error_message(exc)}
    finally:
        db.close()


async def _schedule_one_symbol_with_retries(
    symbol: str,
    payload: Dict[str, Any],
    *,
    enforce_preflight: bool = True,
    holdings_by_symbol: Optional[Dict[str, int]] = None,
    batch_snapshots: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    last_result: Dict[str, Any] = {}
    for attempt in range(1, SCHEDULE_RETRY_ATTEMPTS + 1):
        result = await _schedule_one_symbol(
            symbol,
            payload,
            enforce_preflight=enforce_preflight,
            holdings_by_symbol=holdings_by_symbol,
            batch_snapshots=batch_snapshots,
        )
        if result.get("order_id"):
            if attempt > 1:
                result["retry_attempts"] = attempt
            return result
        message = str(result.get("message") or result.get("error") or "")
        last_result = result
        if not _is_transient_schedule_error(message) or attempt >= SCHEDULE_RETRY_ATTEMPTS:
            return result
        await asyncio.sleep(SCHEDULE_RETRY_BACKOFF_SECONDS * attempt)
    return last_result


async def run_custom_query_batch(payload: Dict[str, Any]) -> Dict[str, Any]:
    symbols = _normalize_symbols(list(payload.get("symbols") or []))
    batch_id = str(uuid.uuid4())
    payload = {
        **payload,
        "schedule_batch_id": batch_id,
        "schedule_batch_label": _batch_label_from_payload(payload),
        "schedule_batch_symbol_count": len(symbols),
    }
    semaphore = asyncio.Semaphore(PARALLEL_LIMIT)

    if not payload.get("skip_preflight"):
        batch_preflight = await _preflight_batch(payload, symbols)
        if not batch_preflight.get("ready"):
            failed_preflight = batch_preflight.get("failed") or []
            logger.info(
                "Custom query batch preflight blocked scheduling: %s failed (client=%s)",
                len(failed_preflight),
                payload.get("client_id"),
            )
            return {
                "status": "preflight_failed",
                "schedule_batch_id": batch_id,
                "schedule_batch_label": payload.get("schedule_batch_label"),
                "scheduled": [],
                "failed": failed_preflight,
                "ready": False,
            }

    batch_holdings = dict(payload.get("holdings_by_symbol") or {})
    if (
        not batch_holdings
        and str(payload.get("order_type") or payload.get("order_fields", {}).get("order_type") or "").lower() == "sell"
    ):
        try:
            from utils.strategy_builder.holdings_preflight import build_holdings_map
            from utils.tms_client_resolver import get_tms_user_for_client

            db: Session = SessionLocal()
            try:
                tms_user = await get_tms_user_for_client(str(payload["client_id"]), db)
                batch_holdings = await build_holdings_map(tms_user)
            finally:
                db.close()
        except Exception:
            logger.warning("Custom query batch could not prefetch holdings for client=%s", payload.get("client_id"))

    batch_snapshots: Dict[str, Dict[str, Any]] = dict(
        (payload.get("order_fields") or {}).get("strategy_config", {}).get("schedule_preview_snapshots_by_symbol") or {}
    )
    if symbols and not snapshots_complete_for_symbols(batch_snapshots, symbols):
        try:
            from utils.strategy_builder.schedule_preview_capture import capture_batch_preview_snapshots

            template_fields = dict(payload.get("order_fields") or {})
            template_config = dict(template_fields.get("strategy_config") or {})
            template_config["schedule_preview_snapshots_by_symbol"] = batch_snapshots
            template_request = OrderCreateRequest(
                client_id=str(payload["client_id"]),
                script_name=symbols[0],
                order_type=str(payload.get("order_type") or template_fields.get("order_type") or "buy"),
                price=float(template_fields.get("price") or 0),
                qty=int(template_fields.get("qty") or 0),
                status=str(template_fields.get("status") or "pending"),
                strategy_type=template_fields.get("strategy_type"),
                strategy_config=template_config,
            )
            db: Session = SessionLocal()
            try:
                batch_snapshots = await capture_batch_preview_snapshots(
                    template_request,
                    db,
                    symbols,
                    holdings_by_symbol=batch_holdings or None,
                )
            finally:
                db.close()
            order_fields = dict(payload.get("order_fields") or {})
            strategy_config = dict(order_fields.get("strategy_config") or {})
            strategy_config["schedule_preview_snapshots_by_symbol"] = batch_snapshots
            order_fields["strategy_config"] = strategy_config
            payload = {**payload, "order_fields": order_fields}
        except Exception:
            logger.exception("Custom query batch preview snapshot capture failed for client=%s", payload.get("client_id"))

    async def _schedule_guarded(symbol: str) -> Dict[str, Any]:
        async with semaphore:
            return await _schedule_one_symbol_with_retries(
                symbol,
                payload,
                enforce_preflight=False,
                holdings_by_symbol=batch_holdings or None,
                batch_snapshots=batch_snapshots or None,
            )

    results = list(await asyncio.gather(*[_schedule_guarded(symbol) for symbol in symbols]))
    scheduled = [item for item in results if item.get("order_id")]
    failed = [
        {
            "symbol": item["symbol"],
            "message": item.get("message") or item.get("error") or f"{item['symbol']} failed to schedule.",
        }
        for item in results
        if item.get("error")
    ]
    logger.info(
        "Custom query batch finished: %s scheduled, %s failed (client=%s)",
        len(scheduled),
        len(failed),
        payload.get("client_id"),
    )
    return {
        "status": "completed",
        "schedule_batch_id": batch_id,
        "schedule_batch_label": payload.get("schedule_batch_label"),
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
