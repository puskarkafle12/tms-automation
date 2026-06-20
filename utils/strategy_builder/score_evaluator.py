from __future__ import annotations

from typing import Any, Dict, List

from utils.strategy_builder.history_service import TargetHistory
from utils.strategy_builder.strategy_models import ConditionResult


def evaluate_score_block(
    score_items: List[Dict[str, Any]],
    flat: Dict[str, Any],
    history: TargetHistory,
    *,
    required_score: float,
    evaluate_node,
) -> tuple[bool, List[Dict[str, Any]], float]:
    breakdown: List[Dict[str, Any]] = []
    total = 0.0
    for item in score_items:
        weight = float(item.get("weight") or 1)
        condition = item.get("condition")
        label = item.get("label") or str(item.get("expression") or "condition")
        matched = False
        if condition:
            matched = evaluate_node(condition, flat, history).matched
        points = weight if matched else 0.0
        total += points
        breakdown.append({
            "label": label,
            "weight": weight,
            "matched": matched,
            "points": points,
        })
    return total >= required_score, breakdown, total
