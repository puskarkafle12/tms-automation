from __future__ import annotations

import copy
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from utils.base_functions import truncate_to_one_decimal_place
from utils.strategy_builder.strategy_models import StrategyPlanAST
from utils.strategy_builder.strategy_parser import StrategyQueryError, parse_strategy_query

DEFAULT_DROP_PERCENT = 10.0
DEFAULT_EXPIRATION_ACTION = "CANCEL"
DEFAULT_EXPIRATION_SLIPPAGE_PCT = 1.0
DEFAULT_MARKET_CLOSED_POLICY = "CANCEL_IF_MARKET_CLOSED"
DEFAULT_TOP_SELL_FALLBACK = "CANCEL"

SELF_REFERENTIAL_DROP_PATTERN = re.compile(
    r"ltp\s*(?:<=|>=|<|>|=|!=)\s*ltp\s*\*",
    re.IGNORECASE,
)

SUPPORTED_EXPIRATION_ACTIONS = {
    "CANCEL",
    "BUY_AT_PROTECTED_LTP",
    "BUY_AT_TOP_SELL",
}
SUPPORTED_MARKET_CLOSED_POLICIES = {
    "CANCEL_IF_MARKET_CLOSED",
    "EXECUTE_AT_NEXT_VALID_MARKET_QUOTE",
    "KEEP_PENDING_UNTIL_SECONDARY_EXPIRY",
}


class ScheduleBaselineError(ValueError):
    pass


def calculate_trigger_price(reference_ltp: float, drop_percent: float = DEFAULT_DROP_PERCENT) -> float:
    ref = float(reference_ltp or 0)
    if ref <= 0:
        raise ScheduleBaselineError("Reference LTP must be greater than zero.")
    pct = float(drop_percent if drop_percent is not None else DEFAULT_DROP_PERCENT)
    if pct <= 0 or pct >= 100:
        raise ScheduleBaselineError("Drop percent must be between 0 and 100.")
    raw = ref * (1.0 - pct / 100.0)
    return float(truncate_to_one_decimal_place(raw))


def reject_self_referential_drop_query(query_text: str) -> None:
    if not query_text:
        return
    if SELF_REFERENTIAL_DROP_PATTERN.search(query_text):
        raise StrategyQueryError(
            "Invalid drop trigger: ltp <= ltp * percentage compares live LTP with itself. "
            "Use schedule-time baseline capture instead."
        )


def build_fixed_ltp_trigger_when(trigger_price: float) -> dict:
    return {
        "type": "comparison",
        "left": {"type": "field", "name": "ltp"},
        "operator": "lte",
        "right": {"type": "literal", "value": float(trigger_price)},
    }


def apply_fixed_trigger_to_compiled_plan(
    compiled_plan: dict,
    *,
    symbol: str,
    trigger_price: float,
) -> dict:
    """Replace matching rule WHEN with ltp <= fixed trigger_price."""
    payload = copy.deepcopy(compiled_plan)
    target = symbol.strip().upper()
    for rule in payload.get("rules") or []:
        rule_symbols = {str(item).strip().upper() for item in rule.get("symbols") or []}
        if target in rule_symbols:
            rule["when"] = build_fixed_ltp_trigger_when(trigger_price)
    return payload


def build_symbol_baseline_record(
    *,
    symbol: str,
    reference_ltp: float,
    drop_percent: float,
    captured_at: Optional[datetime] = None,
    quote_timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    captured = captured_at or datetime.now(timezone.utc)
    trigger = calculate_trigger_price(reference_ltp, drop_percent)
    return {
        "symbol": symbol.strip().upper(),
        "reference_ltp": float(reference_ltp),
        "reference_ltp_captured_at": captured.isoformat(),
        "drop_percent": float(drop_percent),
        "trigger_price": trigger,
        "quote_timestamp": quote_timestamp,
    }


async def capture_symbol_baseline_from_tms(
    tms_user,
    symbol: str,
    *,
    drop_percent: float = DEFAULT_DROP_PERCENT,
    max_quote_age_seconds: int = 60,
) -> Dict[str, Any]:
    normalized = symbol.strip().upper()
    if not normalized:
        raise ScheduleBaselineError("Symbol is required.")

    security = await tms_user.get_security_id(normalized)
    if not security or not security.get("id"):
        raise ScheduleBaselineError(f"{normalized} was not found in TMS.")

    from utils.strategy_builder.reference_capture import REFERENCE_CAPTURE_MAX_RETRIES

    quote = await tms_user.get_stock_details_async(
        str(security["id"]),
        max_retries=REFERENCE_CAPTURE_MAX_RETRIES,
        retry_backoff=True,
    )
    if not quote:
        raise ScheduleBaselineError(f"Live TMS quote is unavailable for {normalized}.")

    ltp = float(quote.get("ltp") or 0)
    if ltp <= 0:
        raise ScheduleBaselineError(f"Reference LTP for {normalized} is zero or missing.")

    quote_ts = quote.get("lastTradedTime") or quote.get("last_traded_time")
    return build_symbol_baseline_record(
        symbol=normalized,
        reference_ltp=ltp,
        drop_percent=drop_percent,
        quote_timestamp=str(quote_ts) if quote_ts else None,
    )


async def capture_baselines_for_symbols(
    tms_user,
    symbols: List[str],
    *,
    drop_percent: float = DEFAULT_DROP_PERCENT,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    baselines: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []
    for symbol in symbols:
        try:
            baselines.append(
                await capture_symbol_baseline_from_tms(
                    tms_user,
                    symbol,
                    drop_percent=drop_percent,
                )
            )
        except ScheduleBaselineError as exc:
            errors.append({"symbol": symbol.strip().upper(), "message": str(exc)})
    return baselines, errors


def normalize_expiration_config(raw: Optional[dict]) -> Dict[str, Any]:
    payload = dict(raw or {})
    action = str(payload.get("expiration_action") or payload.get("action") or DEFAULT_EXPIRATION_ACTION).upper()
    if action not in SUPPORTED_EXPIRATION_ACTIONS:
        raise ScheduleBaselineError(f"Unsupported expiration action: {action}")
    market_closed = str(
        payload.get("market_closed_policy") or DEFAULT_MARKET_CLOSED_POLICY
    ).upper()
    if market_closed not in SUPPORTED_MARKET_CLOSED_POLICIES:
        raise ScheduleBaselineError(f"Unsupported market-closed policy: {market_closed}")
    top_sell_fallback = str(payload.get("top_sell_fallback") or DEFAULT_TOP_SELL_FALLBACK).upper()
    return {
        "expiration_action": action,
        "expiration_price_source": str(payload.get("expiration_price_source") or "LTP"),
        "expiration_max_slippage_pct": float(
            payload.get("expiration_max_slippage_pct")
            or payload.get("max_slippage_pct")
            or DEFAULT_EXPIRATION_SLIPPAGE_PCT
        ),
        "market_closed_policy": market_closed,
        "top_sell_fallback": top_sell_fallback,
    }


def validate_expiration_timestamp(expires_at: Optional[datetime]) -> None:
    if expires_at is None:
        return
    now = datetime.utcnow()
    value = expires_at.replace(tzinfo=None) if expires_at.tzinfo else expires_at
    if value <= now:
        raise ScheduleBaselineError("Expiration timestamp must be in the future.")


def compile_baseline_strategy_config(
    *,
    query_text: str,
    symbol: str,
    baseline: Dict[str, Any],
    expiration: Optional[dict] = None,
    fixed_symbols: Optional[List[str]] = None,
) -> Dict[str, Any]:
    reject_self_referential_drop_query(query_text)
    plan = parse_strategy_query(query_text)
    compiled = apply_fixed_trigger_to_compiled_plan(
        plan.model_dump(),
        symbol=symbol,
        trigger_price=float(baseline["trigger_price"]),
    )
    config: Dict[str, Any] = {
        "query_text": query_text,
        "compiled_plan": compiled,
        "schedule_baseline": baseline,
        "capture_reference_ltp": True,
        "fixed_symbols": list(fixed_symbols or [symbol.strip().upper()]),
        "baseline_warning": (
            "The reference LTP and trigger price will remain fixed after scheduling. "
            "Live LTP will continue to update during monitoring."
        ),
    }
    if expiration:
        config["expiration"] = normalize_expiration_config(expiration)
    return config


def merge_baseline_into_order_fields(order_data, baseline: Dict[str, Any]) -> None:
    order_data.reference_ltp = float(baseline["reference_ltp"])
    order_data.trigger_price = float(baseline["trigger_price"])
    order_data.drop_percent = float(baseline.get("drop_percent") or DEFAULT_DROP_PERCENT)
    captured_at_raw = baseline.get("reference_ltp_captured_at")
    if captured_at_raw:
        try:
            order_data.reference_ltp_captured_at = datetime.fromisoformat(
                str(captured_at_raw).replace("Z", "+00:00")
            ).replace(tzinfo=None)
        except ValueError:
            order_data.reference_ltp_captured_at = datetime.utcnow()
