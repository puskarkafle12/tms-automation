from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from utils.strategy_builder.execution_sizing import resolve_order_quantity
from utils.strategy_builder.rule_evaluator import evaluate_expression
from utils.strategy_builder.history_service import TargetHistory
from utils.strategy_builder.strategy_models import PositionExitAction, StrategyPlanAST


def evaluate_position_exits(
    plan: StrategyPlanAST,
    symbol: str,
    flat: Dict[str, Any],
    history: TargetHistory,
    *,
    holding_qty: int = 0,
    form_qty: int = 0,
) -> Optional[Dict[str, Any]]:
    if not plan.position_exit:
        return None
    position = dict(history.position or {})
    for action in plan.position_exit:
        if not action.when:
            continue
        matched = evaluate_expression(action.when, flat, history).matched
        if not matched:
            continue
        if action.action == "move_stop_to_entry" and position.get("entry_price"):
            position["stop_floor"] = float(position["entry_price"])
            history.position = position
            continue
        if action.action == "lock_profit_pct" and position.get("entry_price") and action.lock_profit_pct is not None:
            floor_price = float(position["entry_price"]) * (1.0 + float(action.lock_profit_pct) / 100.0)
            position["stop_floor"] = max(float(position.get("stop_floor") or 0), floor_price)
            history.position = position
            continue
        if action.action == "trail_remaining":
            position["trail_remaining"] = True
            history.position = position
            continue
        if action.action == "sell":
            qty = resolve_order_quantity(
                order_mode=action.order_mode or "percent_of_holding",
                order_value=action.order_value,
                ltp=flat.get("ltp"),
                holding_qty=holding_qty,
                form_qty=form_qty,
            )
            if qty > 0:
                return {
                    "action": "sell",
                    "qty": qty,
                    "reason": "position_exit",
                }
    return None
