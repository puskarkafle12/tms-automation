from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional

from utils.strategies.aliases import canonical_strategy_name
from utils.strategies.handlers import HANDLERS, evaluate_time_based_buy, evaluate_time_based_exit
from utils.strategies.order_context import build_order_context
from utils.strategies.risk_guard import can_place_order
from utils.strategies.types import AccountState, MarketSnapshot, ScannerMemory, ScriptDetails, StrategyDecision


def evaluate_strategy(
    db_order,
    snapshot: MarketSnapshot,
    memory: ScannerMemory,
    details: ScriptDetails,
    account: Optional[AccountState] = None,
) -> StrategyDecision:
    ctx = build_order_context(db_order)
    account = account or AccountState()
    canonical = ctx.canonical_strategy

    if canonical == "Time-Based Buy":
        wrapped_name = ctx.config.wrapped_strategy_type or "Quality Pullback Recovery Buy"
        wrapped_handler = HANDLERS.get(wrapped_name)
        if not wrapped_handler:
            return StrategyDecision("SKIP", "WRAPPED_STRATEGY_UNKNOWN", f"Unknown wrapped strategy: {wrapped_name}")
        return evaluate_time_based_buy(ctx, snapshot, memory, details, wrapped_handler)

    if canonical == "Time-Based Exit":
        return evaluate_time_based_exit(ctx, snapshot, memory, details)

    handler: Optional[Callable] = HANDLERS.get(canonical)
    if not handler:
        return StrategyDecision("SKIP", "UNKNOWN_STRATEGY", f"Unknown strategy: {ctx.strategy_type}", tracking_status="Monitoring")

    decision = handler(ctx, snapshot, memory, details)

    if decision.action == "EXECUTE" and decision.price is not None:
        requires_depth = canonical == "Order Book Strength Buy"
        risk = can_place_order(
            context=ctx,
            snapshot=snapshot,
            account=account,
            price=float(decision.price),
            qty=int(decision.qty or ctx.remaining_qty or ctx.qty),
            requires_depth=requires_depth,
            strategy_expired=decision.expired,
        )
        if not risk.allowed:
            return StrategyDecision(
                "NO_TRADE",
                risk.reason_code,
                risk.reason,
                score=decision.score,
                tracking_status="Blocked by risk guard",
            )

    if decision.mutate:
        config_payload = dict(getattr(db_order, "strategy_config", None) or {})
        for key, value in decision.mutate.items():
            if hasattr(db_order, key):
                setattr(db_order, key, value)
            if key in {"sold_target1", "sold_target2", "break_even_armed"}:
                config_payload[key] = value
        if config_payload:
            db_order.strategy_config = config_payload

    return decision


def decision_to_execute_dict(decision: StrategyDecision) -> Optional[dict]:
    if decision.action != "EXECUTE" or decision.price is None:
        return None
    payload = {
        "action": "execute",
        "price": float(decision.price),
        "reason": f"{decision.reason_code}: {decision.reason}",
    }
    if decision.qty is not None:
        payload["qty"] = int(decision.qty)
    if decision.source:
        payload["source"] = decision.source
    if decision.leg_id:
        payload["leg_id"] = decision.leg_id
    return payload


def resolve_canonical(strategy_type: str, side: str) -> str:
    return canonical_strategy_name(strategy_type, side)
