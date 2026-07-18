"""Statistical validation and robust ranking for professional backtest results."""

from __future__ import annotations

import math
from datetime import date
from typing import Any, Dict, Iterable, List, Sequence, Tuple


ROBUST_SCORE_VERSION = "robust-score-v1"


def wilson_interval(wins: int, total: int, z: float = 1.959963984540054) -> Tuple[float, float]:
    if total <= 0:
        return 0.0, 0.0
    proportion = wins / total
    denominator = 1 + z * z / total
    centre = proportion + z * z / (2 * total)
    margin = z * math.sqrt((proportion * (1 - proportion) + z * z / (4 * total)) / total)
    return round(max(0.0, (centre - margin) / denominator) * 100, 2), round(min(1.0, (centre + margin) / denominator) * 100, 2)


def positive_win_rate_p_value(wins: int, total: int) -> float:
    """One-sided normal approximation for win probability above 50%."""
    if total <= 0:
        return 1.0
    z = (wins - total * 0.5) / math.sqrt(total * 0.25)
    return max(0.0, min(1.0, 0.5 * math.erfc(z / math.sqrt(2))))


def fdr_benjamini_hochberg(p_values: Sequence[float]) -> List[float]:
    if not p_values:
        return []
    count = len(p_values)
    ordered = sorted(enumerate(p_values), key=lambda item: item[1])
    adjusted = [1.0] * count
    running = 1.0
    for rank_index in range(count - 1, -1, -1):
        original_index, value = ordered[rank_index]
        rank = rank_index + 1
        running = min(running, float(value) * count / rank)
        adjusted[original_index] = round(max(0.0, min(1.0, running)), 6)
    return adjusted


def data_completeness_pct(bars: Sequence[Any]) -> float:
    if len(bars) < 2:
        return 0.0
    first = date.fromisoformat(str(bars[0].day))
    last = date.fromisoformat(str(bars[-1].day))
    expected = max(2, round(((last - first).days + 1) * 5 / 7))
    return round(min(100.0, len({str(bar.day) for bar in bars}) / expected * 100), 2)


def liquidity_score(bars: Sequence[Any]) -> float:
    recent = [max(float(bar.volume or 0), 0) for bar in bars[-60:]]
    if not recent:
        return 0.0
    ordered = sorted(recent)
    median = ordered[len(ordered) // 2]
    return round(min(100.0, max(0.0, math.log10(median + 1) / 6 * 100)), 2)


def walk_forward_profitable_pct(trades: Sequence[Dict[str, Any]], bars: Sequence[Any]) -> float | None:
    """Measure fixed-strategy stability across 6-month test folds after 2 years."""
    if len(bars) < 630:
        return None
    exits = [(str(trade.get("exit_date") or ""), float(trade.get("pnl") or 0)) for trade in trades]
    profitable = folds = 0
    start = 504
    while start < len(bars):
        end = min(start + 126, len(bars))
        start_day, end_day = str(bars[start].day), str(bars[end - 1].day)
        fold_pnl = sum(pnl for exit_day, pnl in exits if start_day <= exit_day <= end_day)
        profitable += int(fold_pnl > 0)
        folds += 1
        start += 126
    return round(profitable / folds * 100, 2) if folds else None


def build_validation_fields(
    full_summary: Dict[str, Any], oos_summary: Dict[str, Any],
    bars: Sequence[Any], full_trades: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    total = int(full_summary.get("total_trades") or 0)
    wins = int(full_summary.get("wins") or 0)
    ci_low, ci_high = wilson_interval(wins, total)
    oos_trades = int(oos_summary.get("total_trades") or 0)
    completeness = data_completeness_pct(bars)
    warnings: List[str] = []
    if oos_trades < 10:
        warnings.append("INSUFFICIENT_OOS_TRADES")
    if float(oos_summary.get("net_return_pct") or 0) <= 0:
        warnings.append("NON_POSITIVE_OOS_RETURN")
    if completeness < 95:
        warnings.append("INCOMPLETE_HISTORY")
    if any(float(bar.volume or 0) <= 0 for bar in bars):
        warnings.append("ZERO_VOLUME_BARS")
    status = "recommended" if not warnings[:3] and total >= 20 else "review" if total >= 5 else "insufficient_sample"
    return {
        "wins": wins, "losses": int(full_summary.get("losses") or 0),
        "win_rate_ci_low": ci_low, "win_rate_ci_high": ci_high,
        "oos_trades": oos_trades,
        "oos_win_rate_pct": float(oos_summary.get("win_rate_pct") or 0),
        "oos_return_pct": float(oos_summary.get("net_return_pct") or 0),
        "oos_expectancy_pct": float(oos_summary.get("expectancy_pct") or 0),
        "oos_sharpe_ratio": oos_summary.get("sharpe_ratio"),
        "oos_max_drawdown_pct": float(oos_summary.get("max_drawdown_pct") or 0),
        "walk_forward_profitable_pct": walk_forward_profitable_pct(full_trades, bars),
        "data_completeness_pct": completeness,
        "liquidity_score": liquidity_score(bars),
        "p_value": positive_win_rate_p_value(wins, total),
        "warning_codes": warnings, "recommendation_status": status,
    }


def _percentile(values: Sequence[float]) -> List[float]:
    if not values:
        return []
    ordered = sorted((value, index) for index, value in enumerate(values))
    ranks = [0.0] * len(values)
    denominator = max(len(values) - 1, 1)
    cursor = 0
    while cursor < len(ordered):
        end = cursor
        while end + 1 < len(ordered) and ordered[end + 1][0] == ordered[cursor][0]:
            end += 1
        rank = ((cursor + end) / 2) / denominator
        for position in range(cursor, end + 1):
            ranks[ordered[position][1]] = rank
        cursor = end + 1
    return ranks


def assign_robust_scores(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Assign universe-relative scores and FDR values in-place."""
    if not rows:
        return rows
    expectancy = _percentile([float(row.get("oos_expectancy_pct") or 0) for row in rows])
    returns = _percentile([float(row.get("oos_return_pct") or 0) for row in rows])
    sharpes = _percentile([float(row.get("oos_sharpe_ratio") or -10) for row in rows])
    drawdowns = _percentile([-float(row.get("oos_max_drawdown_pct") or 0) for row in rows])
    consistency = _percentile([float(row.get("walk_forward_profitable_pct") or 0) for row in rows])
    q_values = fdr_benjamini_hochberg([float(row.get("p_value") or 1) for row in rows])
    for index, row in enumerate(rows):
        reliability = min(int(row.get("oos_trades") or 0) / 20, 1)
        score = 100 * (
            .30 * expectancy[index] + .20 * returns[index] + .15 * sharpes[index]
            + .15 * drawdowns[index] + .10 * consistency[index] + .10 * reliability
        )
        if float(row.get("oos_return_pct") or 0) <= 0:
            score = min(score, 49)
        if int(row.get("oos_trades") or 0) < 10:
            score = min(score, 39)
        if float(row.get("data_completeness_pct") or 0) < 95:
            score = min(score, 39)
        row["robust_score"] = round(max(0.0, min(100.0, score)), 2)
        row["fdr_q_value"] = q_values[index]
        if q_values[index] > .10:
            warnings = list(row.get("warning_codes") or [])
            if "MULTIPLE_TESTING_RISK" not in warnings:
                warnings.append("MULTIPLE_TESTING_RISK")
            row["warning_codes"] = warnings
    return rows
