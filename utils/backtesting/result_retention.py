"""Shared retention rules for persisted and user-visible backtest results."""

from __future__ import annotations

from typing import Any, Mapping


MIN_RETAINED_TRADES = 9
MIN_RETAINED_WIN_RATE_PCT = 50.0
STANDARD_RETAINED_TRADES = 16
STANDARD_RETAINED_WIN_RATE_PCT = 50.0
HIGH_WIN_RETAINED_TRADES = 9
HIGH_WIN_RETAINED_WIN_RATE_PCT = 60.0
MIN_REVALIDATION_TRADES = 9
MIN_REVALIDATION_WIN_RATE_PCT = 35.0
RETENTION_POLICY_VERSION = "trades-16-win-50-or-trades-9-win-60-v2"


def is_retained_result(result: Mapping[str, Any]) -> bool:
    """Return whether a result has enough evidence to keep in the research DB."""
    try:
        total_trades = int(result.get("total_trades") or 0)
        win_rate_pct = float(result.get("win_rate_pct") or 0)
    except (TypeError, ValueError):
        return False
    return (
        total_trades >= STANDARD_RETAINED_TRADES
        and win_rate_pct >= STANDARD_RETAINED_WIN_RATE_PCT
    ) or (
        total_trades >= HIGH_WIN_RETAINED_TRADES
        and win_rate_pct >= HIGH_WIN_RETAINED_WIN_RATE_PCT
    )


def is_revalidation_candidate(result: Mapping[str, Any]) -> bool:
    """Return whether a rejected result is strong enough for periodic reconsideration."""
    try:
        total_trades = int(result.get("total_trades") or 0)
        win_rate_pct = float(result.get("win_rate_pct") or 0)
    except (TypeError, ValueError):
        return False
    return (
        not is_retained_result(result)
        and total_trades >= MIN_REVALIDATION_TRADES
        and win_rate_pct >= MIN_REVALIDATION_WIN_RATE_PCT
    )


def retention_failure_reason(result: Mapping[str, Any]) -> str:
    """Return a stable, readable explanation for a rejected result."""
    try:
        total_trades = int(result.get("total_trades") or 0)
        win_rate_pct = float(result.get("win_rate_pct") or 0)
    except (TypeError, ValueError):
        return "invalid_metrics"
    if total_trades < HIGH_WIN_RETAINED_TRADES and win_rate_pct < STANDARD_RETAINED_WIN_RATE_PCT:
        return "insufficient_trades_and_low_win_rate"
    if total_trades < HIGH_WIN_RETAINED_TRADES:
        return "insufficient_trades"
    if win_rate_pct < MIN_REVALIDATION_WIN_RATE_PCT:
        return "very_low_win_rate"
    if win_rate_pct < STANDARD_RETAINED_WIN_RATE_PCT:
        return "low_win_rate"
    if total_trades < STANDARD_RETAINED_TRADES and win_rate_pct < HIGH_WIN_RETAINED_WIN_RATE_PCT:
        return "insufficient_trades_for_standard_win_rate"
    return "qualified"


RETAINED_RESULT_SQL = (
    f"((r.total_trades >= {STANDARD_RETAINED_TRADES} "
    f"AND r.win_rate_pct >= {STANDARD_RETAINED_WIN_RATE_PCT:g}) "
    f"OR (r.total_trades >= {HIGH_WIN_RETAINED_TRADES} "
    f"AND r.win_rate_pct >= {HIGH_WIN_RETAINED_WIN_RATE_PCT:g}))"
)

RETAINED_ROW_SQL = RETAINED_RESULT_SQL.replace("r.", "")
