"""Adaptive out-of-sample selection of one exit + stop champion.

The first stage ranks every approved sell rule with a neutral fixed stop.
The second stage tests all approved stop configurations against only the
leading sell rules. This bounds CPU work while keeping selection separate
from the in-sample result eventually shown to users.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Sequence


STOP_CONFIGURATIONS = (
    {"id": "fixed_tight_4", "label": "Tight fixed stop (4%)", "stop_loss_pct": 4.0, "trailing_stop_pct": None, "atr_stop_multiple": None, "break_even_trigger_pct": None},
    {"id": "fixed_balanced_6", "label": "Balanced fixed stop (6%)", "stop_loss_pct": 6.0, "trailing_stop_pct": None, "atr_stop_multiple": None, "break_even_trigger_pct": None},
    {"id": "fixed_wide_8", "label": "Wide fixed stop (8%)", "stop_loss_pct": 8.0, "trailing_stop_pct": None, "atr_stop_multiple": None, "break_even_trigger_pct": None},
    {"id": "fixed_7_trailing_5", "label": "Initial 7% + trailing 5%", "stop_loss_pct": 7.0, "trailing_stop_pct": 5.0, "atr_stop_multiple": None, "break_even_trigger_pct": None},
    {"id": "atr_2", "label": "ATR volatility stop (2× ATR)", "stop_loss_pct": 8.0, "trailing_stop_pct": None, "atr_stop_multiple": 2.0, "break_even_trigger_pct": None},
    {"id": "fixed_7_break_even_5", "label": "Initial 7% + break-even after +5%", "stop_loss_pct": 7.0, "trailing_stop_pct": None, "atr_stop_multiple": None, "break_even_trigger_pct": 5.0},
)


def protection_score(summary: Dict[str, Any]) -> float:
    """Conservative score that cannot be dominated by raw win rate."""
    trades = max(0, int(summary.get("total_trades") or 0))
    if trades == 0:
        return -1_000_000.0
    win_rate = float(summary.get("win_rate_pct") or 0)
    expectancy = float(summary.get("expectancy_pct") or 0)
    net_return = float(summary.get("net_return_pct") or 0)
    drawdown = abs(float(summary.get("max_drawdown_pct") or 0))
    profit_factor = summary.get("profit_factor")
    profit_factor = min(3.0, max(0.0, float(profit_factor))) if profit_factor is not None else 0.0
    sharpe = summary.get("sharpe_ratio")
    sharpe = max(-2.0, min(3.0, float(sharpe))) if sharpe is not None else 0.0
    sample_weight = math.sqrt(trades / (trades + 9))
    thin_sample_penalty = max(0, 9 - trades) * 6.0
    return round(
        expectancy * 4.0
        + profit_factor * 7.0
        + sharpe * 4.0
        + net_return * .20
        + win_rate * sample_weight * .12
        - drawdown * .55
        - thin_sample_penalty,
        6,
    )


def choose_protection_champion(
    exit_rules: Sequence[tuple[str, str]],
    evaluate: Callable[[str, str, Dict[str, Any]], Dict[str, Any]],
    *,
    finalist_exit_count: int = 4,
) -> Dict[str, Any]:
    """Evaluate a bounded matrix and return one auditable OOS champion."""
    neutral = next(item for item in STOP_CONFIGURATIONS if item["id"] == "fixed_balanced_6")
    stage_one: List[Dict[str, Any]] = []
    for exit_rule_id, exit_condition in exit_rules:
        summary = evaluate(exit_rule_id, exit_condition, neutral)
        stage_one.append({
            "exit_rule_id": exit_rule_id,
            "exit_condition": exit_condition,
            "stop": dict(neutral),
            "summary": summary,
            "selection_score": protection_score(summary),
        })
    ranked_exits = sorted(
        stage_one,
        key=lambda item: (
            item["selection_score"],
            int(item["summary"].get("total_trades") or 0),
            str(item["exit_rule_id"]),
        ),
        reverse=True,
    )[:max(1, int(finalist_exit_count))]

    finalists: List[Dict[str, Any]] = []
    for exit_candidate in ranked_exits:
        for stop in STOP_CONFIGURATIONS:
            if stop["id"] == neutral["id"]:
                summary = exit_candidate["summary"]
            else:
                summary = evaluate(
                    exit_candidate["exit_rule_id"],
                    exit_candidate["exit_condition"],
                    stop,
                )
            finalists.append({
                "exit_rule_id": exit_candidate["exit_rule_id"],
                "exit_condition": exit_candidate["exit_condition"],
                "stop": dict(stop),
                "summary": summary,
                "selection_score": protection_score(summary),
            })
    champion = max(
        finalists,
        key=lambda item: (
            item["selection_score"],
            int(item["summary"].get("total_trades") or 0),
            -float(item["summary"].get("max_drawdown_pct") or 0),
            str(item["exit_rule_id"]),
            str(item["stop"]["id"]),
        ),
    )
    leaderboard = sorted(
        finalists,
        key=lambda item: item["selection_score"],
        reverse=True,
    )[:8]
    return {
        "method": "two_stage_locked_oos_v1",
        "sell_rules_tested": len(stage_one),
        "stop_methods_tested": len(STOP_CONFIGURATIONS),
        "final_combinations_tested": len(finalists),
        "total_evaluations": len(stage_one) + len(finalists) - len(ranked_exits),
        "champion": champion,
        "leaderboard": leaderboard,
    }
