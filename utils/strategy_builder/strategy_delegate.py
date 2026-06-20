from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from utils.strategies.handlers import (
    HANDLERS,
    evaluate_time_based_buy,
    evaluate_time_based_exit,
)
from utils.strategies.risk_guard import can_place_order
from utils.strategies.strategy_query_catalog import build_order_context_from_rule, resolve_strategy_name
from utils.strategies.types import (
    AccountState,
    MarketSnapshot,
    OrderContext,
    ScannerMemory,
    ScriptDetails,
    StrategyDecision,
)


def _resolve_handler(canonical: str) -> Optional[Callable]:
    if canonical == "Time-Based Buy":
        return None
    if canonical == "Time-Based Exit":
        return evaluate_time_based_exit
    return HANDLERS.get(canonical)


def evaluate_delegated_strategy(
    rule: Any,
    *,
    plan_side: str,
    symbol: str,
    parent_ctx: OrderContext,
    snapshot: MarketSnapshot,
    memory: ScannerMemory,
    details: ScriptDetails,
    account: Optional[AccountState] = None,
    qty: Optional[int] = None,
) -> StrategyDecision:
    order_qty = int(qty if qty is not None else parent_ctx.remaining_qty or parent_ctx.qty or 0)
    delegated_ctx, issues = build_order_context_from_rule(
        rule,
        plan_side=plan_side,
        symbol=symbol,
        qty=order_qty,
        remaining_qty=parent_ctx.remaining_qty or order_qty,
    )
    if issues:
        message = issues[0].message
        return StrategyDecision("SKIP", "INVALID_STRATEGY_PARAMS", message, tracking_status="Invalid strategy params")
    if delegated_ctx is None:
        return StrategyDecision("SKIP", "INVALID_STRATEGY_PARAMS", "Could not build strategy context")

    delegated_ctx.highest_tracked_price = parent_ctx.highest_tracked_price
    delegated_ctx.executed_legs = list(parent_ctx.executed_legs or [])
    delegated_ctx.below_stop_loss_check_count = parent_ctx.below_stop_loss_check_count
    delegated_ctx.last_checked_ltp = parent_ctx.last_checked_ltp
    delegated_ctx.target_reached = parent_ctx.target_reached
    delegated_ctx.target_reached_at = parent_ctx.target_reached_at
    if not delegated_ctx.partial_legs:
        delegated_ctx.partial_legs = list(parent_ctx.partial_legs or [])

    canonical = resolve_strategy_name(delegated_ctx.canonical_strategy, plan_side)
    delegated_ctx.canonical_strategy = canonical
    delegated_ctx.strategy_type = canonical

    if canonical == "Time-Based Buy":
        wrapped_name = delegated_ctx.config.wrapped_strategy_type or "Quality Pullback Recovery Buy"
        wrapped_handler = HANDLERS.get(resolve_strategy_name(wrapped_name, "buy"))
        if not wrapped_handler:
            return StrategyDecision(
                "SKIP",
                "WRAPPED_STRATEGY_UNKNOWN",
                f"Unknown wrapped strategy: {wrapped_name}",
            )
        decision = evaluate_time_based_buy(delegated_ctx, snapshot, memory, details, wrapped_handler)
    else:
        handler = _resolve_handler(canonical)
        if not handler:
            return StrategyDecision("SKIP", "UNKNOWN_STRATEGY", f"Unknown strategy: {canonical}")
        decision = handler(delegated_ctx, snapshot, memory, details)

    account = account or AccountState()
    if decision.action == "EXECUTE" and decision.price is not None:
        requires_depth = canonical == "Order Book Strength Buy"
        risk = can_place_order(
            context=delegated_ctx,
            snapshot=snapshot,
            account=account,
            price=float(decision.price),
            qty=int(decision.qty or delegated_ctx.remaining_qty or delegated_ctx.qty),
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
                mutate=decision.mutate,
            )

    return decision


def map_delegated_decision_to_rule_action(
    decision: StrategyDecision,
    *,
    symbol: str,
    strategy_name: str,
    mutate: Optional[Dict[str, Any]] = None,
) -> StrategyDecision:
    payload = dict(mutate or {})
    if decision.mutate:
        payload.update(decision.mutate)

    if decision.action == "EXECUTE":
        return StrategyDecision(
            decision.action,
            decision.reason_code or "STRATEGY_EXECUTE",
            decision.reason or f"{strategy_name} ready for {symbol}",
            score=decision.score,
            price=decision.price,
            qty=decision.qty,
            source=decision.source or strategy_name,
            leg_id=decision.leg_id,
            mutate=payload,
        )

    tracking = decision.tracking_status or decision.reason or "Monitoring"
    action = decision.action if decision.action in {"TRACK", "WATCH", "NO_TRADE", "SKIP", "EXPIRE"} else "TRACK"
    return StrategyDecision(
        action,
        decision.reason_code or "STRATEGY_TRACKING",
        decision.reason or f"{strategy_name}: {tracking}",
        score=decision.score,
        tracking_status=tracking,
        expired=decision.expired,
        cancelled_reason=decision.cancelled_reason,
        mutate=payload,
    )
