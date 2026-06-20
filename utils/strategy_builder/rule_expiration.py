from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from utils.strategies.types import MarketSnapshot, OrderContext, ScriptDetails, StrategyDecision
from utils.strategy_builder.execution_depth import resolve_buy_limit_price
from utils.strategy_builder.schedule_baseline import (
    DEFAULT_EXPIRATION_ACTION,
    DEFAULT_MARKET_CLOSED_POLICY,
    SUPPORTED_EXPIRATION_ACTIONS,
)
from utils.strategies.helpers import is_market_depth_available


def _utc_now() -> datetime:
    return datetime.utcnow()


def expiration_config_from_context(ctx: OrderContext) -> dict:
    extra = dict(ctx.config.extra or {})
    return dict(extra.get("expiration") or {})


def has_expired(ctx: OrderContext, now: Optional[datetime] = None) -> bool:
    if not ctx.expiry_time:
        return False
    current = now or _utc_now()
    expiry = ctx.expiry_time.replace(tzinfo=None) if ctx.expiry_time.tzinfo else ctx.expiry_time
    return current >= expiry


def market_is_open(snapshot: MarketSnapshot) -> bool:
    return float(snapshot.ltp or 0) > 0


def _parse_optional_datetime(value) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _secondary_expiry_reached(expiration: dict, now: datetime) -> bool:
    secondary = _parse_optional_datetime(expiration.get("secondary_expires_at"))
    return secondary is not None and now >= secondary


def _build_secondary_expiry(primary_expiry: Optional[datetime], expiration: dict) -> datetime:
    configured = _parse_optional_datetime(expiration.get("secondary_expires_at"))
    if configured:
        return configured
    base = primary_expiry or _utc_now()
    hours = float(expiration.get("secondary_expiry_hours") or 24)
    return base + timedelta(hours=hours)


def evaluate_rule_based_expiration(
    ctx: OrderContext,
    snapshot: MarketSnapshot,
    details: ScriptDetails,
    *,
    now: Optional[datetime] = None,
) -> Optional[StrategyDecision]:
    """
    Apply expiration policy for rule-based orders after expiry_time.
    Returns None when expiry is not active or normal monitoring should continue.
    """
    if not has_expired(ctx, now=now):
        return None

    extra = dict(ctx.config.extra or {})
    if extra.get("expiration_executed") or extra.get("expiration_cancelled"):
        return StrategyDecision(
            "EXPIRE",
            "STRATEGY_EXPIRED",
            "Strategy already expired",
            expired=True,
            cancelled_reason="Strategy expired",
            tracking_status="Expired",
        )

    expiration = expiration_config_from_context(ctx)
    current = now or _utc_now()
    if _secondary_expiry_reached(expiration, current):
        return StrategyDecision(
            "EXPIRE",
            "EXPIRY_SECONDARY_CANCELLED",
            "Secondary expiration reached while waiting for market quote",
            expired=True,
            cancelled_reason="EXPIRY_SECONDARY_CANCELLED",
            tracking_status="Expired",
            mutate={
                "expiration_cancelled": True,
                "expiration_execution_reason": "EXPIRY_SECONDARY_CANCELLED",
            },
        )

    action = str(ctx.expiry_action or expiration.get("expiration_action") or DEFAULT_EXPIRATION_ACTION).upper()
    if action not in SUPPORTED_EXPIRATION_ACTIONS:
        action = DEFAULT_EXPIRATION_ACTION

    market_closed_policy = str(
        expiration.get("market_closed_policy") or DEFAULT_MARKET_CLOSED_POLICY
    ).upper()
    pending_market_open = bool(extra.get("expiration_pending_market_open"))

    if pending_market_open and not market_is_open(snapshot):
        return StrategyDecision(
            "TRACK",
            "EXPIRY_PENDING_MARKET_OPEN",
            "Waiting for next valid market quote at expiration",
            tracking_status="EXPIRY_PENDING_MARKET_OPEN",
        )

    if not market_is_open(snapshot):
        if market_closed_policy == "CANCEL_IF_MARKET_CLOSED":
            return StrategyDecision(
                "EXPIRE",
                "EXPIRY_CANCELLED",
                "Expired while market closed (cancel policy)",
                expired=True,
                cancelled_reason="EXPIRY_CANCELLED",
                tracking_status="Expired",
                mutate={
                    "expiration_cancelled": True,
                    "expiration_execution_reason": "EXPIRY_CANCELLED",
                },
            )
        if action in {"BUY_AT_PROTECTED_LTP", "BUY_AT_TOP_SELL"}:
            updated_expiration = dict(expiration)
            if not updated_expiration.get("secondary_expires_at"):
                updated_expiration["secondary_expires_at"] = _build_secondary_expiry(
                    ctx.expiry_time,
                    updated_expiration,
                ).isoformat()
            if market_closed_policy == "EXECUTE_AT_NEXT_VALID_MARKET_QUOTE":
                return StrategyDecision(
                    "TRACK",
                    "EXPIRY_PENDING_MARKET_OPEN",
                    "Waiting for next valid market quote at expiration",
                    tracking_status="EXPIRY_PENDING_MARKET_OPEN",
                    mutate={
                        "expiration_pending_market_open": True,
                        "expiration": updated_expiration,
                    },
                )
            if market_closed_policy == "KEEP_PENDING_UNTIL_SECONDARY_EXPIRY":
                return StrategyDecision(
                    "TRACK",
                    "EXPIRY_PENDING_SECONDARY",
                    "Waiting for market open until secondary expiration",
                    tracking_status="EXPIRY_PENDING_MARKET_OPEN",
                    mutate={
                        "expiration_pending_secondary": True,
                        "expiration": updated_expiration,
                    },
                )

    if action == "CANCEL":
        return StrategyDecision(
            "EXPIRE",
            "EXPIRY_CANCELLED",
            "Pullback trigger not reached before expiration",
            expired=True,
            cancelled_reason="EXPIRY_CANCELLED",
            tracking_status="Expired",
            mutate={
                "expiration_cancelled": True,
                "expiration_execution_reason": "EXPIRY_CANCELLED",
            },
        )

    slippage = float(
        ctx.max_allowed_slippage_percent
        or expiration.get("expiration_max_slippage_pct")
        or 1.0
    )
    ltp = float(snapshot.ltp or 0)
    if ltp <= 0:
        return StrategyDecision(
            "EXPIRE",
            "EXPIRY_QUOTE_UNAVAILABLE",
            "Expiration quote unavailable",
            expired=True,
            cancelled_reason="Expiration quote unavailable",
            tracking_status="Failed",
            mutate={"expiration_execution_reason": "EXPIRY_QUOTE_UNAVAILABLE"},
        )

    price_source = action
    exec_price = ltp
    source_label = "LTP"

    if action == "BUY_AT_TOP_SELL":
        if not is_market_depth_available(snapshot):
            fallback = str(expiration.get("top_sell_fallback") or "CANCEL").upper()
            if fallback == "FALLBACK_TO_PROTECTED_LTP":
                exec_price, source_label = resolve_buy_limit_price(snapshot, ltp, max_slippage_percent=slippage)
                price_source = "BUY_AT_PROTECTED_LTP"
            else:
                return StrategyDecision(
                    "EXPIRE",
                    "EXPIRY_TOP_SELL_UNAVAILABLE",
                    "Top-sell unavailable at expiration",
                    expired=True,
                    cancelled_reason="EXPIRY_TOP_SELL_UNAVAILABLE",
                    tracking_status="Expired",
                    mutate={"expiration_execution_reason": "EXPIRY_TOP_SELL_UNAVAILABLE"},
                )
        else:
            exec_price, source_label = resolve_buy_limit_price(snapshot, ltp, max_slippage_percent=slippage)
            price_source = "BUY_AT_TOP_SELL"
    elif action == "BUY_AT_PROTECTED_LTP":
        exec_price, source_label = resolve_buy_limit_price(snapshot, ltp, max_slippage_percent=slippage)
        price_source = "BUY_AT_PROTECTED_LTP"

    qty = int(ctx.remaining_qty or ctx.qty or 0)
    if qty <= 0:
        return StrategyDecision(
            "EXPIRE",
            "EXPIRY_INVALID_QTY",
            "Expiration execution blocked: invalid quantity",
            expired=True,
            cancelled_reason="Invalid quantity at expiration",
            tracking_status="Failed",
        )

    return StrategyDecision(
        "EXECUTE",
        price_source,
        f"Expiration action {price_source} at {exec_price}",
        price=exec_price,
        qty=qty,
        source=source_label,
        mutate={
            "expiration_executed": True,
            "expiration_execution_reason": price_source,
            "expiration_execution_price": exec_price,
            "expiration_execution_attempted_at": _utc_now().isoformat(),
        },
    )


def should_skip_normal_trigger_after_expiry(ctx: OrderContext, now: Optional[datetime] = None) -> bool:
    """At or after expiry, do not start a new normal trigger evaluation."""
    return has_expired(ctx, now=now)
