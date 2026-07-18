"""Current completed-session signals supported by persisted historical backtests."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Sequence

from utils.backtesting.presets import build_preset_query
from utils.strategy_builder.rule_evaluator import evaluate_rule, update_history_from_snapshot
from utils.strategy_builder.strategy_parser import parse_strategy_query, retarget_strategy_query
from utils.strategy_builder.history_service import TargetHistory


RELIABILITY_VERSION = "strong-buy-reliability-v1"


def condition_progress(conditions: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Summarize current entry-condition progress without calling it a forecast."""
    total = len(conditions)
    passed = sum(1 for item in conditions if item.get("matched"))
    progress = round((passed / total) * 100, 2) if total else 0.0
    return {
        "conditions_passed": passed,
        "conditions_total": total,
        "condition_progress_pct": progress,
        "near_trigger": bool(total >= 2 and passed < total and progress >= 60),
    }


def evaluate_latest_completed_signal(preset: Dict[str, Any], symbol: str, rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Evaluate the previous and latest completed rows with the production rule evaluator."""
    if len(rows) < 2:
        return {"active": False, "status": "UNAVAILABLE", "conditions": [], "reason": "At least two completed sessions are required."}
    plan = parse_strategy_query(build_preset_query(preset, symbol))
    rule = plan.rules[0]
    history = TargetHistory()
    # The largest preset window is 200 sessions. Extra rows retain enough warm-up
    # history without replaying an entire multi-year backtest for current evidence.
    scoped = rows[-260:]
    for row in scoped[:-2]:
        update_history_from_snapshot(history, row)
    update_history_from_snapshot(history, scoped[-2])
    evaluate_rule(rule, symbol, scoped[-2], history, trigger_on_cross=True)
    update_history_from_snapshot(history, scoped[-1])
    result = evaluate_rule(rule, symbol, scoped[-1], history, trigger_on_cross=True)
    conditions = [item.model_dump(mode="json") for item in result.conditions]
    progress = condition_progress(conditions)
    passed = [item["expression"] for item in conditions if item.get("matched")]
    failed = [item["expression"] for item in conditions if not item.get("matched")]
    latest = scoped[-1]
    reason = (
        f"{symbol} generated a current {preset['name']} entry signal because all strategy conditions "
        f"passed on the latest completed session."
        if result.final_result else
        f"{symbol} does not have a new {preset['name']} entry signal on the latest completed session."
    )
    return {
        "active": bool(result.final_result), "status": result.status,
        "strategy_condition": preset["condition"], "conditions": conditions,
        "passed_conditions": passed, "failed_conditions": failed, "reason": reason,
        "latest_values": {
            "ltp": latest.get("ltp"), "change_percent": latest.get("change_percent"),
            "volume": latest.get("volume"), "volume_ratio_20": latest.get("technical_volume_ratio_20"),
            "rsi_14": latest.get("technical_rsi_14"), "macd": latest.get("technical_macd"),
            "macd_histogram": latest.get("technical_macd_histogram"), "sma_20": latest.get("technical_sma_20"),
            "sma_50": latest.get("technical_sma_50"), "adx_14": latest.get("technical_adx_14"),
            "plus_di_14": latest.get("technical_plus_di_14"), "minus_di_14": latest.get("technical_minus_di_14"),
            "technical_signal": latest.get("technical_signal"),
            "technical_signal_score": latest.get("technical_signal_score"),
        },
        **progress,
    }


def evaluate_latest_completed_query(
    query_text: str, symbol: str, rows: Sequence[Dict[str, Any]], *, strategy_name: str,
) -> Dict[str, Any]:
    """Evaluate a custom query with the same production rule evaluator used by plans."""
    if len(rows) < 2:
        return {"active": False, "status": "UNAVAILABLE", "conditions": [], "reason": "At least two completed sessions are required."}
    executable_query = retarget_strategy_query(query_text, [symbol])
    plan = parse_strategy_query(executable_query)
    scoped = rows[-260:]
    all_conditions: List[Dict[str, Any]] = []
    active_rules: List[str] = []
    latest_values: Dict[str, Any] = {}
    for rule in plan.rules:
        history = TargetHistory()
        for row in scoped[:-2]:
            update_history_from_snapshot(history, row)
        update_history_from_snapshot(history, scoped[-2])
        evaluate_rule(rule, symbol, scoped[-2], history, trigger_on_cross=True)
        update_history_from_snapshot(history, scoped[-1])
        result = evaluate_rule(rule, symbol, scoped[-1], history, trigger_on_cross=True)
        conditions = [item.model_dump(mode="json") for item in result.conditions]
        all_conditions.extend([{**item, "rule": rule.name} for item in conditions])
        if result.final_result:
            active_rules.append(rule.name)
    latest = scoped[-1]
    for key in (
        "ltp", "change_percent", "volume", "technical_volume_ratio_20", "technical_rsi_14",
        "technical_macd", "technical_macd_histogram", "technical_adx_14", "technical_supertrend",
        "technical_ppo_histogram", "technical_signal", "technical_signal_score",
    ):
        latest_values[key] = latest.get(key)
    active = bool(active_rules)
    progress = condition_progress(all_conditions)
    return {
        "active": active, "status": "MATCHED" if active else "NO_MATCH",
        "strategy_condition": "Custom Strategy Language query",
        "conditions": all_conditions,
        "passed_conditions": [item["expression"] for item in all_conditions if item.get("matched")],
        "failed_conditions": [item["expression"] for item in all_conditions if not item.get("matched")],
        "reason": (
            f"{symbol} generated a current {strategy_name} entry signal from rule(s): {', '.join(active_rules)}."
            if active else f"{symbol} has no new {strategy_name} entry signal on the latest completed session."
        ),
        "matched_rules": active_rules, "latest_values": latest_values,
        **progress,
    }


def reliability_score(summary: Dict[str, Any], *, confidence_score: float, technical_score: float,
                      liquidity_score: float, fresh: bool, indicators_complete: bool) -> Dict[str, Any]:
    trades = int(summary.get("total_trades") or 0)
    win_rate = float(summary.get("win_rate_pct") or 0)
    net_return = float(summary.get("net_return_pct") or 0)
    profit_factor = summary.get("profit_factor")
    sharpe = summary.get("sharpe_ratio")
    drawdown = float(summary.get("max_drawdown_pct") or 100)
    components = {
        "historical_win_rate": min(15, max(0, (win_rate - 40) / 30 * 15)),
        "completed_trades": min(10, trades / 50 * 10),
        "confidence": min(10, max(0, confidence_score) / 100 * 10),
        "net_return": min(10, max(0, math.log1p(max(net_return, 0)) / math.log(201) * 10)),
        "profit_factor": min(10, max(0, (float(profit_factor or 0) - 1) / 1.5 * 10)),
        "sharpe": min(10, max(0, float(sharpe or 0) / 2 * 10)),
        "drawdown_protection": min(10, max(0, (40 - drawdown) / 40 * 10)),
        "current_technical_confirmation": min(10, max(0, technical_score) / 100 * 10),
        "liquidity": min(8, max(0, liquidity_score) / 100 * 8),
        "data_freshness": 7 if fresh else 0,
    }
    penalties: List[Dict[str, Any]] = []
    if trades < 20: penalties.append({"code": "FEWER_THAN_20_TRADES", "points": 20})
    if drawdown >= 30: penalties.append({"code": "EXCESSIVE_DRAWDOWN", "points": 15})
    if float(sharpe or 0) < 0: penalties.append({"code": "NEGATIVE_SHARPE", "points": 10})
    if liquidity_score < 35: penalties.append({"code": "WEAK_LIQUIDITY", "points": 10})
    if not fresh: penalties.append({"code": "STALE_DATA", "points": 25})
    if not indicators_complete: penalties.append({"code": "MISSING_INDICATORS", "points": 15})
    gross_wins = float(summary.get("gross_profit") or 0)
    largest_win = float(summary.get("largest_winning_trade") or 0)
    if gross_wins > 0 and largest_win / gross_wins > .5:
        penalties.append({"code": "CONCENTRATED_WIN_DEPENDENCY", "points": 10})
    raw = sum(components.values())
    score = max(0, min(100, raw - sum(item["points"] for item in penalties)))
    return {"version": RELIABILITY_VERSION, "score": round(score, 2),
            "raw_score": round(raw, 2), "components": {key: round(value, 2) for key, value in components.items()},
            "penalties": penalties}


def qualifies_default(summary: Dict[str, Any], *, active: bool, fresh: bool,
                      indicators_complete: bool, liquidity_score: float) -> bool:
    return bool(
        active and fresh and indicators_complete and liquidity_score >= 35
        and int(summary.get("total_trades") or 0) >= 20
        and float(summary.get("win_rate_pct") or 0) >= 50
        and float(summary.get("net_return_pct") or 0) > 0
        and (summary.get("profit_factor") is None or float(summary["profit_factor"]) > 1.20)
        and float(summary.get("sharpe_ratio") or 0) > .50
        and float(summary.get("max_drawdown_pct") or 100) < 30
    )
