from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from models.scheduled_order import ScheduledOrder
from schemas.schemas import OrderCreateRequest
from utils.strategy_builder.constants import DEFAULT_RULE_ORDER_QUANTITY
from utils.strategy_builder.plan_helpers import extract_planned_quantity_from_compiled_plan
from utils.strategy_builder.schedule_baseline import (
    DEFAULT_DROP_PERCENT,
    ScheduleBaselineError,
    apply_fixed_trigger_to_compiled_plan,
    capture_baselines_for_symbols,
    capture_symbol_baseline_from_tms,
    compile_baseline_strategy_config,
    merge_baseline_into_order_fields,
    normalize_expiration_config,
    reject_self_referential_drop_query,
    validate_expiration_timestamp,
)
from utils.strategy_builder.schedule_preflight import run_schedule_preflight

MAX_SCREENER_DROP_SYMBOLS = 10

FRONTEND_EXPIRATION_ACTION_MAP = {
    "cancel": "CANCEL",
    "cancel strategy": "CANCEL",
    "mark expired only": "CANCEL",
    "buy at protected ltp": "BUY_AT_PROTECTED_LTP",
    "protected ltp buy": "BUY_AT_PROTECTED_LTP",
    "buy at top sell": "BUY_AT_TOP_SELL",
    "top sell buy": "BUY_AT_TOP_SELL",
}


def map_expiration_action(frontend_label: Optional[str]) -> str:
    if not frontend_label:
        return "CANCEL"
    normalized = str(frontend_label).strip().lower()
    return FRONTEND_EXPIRATION_ACTION_MAP.get(normalized, str(frontend_label).strip().upper())


def recalculate_trigger_from_reference(reference_ltp: float, drop_percent: float) -> float:
    from utils.strategy_builder.schedule_baseline import calculate_trigger_price

    return calculate_trigger_price(reference_ltp, drop_percent)


def build_default_screener_drop_query(symbol: str, qty: int = DEFAULT_RULE_ORDER_QUANTITY) -> str:
    normalized = symbol.strip().upper()
    return f"""STRATEGY_VERSION 1
SIDE BUY
RULE "Screener Pullback Buy" FOR SYMBOL "{normalized}" {{
    WHEN ltp <= 999999
    ORDER QUANTITY {max(1, int(qty))}
    EXECUTE ONCE PER SYMBOL
}}"""


def resolve_query_for_symbol(query_text: str, symbol: str, qty: int) -> str:
    normalized = symbol.strip().upper()
    text = str(query_text or "").strip()
    if text and normalized in text.upper():
        return text
    return build_default_screener_drop_query(normalized, qty)


def _normalize_symbols(symbols: List[str]) -> List[str]:
    seen = set()
    normalized: List[str] = []
    for item in symbols:
        symbol = str(item).strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        normalized.append(symbol)
    return normalized


def _validate_symbols(symbols: List[str]) -> List[str]:
    normalized = _normalize_symbols(symbols)
    if not normalized:
        raise ScheduleBaselineError("At least one symbol is required.")
    if len(normalized) > MAX_SCREENER_DROP_SYMBOLS:
        raise ScheduleBaselineError(
            f"A maximum of {MAX_SCREENER_DROP_SYMBOLS} symbols is supported per batch."
        )
    return normalized


def _build_expiration_payload(
    *,
    expiration: Optional[dict],
    expiry_time: Optional[datetime],
    expiry_action: Optional[str],
    max_slippage_percent: float,
) -> dict:
    payload = dict(expiration or {})
    if expiry_time is not None:
        payload["expires_at"] = expiry_time.isoformat()
    action = map_expiration_action(
        payload.get("expiration_action") or payload.get("action") or expiry_action
    )
    payload["expiration_action"] = action
    payload.setdefault("expiration_max_slippage_pct", max_slippage_percent)
    return normalize_expiration_config(payload)


def _resolve_qty(
    *,
    compiled_plan: dict,
    symbol: str,
    default_qty: Optional[int],
    per_symbol_qty: Optional[Dict[str, int]],
) -> int:
    if per_symbol_qty:
        configured = per_symbol_qty.get(symbol.strip().upper())
        if configured and int(configured) > 0:
            return int(configured)
    from_plan = extract_planned_quantity_from_compiled_plan(compiled_plan, symbol)
    if from_plan and from_plan > 0:
        return from_plan
    if default_qty and int(default_qty) > 0:
        return int(default_qty)
    return DEFAULT_RULE_ORDER_QUANTITY


async def preview_screener_drop_batch(
    db: Session,
    *,
    client_id: str,
    query_text: str,
    symbols: List[str],
    drop_percent: float = DEFAULT_DROP_PERCENT,
    expiration: Optional[dict] = None,
    expiry_time: Optional[datetime] = None,
    expiry_action: Optional[str] = None,
    max_slippage_percent: float = 1.0,
    default_qty: Optional[int] = None,
    per_symbol_qty: Optional[Dict[str, int]] = None,
) -> dict:
    from utils.tms_client_resolver import get_tms_user_for_client

    normalized_symbols = _validate_symbols(symbols)
    reject_self_referential_drop_query(query_text)
    expiration_payload = _build_expiration_payload(
        expiration=expiration,
        expiry_time=expiry_time,
        expiry_action=expiry_action,
        max_slippage_percent=max_slippage_percent,
    )
    if expiry_time is not None:
        validate_expiration_timestamp(expiry_time)

    tms_user = await get_tms_user_for_client(client_id, db)
    baselines, errors = await capture_baselines_for_symbols(
        tms_user,
        normalized_symbols,
        drop_percent=drop_percent,
    )
    rows = []
    for baseline in baselines:
        symbol = baseline["symbol"]
        qty = _resolve_qty(
            compiled_plan={},
            symbol=symbol,
            default_qty=default_qty,
            per_symbol_qty=per_symbol_qty,
        )
        symbol_query = resolve_query_for_symbol(query_text, symbol, qty)
        config = compile_baseline_strategy_config(
            query_text=symbol_query,
            symbol=symbol,
            baseline=baseline,
            expiration=expiration_payload,
            fixed_symbols=normalized_symbols,
        )
        qty = _resolve_qty(
            compiled_plan=config["compiled_plan"],
            symbol=symbol,
            default_qty=default_qty,
            per_symbol_qty=per_symbol_qty,
        )
        rows.append(
            {
                **baseline,
                "qty": qty,
                "compiled_plan": config["compiled_plan"],
                "expiration": config.get("expiration"),
                "expiry_time": expiry_time.isoformat() if expiry_time else expiration_payload.get("expires_at"),
                "expiration_action": expiration_payload.get("expiration_action"),
                "max_allowed_slippage_percent": max_slippage_percent,
            }
        )
    return {
        "ready": len(errors) == 0,
        "fixed_symbols": normalized_symbols,
        "rows": rows,
        "errors": errors,
        "baseline_warning": (
            "The reference LTP and trigger price will remain fixed after scheduling. "
            "Live LTP will continue to update during monitoring."
        ),
        "expiration_notice": (
            "If the pullback trigger is not reached before expiration, the configured expiration action "
            "may submit a protected BUY using a fresh expiration-time quote."
        ),
    }


async def _build_order_request_for_symbol(
    *,
    client_id: str,
    query_text: str,
    symbol: str,
    fixed_symbols: List[str],
    baseline: dict,
    expiration_payload: dict,
    expiry_time: Optional[datetime],
    expiry_action: str,
    strategy_type: str,
    qty: int,
    max_slippage_percent: float,
    odd_lot_allowed: bool,
    security_details: Optional[dict],
) -> OrderCreateRequest:
    config = compile_baseline_strategy_config(
        query_text=query_text,
        symbol=symbol,
        baseline=baseline,
        expiration=expiration_payload,
        fixed_symbols=fixed_symbols,
    )
    order_data = OrderCreateRequest(
        client_id=client_id,
        script_name=symbol,
        symbol=symbol,
        price=0,
        qty=qty,
        order_type="buy",
        status="Waiting",
        strategy_type=strategy_type,
        side="buy",
        expiry_time=expiry_time,
        expiry_action=expiry_action,
        max_allowed_slippage_percent=max_slippage_percent,
        odd_lot_allowed=odd_lot_allowed,
        security_details={
            **(security_details or {}),
            "odd_lot_allowed": odd_lot_allowed,
            "oddLotAllowed": odd_lot_allowed,
        },
        strategy_config={
            **config,
            "rule_planned_qty": qty,
            "execution_mode": "live",
        },
    )
    merge_baseline_into_order_fields(order_data, baseline)
    return order_data


async def commit_screener_drop_batch(
    db: Session,
    *,
    client_id: str,
    query_text: str,
    symbols: List[str],
    drop_percent: float = DEFAULT_DROP_PERCENT,
    expiration: Optional[dict] = None,
    expiry_time: Optional[datetime] = None,
    expiry_action: Optional[str] = None,
    strategy_type: str = "Custom Query Buy",
    default_qty: Optional[int] = None,
    per_symbol_qty: Optional[Dict[str, int]] = None,
    max_slippage_percent: float = 1.0,
    odd_lot_allowed: bool = False,
    security_details_by_symbol: Optional[Dict[str, dict]] = None,
    owner_user_id: Optional[int] = None,
) -> dict:
    from models.user import User
    from utils.tms_client_resolver import get_tms_user_for_client

    normalized_symbols = _validate_symbols(symbols)
    reject_self_referential_drop_query(query_text)
    if expiry_time is None:
        raise ScheduleBaselineError("Expiration timestamp is required.")
    validate_expiration_timestamp(expiry_time)

    user = db.query(User).filter(User.client_id == client_id).first()
    if not user:
        raise ScheduleBaselineError("User not found.")

    expiration_payload = _build_expiration_payload(
        expiration=expiration,
        expiry_time=expiry_time,
        expiry_action=expiry_action,
        max_slippage_percent=max_slippage_percent,
    )
    mapped_action = str(expiration_payload.get("expiration_action") or "CANCEL")

    tms_user = await get_tms_user_for_client(client_id, db)
    scheduled: List[dict] = []
    failed: List[dict] = []

    for symbol in normalized_symbols:
        try:
            preview_qty = _resolve_qty(
                compiled_plan={},
                symbol=symbol,
                default_qty=default_qty,
                per_symbol_qty=per_symbol_qty,
            )
            symbol_query = resolve_query_for_symbol(query_text, symbol, preview_qty)
            baseline = await capture_symbol_baseline_from_tms(
                tms_user,
                symbol,
                drop_percent=drop_percent,
            )
            preview_config = compile_baseline_strategy_config(
                query_text=symbol_query,
                symbol=symbol,
                baseline=baseline,
                expiration=expiration_payload,
                fixed_symbols=normalized_symbols,
            )
            qty = _resolve_qty(
                compiled_plan=preview_config["compiled_plan"],
                symbol=symbol,
                default_qty=default_qty,
                per_symbol_qty=per_symbol_qty,
            )
            preflight = await run_schedule_preflight(
                query_text=symbol_query,
                compiled_plan=preview_config["compiled_plan"],
                strategy_type=strategy_type,
                client_id=client_id,
                script_name=symbol,
                db=db,
                capture_reference_ltp=False,
            )
            if not preflight.get("ready"):
                message = preflight.get("message") or "Preflight check failed."
                failed.append({"symbol": symbol, "message": message})
                continue

            order_data = await _build_order_request_for_symbol(
                client_id=client_id,
                query_text=symbol_query,
                symbol=symbol,
                fixed_symbols=normalized_symbols,
                baseline=baseline,
                expiration_payload=expiration_payload,
                expiry_time=expiry_time,
                expiry_action=mapped_action,
                strategy_type=strategy_type,
                qty=qty,
                max_slippage_percent=max_slippage_percent,
                odd_lot_allowed=odd_lot_allowed,
                security_details=(security_details_by_symbol or {}).get(symbol),
            )
            order = ScheduledOrder(order_data)
            order.owner_user_id = owner_user_id
            db.add(order)
            db.flush()
            strategy_config = dict(order_data.strategy_config or {})
            compiled_plan = strategy_config.get("compiled_plan")
            if compiled_plan:
                from utils.strategy_builder.reference_dependencies import plan_uses_reference
                from utils.strategy_builder.reference_capture import ReferenceCaptureError
                from utils.strategy_builder.reference_schedule import capture_and_attach_field_references
                from utils.strategy_builder.strategy_models import StrategyPlanAST

                plan = StrategyPlanAST.model_validate(compiled_plan)
                if plan_uses_reference(plan):
                    try:
                        order.strategy_config = await capture_and_attach_field_references(
                            db=db,
                            tms_user=tms_user,
                            order_id=order.order_id,
                            symbol=symbol,
                            plan=plan,
                            strategy_config=strategy_config,
                        )
                    except ReferenceCaptureError as exc:
                        db.delete(order)
                        db.flush()
                        failed.append({"symbol": symbol, "message": str(exc)})
                        continue
            scheduled.append(
                {
                    "order_id": order.order_id,
                    "symbol": symbol,
                    "reference_ltp": order.reference_ltp,
                    "trigger_price": order.trigger_price,
                    "qty": order.qty,
                    "expiry_time": order.expiry_time.isoformat() if order.expiry_time else None,
                }
            )
        except ScheduleBaselineError as exc:
            failed.append({"symbol": symbol, "message": str(exc)})
        except Exception as exc:
            failed.append({"symbol": symbol, "message": str(exc)})

    if scheduled:
        db.commit()
    else:
        db.rollback()

    return {"scheduled": scheduled, "failed": failed, "ready": len(failed) == 0}


def recompile_baseline_plan_for_drop_change(
    *,
    query_text: str,
    symbol: str,
    reference_ltp: float,
    drop_percent: float,
    fixed_symbols: Optional[List[str]] = None,
    expiration: Optional[dict] = None,
) -> Tuple[dict, dict]:
    trigger_price = recalculate_trigger_from_reference(reference_ltp, drop_percent)
    baseline = {
        "symbol": symbol.strip().upper(),
        "reference_ltp": float(reference_ltp),
        "drop_percent": float(drop_percent),
        "trigger_price": trigger_price,
    }
    config = compile_baseline_strategy_config(
        query_text=query_text,
        symbol=symbol,
        baseline=baseline,
        expiration=expiration,
        fixed_symbols=fixed_symbols or [symbol.strip().upper()],
    )
    compiled = apply_fixed_trigger_to_compiled_plan(
        config["compiled_plan"],
        symbol=symbol,
        trigger_price=trigger_price,
    )
    config["compiled_plan"] = compiled
    config["schedule_baseline"] = {**baseline, **(config.get("schedule_baseline") or {})}
    config["schedule_baseline"]["trigger_price"] = trigger_price
    config["schedule_baseline"]["drop_percent"] = float(drop_percent)
    return config, baseline
