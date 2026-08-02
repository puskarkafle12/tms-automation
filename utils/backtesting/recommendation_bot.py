"""Causal portfolio replay for recommendation-filter trading bots.

The replay intentionally calculates win rate and confidence from trades that
finished before each signal.  It never uses the final backtest summary as if it
had been known at the historical signal date.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
import math
from typing import Any, Dict, Iterable, List

from sqlalchemy import bindparam, text

from utils.backtesting.portfolio import replay_shared_capital


FILTER_FIELDS = {
    "symbol": "text", "strategy": "text", "sector": "text",
    "win_rate_pct": "number", "confidence_floor_pct": "number",
    "prior_trades": "number", "average_volume_20": "number",
    "prior_expectancy_pct": "number", "prior_profit_factor": "number",
    "recent_win_rate_pct": "number", "recent_expectancy_pct": "number",
    "recent_trades": "number",
    "entry_price": "number", "holding_days": "number",
}
FILTER_OPERATORS = {"eq", "neq", "gt", "gte", "lt", "lte", "contains"}


def _as_date(value: Any) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def _wilson_floor(wins: int, trades: int) -> float:
    if trades <= 0:
        return 0.0
    rate = wins / trades
    z = 1.96
    denominator = 1 + z * z / trades
    centre = rate + z * z / (2 * trades)
    spread = z * math.sqrt((rate * (1 - rate) + z * z / (4 * trades)) / trades)
    return 100 * (centre - spread) / denominator


def _completed_trade_count(summary: Dict[str, Any]) -> int:
    return max(
        0,
        int(summary.get("accepted_signals") or 0)
        - int(summary.get("open_positions_at_end") or 0),
    )


def _benchmark_period_return(
    proxy_rows: Iterable[Dict[str, Any]], period_start: date, period_end: date,
) -> float:
    value = 1.0
    found = False
    for row in proxy_rows:
        session_date = _as_date(row["session_date"])
        if period_start <= session_date <= period_end:
            value *= 1 + float(row.get("daily_return") or 0)
            found = True
    return round((value - 1) * 100, 4) if found else 0.0


def _optimize_multi_trade_portfolio(
    simulations: Dict[str, List[Dict[str, Any]]],
    config: Dict[str, Any],
    allocation: Dict[str, Any],
    proxy_rows: Iterable[Dict[str, Any]],
    start_date: date,
    end_date: date,
) -> Dict[str, Any] | None:
    """Select a diversified setup on early history and verify it on untouched history."""
    split_date = start_date + timedelta(days=max(1, int((end_date - start_date).days * 0.7)))
    validation_start = split_date + timedelta(days=1)
    training_benchmark = _benchmark_period_return(proxy_rows, start_date, split_date)
    validation_benchmark = _benchmark_period_return(proxy_rows, validation_start, end_date)
    position_options = sorted({2, 3, 5, min(8, max(2, int(config["max_positions"])))})
    stock_options = sorted({10.0, 15.0, 20.0, float(config["max_stock_pct"])})
    sector_options = sorted({40.0, 60.0, float(config["max_sector_pct"])})
    trials = []
    for rule, simulated in simulations.items():
        training_trades = [
            item for item in simulated
            if _as_date(item["entry_date"]) <= split_date
            and _as_date(item["exit_date"]) <= split_date
        ]
        validation_trades = [
            item for item in simulated
            if validation_start <= _as_date(item["entry_date"]) <= end_date
            and _as_date(item["exit_date"]) <= end_date
        ]
        for max_positions in position_options:
            for max_stock_pct in stock_options:
                # Do not test configurations that can never deploy at least half
                # the portfolio when enough independent candidates are available.
                if max_positions * max_stock_pct < 50:
                    continue
                for max_sector_pct in sector_options:
                    trial_allocation = {
                        **allocation,
                        "max_positions": max_positions,
                        "max_stock_pct": max_stock_pct,
                        "max_sector_pct": max_sector_pct,
                        "capture_executions": False,
                    }
                    training, _ = replay_shared_capital(
                        training_trades, config["initial_capital"], trial_allocation,
                    )
                    completed = _completed_trade_count(training)
                    if completed < 8:
                        continue
                    net_return = float(training["net_return_pct"])
                    drawdown = float(training["max_drawdown_pct"])
                    alpha = net_return - training_benchmark
                    trials.append({
                        "score": (
                            alpha > 0,
                            net_return > 0,
                            alpha,
                            net_return / max(1.0, drawdown),
                            -drawdown,
                            completed,
                        ),
                        "config": {
                            "max_positions": max_positions,
                            "max_stock_pct": max_stock_pct,
                            "max_sector_pct": max_sector_pct,
                            "exit_strategy": rule,
                        },
                        "training": {
                            **training,
                            "completed_trades": completed,
                            "benchmark_return_pct": training_benchmark,
                            "excess_return_pct": round(alpha, 4),
                            "win_rate_pct": round(
                                100 * int(training.get("winning_trades") or 0) / completed, 2,
                            ),
                        },
                        "validation_trades": validation_trades,
                        "allocation": trial_allocation,
                    })
    if not trials:
        return None
    winner = max(trials, key=lambda item: item["score"])
    validation, _ = replay_shared_capital(
        winner["validation_trades"], config["initial_capital"], winner["allocation"],
    )
    validation_count = _completed_trade_count(validation)
    validation_return = float(validation["net_return_pct"])
    validation_alpha = validation_return - validation_benchmark
    validation_wins = int(validation.get("winning_trades") or 0)
    validation_floor = _wilson_floor(validation_wins, validation_count)
    validation_win_rate = round(
        100 * validation_wins / max(1, validation_count), 2,
    )
    paper_ready = (
        validation_count >= 8
        and validation_return > 0
        and validation_alpha > 0
        and validation_floor >= 30
        and float(validation["max_drawdown_pct"]) <= 10
    )
    return {
        "training_end": split_date.isoformat(),
        "validation_start": validation_start.isoformat(),
        "tested_configurations": len(trials),
        "suggested_config": winner["config"],
        "training": winner["training"],
        "validation": {
            **validation,
            "completed_trades": validation_count,
            "benchmark_return_pct": validation_benchmark,
            "excess_return_pct": round(validation_alpha, 4),
            "win_rate_pct": validation_win_rate,
            "win_rate_floor_pct": round(validation_floor, 2),
        },
        "paper_ready": paper_ready,
        "decision": "paper_candidate" if paper_ready else "stay_in_cash",
        "decision_reason": (
            "The diversified setup produced positive net return, beat the market proxy, and stayed within "
            "the drawdown limit in the untouched validation period."
            if paper_ready
            else "The best training setup did not yet beat every profit, benchmark, sample-size, confidence, "
            "and drawdown gate in the untouched validation period."
        ),
        "note": (
            "Position count, allocation, sector cap, and exit rule were ranked only on the first 70% of "
            "history. The last 30% was not used for selection."
        ),
    }


def _matches_filter(row: Dict[str, Any], rule: Dict[str, Any]) -> bool:
    field = str(rule.get("field") or "")
    operator = str(rule.get("operator") or "").lower()
    if field not in FILTER_FIELDS or operator not in FILTER_OPERATORS:
        raise ValueError(f"Unsupported recommendation bot filter: {field or 'missing field'} {operator}.")
    source = row.get(field)
    requested = rule.get("value")
    if FILTER_FIELDS[field] == "number":
        try:
            left, right = float(source or 0), float(requested)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} requires a numeric value.") from exc
        return {
            "eq": left == right, "neq": left != right, "gt": left > right,
            "gte": left >= right, "lt": left < right, "lte": left <= right,
        }.get(operator, False)
    left, right = str(source or "").casefold(), str(requested or "").strip().casefold()
    if not right:
        raise ValueError(f"{field} requires a value.")
    return (
        right in left if operator == "contains"
        else left == right if operator == "eq"
        else left != right if operator == "neq"
        else False
    )


def _validate_config(raw: Dict[str, Any]) -> Dict[str, Any]:
    config = dict(raw or {})
    def number(name: str, default: float) -> float:
        value = config.get(name)
        return default if value is None else float(value)

    lookback_days = max(1, min(3650, int(config.get("lookback_days") or 180)))
    min_hold = max(0, min(365, int(config.get("min_holding_days") or 5)))
    max_hold = max(min_hold or 1, min(730, int(config.get("max_holding_days") or 90)))
    filters = list(config.get("filters") or [])
    if len(filters) > 12:
        raise ValueError("A recommendation bot supports up to twelve filters.")
    max_stock_pct = float(config.get("max_stock_pct") or 10)
    if max_stock_pct < 5 or max_stock_pct > 100 or abs(max_stock_pct / 5 - round(max_stock_pct / 5)) > 1e-9:
        raise ValueError("Per-stock allocation must be between 5% and 100% in multiples of 5%.")
    exit_strategy = str(config.get("exit_strategy") or "strategy_exit")
    if exit_strategy not in {"strategy_exit", "hard_stop", "trailing_stop", "take_profit", "protective_ensemble", "auto_best"}:
        raise ValueError("Choose a supported sell strategy.")
    ranking_mode = str(config.get("ranking_mode") or "risk_adjusted_expectancy")
    if ranking_mode not in {"risk_adjusted_expectancy", "confidence"}:
        raise ValueError("Choose a supported top-pick ranking mode.")
    normalized = {
        "lookback_days": lookback_days,
        "initial_capital": max(1000.0, float(config.get("initial_capital") or 100000)),
        "minimum_win_rate": max(0.0, min(100.0, number("minimum_win_rate", 75))),
        "minimum_prior_trades": max(0, int(number("minimum_prior_trades", 25))),
        "minimum_confidence": max(0.0, min(100.0, number("minimum_confidence", 55))),
        "minimum_average_volume": max(0.0, number("minimum_average_volume", 10000)),
        "minimum_prior_expectancy_pct": max(-100.0, min(1000.0, number("minimum_prior_expectancy_pct", 3))),
        "minimum_prior_profit_factor": max(0.0, min(100.0, number("minimum_prior_profit_factor", 1.7))),
        "recent_trade_window": max(3, min(100, int(config.get("recent_trade_window") or 12))),
        "minimum_recent_win_rate": max(
            0.0, min(
                100.0,
                float(config["minimum_recent_win_rate"])
                if config.get("minimum_recent_win_rate") is not None else 60.0,
            ),
        ),
        "minimum_recent_expectancy_pct": max(
            -100.0, min(
                1000.0,
                float(config["minimum_recent_expectancy_pct"])
                if config.get("minimum_recent_expectancy_pct") is not None else 1.0,
            ),
        ),
        "min_holding_days": min_hold, "max_holding_days": max_hold,
        "max_positions": max(1, min(50, int(config.get("max_positions") or 5))),
        "max_stock_pct": max_stock_pct,
        "max_sector_pct": max(1.0, min(100.0, float(config.get("max_sector_pct") or 40))),
        "cash_reserve_pct": max(0.0, min(95.0, float(config.get("cash_reserve_pct") or 5))),
        "max_volume_participation_pct": max(
            0.01, min(25.0, float(config.get("max_volume_participation_pct") or 5)),
        ),
        "investor_type": str(config.get("investor_type") or "individual"),
        "exit_strategy": exit_strategy,
        "hard_stop_pct": max(0.1, min(50.0, float(config.get("hard_stop_pct") or 7))),
        "trailing_stop_pct": max(0.1, min(50.0, float(config.get("trailing_stop_pct") or 8))),
        "take_profit_pct": max(0.1, min(500.0, float(config.get("take_profit_pct") or 15))),
        "slippage_pct": max(0.0, min(10.0, float(config.get("slippage_pct") or 0.1))),
        "symbol_cooldown_days": max(0, min(365, int(number("symbol_cooldown_days", 20)))),
        "ranking_mode": ranking_mode,
        "filters": filters,
    }
    # Validate filters before running the large query.
    for rule in filters:
        field = str(rule.get("field") or "")
        operator = str(rule.get("operator") or "").lower()
        if field not in FILTER_FIELDS or operator not in FILTER_OPERATORS:
            raise ValueError(f"Unsupported recommendation bot filter: {field or 'missing field'} {operator}.")
        if FILTER_FIELDS[field] == "text" and operator not in {"eq", "neq", "contains"}:
            raise ValueError(f"{operator} is not valid for text field {field}.")
        if FILTER_FIELDS[field] == "number" and operator == "contains":
            raise ValueError(f"contains is not valid for numeric field {field}.")
        _matches_filter({}, rule)
    return normalized


def _apply_exit_strategy(
    candidates: List[Dict[str, Any]], quotes_by_symbol: Dict[str, List[Dict[str, Any]]],
    config: Dict[str, Any], end_date: date,
) -> List[Dict[str, Any]]:
    """Apply OHLC-confirmed exits after the configured minimum holding period.

    The hard stop is still a protective overlay, so it is checked even when the
    user selects the saved strategy sell signal. It does not bypass the minimum
    holding period. When daily OHLC is available, stops/targets use the
    session's intraday high/low instead of waiting for the close; true minute
    fills can be plugged in later if minute candles are persisted.
    """
    output: List[Dict[str, Any]] = []
    def quote_price(quote: Dict[str, Any], key: str) -> float:
        value = quote.get(key)
        return float(value if value is not None else quote["close_price"])

    for source in candidates:
        entry_date = _as_date(source["entry_date"])
        quotes = [quote for quote in quotes_by_symbol.get(source["symbol"], []) if _as_date(quote["session_date"]) >= entry_date]
        if not quotes:
            continue
        tradable = quotes[: max(1, config["max_holding_days"] + 1)]
        eligible = tradable[config["min_holding_days"]:]
        if not eligible:
            continue
        entry_price = float(source["entry_price"])
        original_exit = _as_date(source["exit_date"])
        strategy_quote = next((quote for quote in eligible if _as_date(quote["session_date"]) >= original_exit), None)
        # Remember highs reached while exits are locked by the minimum hold.
        # Resetting the peak after the lock would understate the drawdown.
        high_water = max(
            [entry_price, *(quote_price(quote, "high_price") for quote in tradable[:config["min_holding_days"]])]
        )
        selected = None
        for quote in eligible:
            open_price = quote_price(quote, "open_price")
            high_price = quote_price(quote, "high_price")
            low_price = quote_price(quote, "low_price")
            close = quote_price(quote, "close_price")
            high_water = max(high_water, high_price)
            hard_stop_price = entry_price * (1 - config["hard_stop_pct"] / 100)
            trailing_stop_price = high_water * (1 - config["trailing_stop_pct"] / 100)
            take_profit_price = entry_price * (1 + config["take_profit_pct"] / 100)
            triggered = []
            exit_prices = {}
            if low_price <= hard_stop_price:
                triggered.append("hard_stop")
                exit_prices["hard_stop"] = min(open_price, hard_stop_price) if open_price <= hard_stop_price else hard_stop_price
            if low_price <= trailing_stop_price:
                triggered.append("trailing_stop")
                exit_prices["trailing_stop"] = min(open_price, trailing_stop_price) if open_price <= trailing_stop_price else trailing_stop_price
            if high_price >= take_profit_price:
                triggered.append("take_profit")
                exit_prices["take_profit"] = max(open_price, take_profit_price) if open_price >= take_profit_price else take_profit_price
            if strategy_quote is quote:
                triggered.append("strategy_exit")
                exit_prices["strategy_exit"] = close
            if "hard_stop" in triggered:
                selected = (quote, "hard_stop", exit_prices["hard_stop"])
                break
            if config["exit_strategy"] in triggered:
                selected = (quote, config["exit_strategy"], exit_prices[config["exit_strategy"]])
                break
            if config["exit_strategy"] == "protective_ensemble" and triggered:
                selected = (quote, triggered[0], exit_prices[triggered[0]])
                break
        if selected is None:
            selected = (eligible[-1], "max_hold", quote_price(eligible[-1], "close_price"))
        quote, reason, raw_exit_price = selected
        item = dict(source)
        item["exit_date"] = _as_date(quote["session_date"])
        item["exit_price"] = float(raw_exit_price) * (1 - config["slippage_pct"] / 100)
        item["holding_days"] = max(0, tradable.index(quote))
        item["exit_reason"] = reason
        item["return_pct"] = round((item["exit_price"] / entry_price - 1) * 100, 4)
        output.append(item)
    return output


def _profile_matches(item: Dict[str, Any], profile: Dict[str, Any]) -> bool:
    """Keep profile filtering explicit so every walk-forward window uses frozen rules."""
    return (
        float(item["win_rate_pct"]) >= float(profile["minimum_win_rate"])
        and int(item["prior_trades"]) >= int(profile["minimum_prior_trades"])
        and float(item["confidence_floor_pct"]) >= float(profile["minimum_confidence"])
        and float(item["prior_expectancy_pct"]) >= float(profile["minimum_prior_expectancy_pct"])
        and float(item["prior_profit_factor"]) >= float(profile["minimum_prior_profit_factor"])
        and float(item["recent_win_rate_pct"]) >= float(profile.get("minimum_recent_win_rate", 0))
        and float(item["recent_expectancy_pct"]) >= float(
            profile.get("minimum_recent_expectancy_pct", -100)
        )
        and float(item["average_volume_20"]) >= float(profile.get("minimum_average_volume", 0))
    )


SHORT_TERM_PROFILES = (
    {"id": "balanced_breakout_30", "label": "30D Balanced breakout", "horizon_days": 30,
     "minimum_win_rate": 60, "minimum_prior_trades": 16, "minimum_confidence": 40,
     "minimum_prior_expectancy_pct": 1, "minimum_prior_profit_factor": 1.2,
     "minimum_recent_win_rate": 55, "minimum_recent_expectancy_pct": 0.5,
     "minimum_average_volume": 5000,
     "min_holding_days": 3, "max_holding_days": 20, "hard_stop_pct": 5,
     "trailing_stop_pct": 6, "take_profit_pct": 10, "exit_strategy": "protective_ensemble",
     "symbol_cooldown_days": 10},
    {"id": "high_confidence_30", "label": "30D High-confidence momentum", "horizon_days": 30,
     "minimum_win_rate": 70, "minimum_prior_trades": 16, "minimum_confidence": 50,
     "minimum_prior_expectancy_pct": 1.5, "minimum_prior_profit_factor": 1.4,
     "minimum_recent_win_rate": 60, "minimum_recent_expectancy_pct": 1,
     "minimum_average_volume": 10000,
     "min_holding_days": 5, "max_holding_days": 25, "hard_stop_pct": 6,
     "trailing_stop_pct": 7, "take_profit_pct": 12, "exit_strategy": "hard_stop",
     "symbol_cooldown_days": 15},
    {"id": "expectancy_30", "label": "30D High-expectancy top pick", "horizon_days": 30,
     "minimum_win_rate": 55, "minimum_prior_trades": 20, "minimum_confidence": 35,
     "minimum_prior_expectancy_pct": 2.5, "minimum_prior_profit_factor": 1.6,
     "minimum_recent_win_rate": 55, "minimum_recent_expectancy_pct": 1,
     "minimum_average_volume": 5000,
     "min_holding_days": 3, "max_holding_days": 20, "hard_stop_pct": 5,
     "trailing_stop_pct": 6, "take_profit_pct": 10, "exit_strategy": "take_profit",
     "symbol_cooldown_days": 15},
    {"id": "balanced_momentum_60", "label": "60D Balanced momentum", "horizon_days": 60,
     "minimum_win_rate": 60, "minimum_prior_trades": 16, "minimum_confidence": 40,
     "minimum_prior_expectancy_pct": 1, "minimum_prior_profit_factor": 1.25,
     "minimum_recent_win_rate": 55, "minimum_recent_expectancy_pct": 0.5,
     "minimum_average_volume": 5000,
     "min_holding_days": 5, "max_holding_days": 45, "hard_stop_pct": 7,
     "trailing_stop_pct": 8, "take_profit_pct": 15, "exit_strategy": "protective_ensemble",
     "symbol_cooldown_days": 20},
    {"id": "high_confidence_60", "label": "60D High-confidence momentum", "horizon_days": 60,
     "minimum_win_rate": 70, "minimum_prior_trades": 20, "minimum_confidence": 50,
     "minimum_prior_expectancy_pct": 1.5, "minimum_prior_profit_factor": 1.4,
     "minimum_recent_win_rate": 60, "minimum_recent_expectancy_pct": 1,
     "minimum_average_volume": 10000,
     "min_holding_days": 5, "max_holding_days": 50, "hard_stop_pct": 7,
     "trailing_stop_pct": 8, "take_profit_pct": 18, "exit_strategy": "hard_stop",
     "symbol_cooldown_days": 20},
    {"id": "expectancy_60", "label": "60D High-expectancy top pick", "horizon_days": 60,
     "minimum_win_rate": 55, "minimum_prior_trades": 25, "minimum_confidence": 35,
     "minimum_prior_expectancy_pct": 3, "minimum_prior_profit_factor": 1.7,
     "minimum_recent_win_rate": 60, "minimum_recent_expectancy_pct": 1,
     "minimum_average_volume": 10000,
     "min_holding_days": 5, "max_holding_days": 45, "hard_stop_pct": 6,
     "trailing_stop_pct": 7, "take_profit_pct": 15, "exit_strategy": "take_profit",
     "symbol_cooldown_days": 20},
)


def _short_term_analysis(
    candidates: List[Dict[str, Any]], quotes_by_symbol: Dict[str, List[Dict[str, Any]]],
    config: Dict[str, Any], allocation: Dict[str, Any], start_date: date, end_date: date,
) -> Dict[str, Any]:
    results = []
    for profile in SHORT_TERM_PROFILES:
        filtered = [item for item in candidates if _profile_matches(item, profile)]
        profile_config = {**config, **profile}
        adjusted = _apply_exit_strategy(filtered, quotes_by_symbol, profile_config, end_date)
        horizon = int(profile["horizon_days"])
        validation_start = end_date - timedelta(days=horizon)
        train_windows = []
        for offset in range(6, 0, -1):
            window_start = validation_start - timedelta(days=horizon * offset)
            window_end = window_start + timedelta(days=horizon)
            if window_start < start_date:
                continue
            window_trades = [
                item for item in adjusted
                if window_start <= _as_date(item["entry_date"]) < window_end
                and _as_date(item["exit_date"]) <= window_end
            ]
            summary, _ = replay_shared_capital(
                window_trades, config["initial_capital"],
                {**allocation, **profile, "max_positions": 1, "capture_executions": False},
            )
            completed = int(summary["accepted_signals"] or 0) - int(summary["open_positions_at_end"] or 0)
            train_windows.append({
                "start": window_start.isoformat(), "end": window_end.isoformat(),
                "net_return_pct": summary["net_return_pct"],
                "max_drawdown_pct": summary["max_drawdown_pct"],
                "completed_trades": completed, "winning_trades": int(summary["winning_trades"] or 0),
            })
        validation_trades = [
            item for item in adjusted
            if validation_start <= _as_date(item["entry_date"]) <= end_date
            and _as_date(item["exit_date"]) <= end_date
        ]
        validation, _ = replay_shared_capital(
            validation_trades, config["initial_capital"],
            {**allocation, **profile, "max_positions": 1, "capture_executions": False},
        )
        validation_count = int(validation["accepted_signals"] or 0) - int(validation["open_positions_at_end"] or 0)
        total_train_trades = sum(int(window["completed_trades"]) for window in train_windows)
        total_train_wins = sum(int(window["winning_trades"]) for window in train_windows)
        usable_windows = [window for window in train_windows if int(window["completed_trades"]) > 0]
        profitable_windows = sum(float(window["net_return_pct"]) > 0 for window in usable_windows)
        average_return = (
            sum(float(window["net_return_pct"]) for window in usable_windows) / len(usable_windows)
            if usable_windows else 0.0
        )
        result = {
            "profile": profile, "training_windows": train_windows,
            "training": {
                "windows": len(usable_windows), "profitable_windows": profitable_windows,
                "average_net_return_pct": round(average_return, 4),
                "completed_trades": total_train_trades,
                "win_rate_pct": round(100 * total_train_wins / max(1, total_train_trades), 2),
                "worst_drawdown_pct": max(
                    (float(window["max_drawdown_pct"]) for window in usable_windows), default=0,
                ),
            },
            "validation": {
                **validation, "start": validation_start.isoformat(),
                "completed_trades": validation_count,
                "win_rate_pct": round(
                    100 * int(validation["winning_trades"] or 0) / max(1, validation_count), 2,
                ),
            },
        }
        result["training_score"] = (
            profitable_windows / max(1, len(usable_windows)),
            average_return,
            -float(result["training"]["worst_drawdown_pct"]),
            total_train_trades,
        )
        results.append(result)
    ranked = sorted(results, key=lambda item: item["training_score"], reverse=True)
    winners = {}
    for horizon in (30, 60):
        matching = [item for item in ranked if int(item["profile"]["horizon_days"]) == horizon]
        qualified = [
            item for item in matching
            if int(item["training"]["windows"]) >= 3
            and int(item["training"]["completed_trades"]) >= 10
            and int(item["training"]["profitable_windows"]) >= math.ceil(
                int(item["training"]["windows"]) * 0.6
            )
        ]
        winner = qualified[0] if qualified else matching[0] if matching else None
        if not winner:
            continue
        validation = winner["validation"]
        training = winner["training"]
        winner["paper_ready"] = (
            int(training["windows"]) >= 3
            and int(training["completed_trades"]) >= 10
            and int(training["profitable_windows"]) >= math.ceil(int(training["windows"]) * 0.6)
            and int(validation["completed_trades"]) >= 3
            and float(validation["net_return_pct"]) > 0
            and float(validation["max_drawdown_pct"]) <= 5
        )
        winner["decision"] = "paper_candidate" if winner["paper_ready"] else "stay_in_cash"
        winner["decision_reason"] = (
            "Passed training consistency, minimum sample, positive untouched validation, and drawdown gates."
            if winner["paper_ready"]
            else "Failed at least one training-consistency, sample-size, validation-profit, or drawdown gate."
        )
        winners[str(horizon)] = winner
    return {
        "winners": winners,
        "profiles": [{key: value for key, value in item.items() if key != "training_score"} for item in ranked],
        "note": (
            "Profiles are ranked only on six earlier non-overlapping windows. The newest 30/60-day window is "
            "an untouched validation window and can veto paper activation."
        ),
    }


def replay_recommendation_bot(
    session, raw_config: Dict[str, Any], *, owner_id: str,
) -> Dict[str, Any]:
    config = _validate_config(raw_config)
    latest = session.execute(text("""
        SELECT MAX(session_date) FROM market_ohlcv_daily
        WHERE adjusted=TRUE AND session_date<=CURRENT_DATE
    """)).scalar()
    if not latest:
        raise ValueError("No completed market session is available.")
    end_date = min(
        _as_date(raw_config.get("end_date")) if raw_config.get("end_date") else latest,
        latest,
    )
    start_date = (
        _as_date(raw_config["start_date"])
        if raw_config.get("start_date")
        else end_date - timedelta(days=config["lookback_days"])
    )
    if start_date >= end_date:
        raise ValueError("The simulation start date must be before the end date.")
    config = {**config, "start_date": start_date.isoformat(), "end_date": end_date.isoformat()}

    rows = session.execute(text("""
        SELECT t.trade_id,t.result_id,t.sequence_no,t.signal_date,t.entry_date,t.entry_price,
               t.exit_date,t.exit_price,t.holding_days,t.exit_reason,t.return_pct,
               r.run_id,r.symbol,r.preset_id,r.preset_name,
               COALESCE(s.sector,'Unknown') AS sector,
               COALESCE(volume.average_volume_20,0) AS average_volume_20
        FROM backtest_canonical_results canonical
        JOIN backtest_results r ON r.result_id=canonical.result_id
        JOIN backtest_runs run ON run.run_id=r.run_id
        JOIN backtest_trades t ON t.result_id=r.result_id
        JOIN backtest_run_symbols s ON s.run_id=r.run_id AND s.symbol=r.symbol
        LEFT JOIN LATERAL (
            SELECT AVG(d.volume)::DOUBLE PRECISION AS average_volume_20
            FROM (
                SELECT volume FROM market_ohlcv_daily
                WHERE symbol=r.symbol AND adjusted=TRUE
                  AND session_date<COALESCE(t.signal_date,t.entry_date)
                ORDER BY session_date DESC LIMIT 20
            ) d
        ) volume ON TRUE
        WHERE canonical.owner_id=:owner_id AND run.deleted_at IS NULL
          AND run.archived_at IS NULL AND run.run_type<>'ipo_research'
          AND t.entry_date<=:end_date
        ORDER BY COALESCE(t.signal_date,t.entry_date),t.entry_date,r.symbol,r.result_id,t.sequence_no
    """), {"owner_id": owner_id, "end_date": end_date}).mappings().all()

    by_result: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    all_trades = [dict(row) for row in rows]
    for trade in all_trades:
        by_result[int(trade["result_id"])].append(trade)
    completed: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    accepted: List[Dict[str, Any]] = []
    rejection_counts: Dict[str, int] = defaultdict(int)
    for source in all_trades:
        signal_date = _as_date(source.get("signal_date") or source["entry_date"])
        if not (start_date <= signal_date <= end_date):
            continue
        if _as_date(source["exit_date"]) > end_date:
            rejection_counts["open_at_window_end"] += 1
            continue
        result_id = int(source["result_id"])
        prior = [
            trade for trade in by_result[result_id]
            if _as_date(trade["exit_date"]) < signal_date
        ]
        wins = sum(float(trade.get("return_pct") or 0) > 0 for trade in prior)
        prior_count = len(prior)
        win_rate = 100 * wins / prior_count if prior_count else 0.0
        confidence = _wilson_floor(wins, prior_count)
        positive_returns = sum(max(0.0, float(trade.get("return_pct") or 0)) for trade in prior)
        negative_returns = -sum(min(0.0, float(trade.get("return_pct") or 0)) for trade in prior)
        profit_factor = positive_returns / negative_returns if negative_returns else (10.0 if positive_returns else 0.0)
        expectancy = sum(float(trade.get("return_pct") or 0) for trade in prior) / prior_count if prior_count else 0.0
        # A long historical record can hide a strategy that has stopped working.
        # This is still causal: it uses only the latest completed exits available
        # before the candidate's signal.
        recent_prior = prior[-config["recent_trade_window"]:]
        recent_count = len(recent_prior)
        recent_wins = sum(float(trade.get("return_pct") or 0) > 0 for trade in recent_prior)
        recent_win_rate = 100 * recent_wins / recent_count if recent_count else 0.0
        recent_expectancy = (
            sum(float(trade.get("return_pct") or 0) for trade in recent_prior) / recent_count
            if recent_count else 0.0
        )
        candidate = {
            **source, "strategy": source["preset_name"],
            "prior_trades": prior_count, "win_rate_pct": round(win_rate, 2),
            "confidence_floor_pct": round(confidence, 2),
            "prior_expectancy_pct": round(expectancy, 4),
            "prior_profit_factor": round(min(10.0, profit_factor), 4),
            "recent_trades": recent_count, "recent_win_rate_pct": round(recent_win_rate, 2),
            "recent_expectancy_pct": round(recent_expectancy, 4),
            "entry_price": float(source["entry_price"]),
            "latest_volume": float(source.get("average_volume_20") or 0),
        }
        if win_rate < config["minimum_win_rate"]:
            rejection_counts["win_rate"] += 1
            continue
        if prior_count < config["minimum_prior_trades"]:
            rejection_counts["prior_trades"] += 1
            continue
        if confidence < config["minimum_confidence"]:
            rejection_counts["confidence"] += 1
            continue
        if float(candidate["average_volume_20"] or 0) < config["minimum_average_volume"]:
            rejection_counts["volume"] += 1
            continue
        if float(candidate["prior_expectancy_pct"]) < config["minimum_prior_expectancy_pct"]:
            rejection_counts["expectancy"] += 1
            continue
        if float(candidate["prior_profit_factor"]) < config["minimum_prior_profit_factor"]:
            rejection_counts["profit_factor"] += 1
            continue
        if recent_win_rate < config["minimum_recent_win_rate"]:
            rejection_counts["recent_win_rate"] += 1
            continue
        if recent_expectancy < config["minimum_recent_expectancy_pct"]:
            rejection_counts["recent_expectancy"] += 1
            continue
        if any(not _matches_filter(candidate, rule) for rule in config["filters"]):
            rejection_counts["advanced_filter"] += 1
            continue
        accepted.append(candidate)

    allocation = {
        **config, "charge_model": "nepse_equity", "apply_cgt": True,
        "dp_charge": 25, "fee_pct": .4, "fixed_fee": 0,
        "allocation_basis": "current_equity", "quantity_lot_size": 10,
        "capture_executions": True, "symbol_cooldown_days": config["symbol_cooldown_days"],
    }
    # Select one top pick per entry session using only data known at that signal.
    if config["ranking_mode"] == "risk_adjusted_expectancy":
        accepted.sort(key=lambda item: (
            item["entry_date"],
            -(0.6 * float(item["recent_expectancy_pct"]) + 0.4 * float(item["prior_expectancy_pct"])),
            -float(item["recent_win_rate_pct"]),
            -float(item["prior_profit_factor"]), -float(item["confidence_floor_pct"]),
            -int(item["prior_trades"]), item["symbol"],
        ))
    else:
        accepted.sort(key=lambda item: (
            item["entry_date"], -float(item["confidence_floor_pct"]),
            -float(item["win_rate_pct"]), -int(item["prior_trades"]), item["symbol"],
        ))
    unique_candidates = []
    seen_stock_entries = set()
    for item in accepted:
        identity = (item["symbol"], _as_date(item["entry_date"]))
        if identity in seen_stock_entries:
            rejection_counts["duplicate_stock_entry"] += 1
            continue
        seen_stock_entries.add(identity)
        unique_candidates.append(item)
    accepted = unique_candidates
    candidate_pool = list(accepted)
    exit_comparison: Dict[str, Dict[str, Any]] = {}
    paper_candidate = None
    short_term_analysis = None
    multi_trade_analysis = None
    simulations: Dict[str, List[Dict[str, Any]]] = {}
    selected_exit_strategy = config["exit_strategy"]
    if accepted:
        quote_query = text("""
            SELECT symbol,session_date,open_price,high_price,low_price,close_price
            FROM market_ohlcv_daily
            WHERE adjusted=TRUE AND symbol IN :symbols
              AND session_date BETWEEN :start_date AND :end_date
            ORDER BY symbol,session_date
        """).bindparams(bindparam("symbols", expanding=True))
        quote_rows = session.execute(quote_query, {
            "symbols": sorted({str(item["symbol"]) for item in accepted}),
            "start_date": min(_as_date(item["entry_date"]) for item in accepted),
            "end_date": end_date,
        }).mappings().all()
        quotes_by_symbol: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for quote in quote_rows:
            quotes_by_symbol[str(quote["symbol"])].append(dict(quote))
        alternatives = ("strategy_exit", "hard_stop", "trailing_stop", "take_profit", "protective_ensemble")
        rules_needed = (
            alternatives
            if (
                config["exit_strategy"] == "auto_best"
                or raw_config.get("analyze_accuracy")
                or raw_config.get("analyze_portfolio")
            )
            else (config["exit_strategy"],)
        )
        simulations = {
            rule: _apply_exit_strategy(
                candidate_pool, quotes_by_symbol, {**config, "exit_strategy": rule}, end_date,
            )
            for rule in rules_needed
        }
        if raw_config.get("analyze_short_term"):
            short_term_analysis = _short_term_analysis(
                candidate_pool, quotes_by_symbol, config, allocation, start_date, end_date,
            )
        if config["exit_strategy"] == "auto_best":
            exit_training_end = start_date + timedelta(
                days=max(1, int((end_date - start_date).days * 0.7))
            )
            for rule in alternatives:
                simulated = simulations[rule]
                trial_summary, _ = replay_shared_capital(
                    [
                        item for item in simulated
                        if _as_date(item["entry_date"]) <= exit_training_end
                        and _as_date(item["exit_date"]) <= exit_training_end
                    ],
                    config["initial_capital"],
                    {**allocation, "capture_executions": False},
                )
                exit_comparison[rule] = {
                    "net_return_pct": trial_summary["net_return_pct"],
                    "max_drawdown_pct": trial_summary["max_drawdown_pct"],
                    "completed_trades": _completed_trade_count(trial_summary),
                }
            selected_exit_strategy = max(
                alternatives,
                key=lambda rule: (exit_comparison[rule]["net_return_pct"], -exit_comparison[rule]["max_drawdown_pct"]),
            )
            accepted = simulations[selected_exit_strategy]
        else:
            accepted = simulations[selected_exit_strategy]

        if raw_config.get("analyze_accuracy"):
            split_date = start_date + timedelta(days=max(1, int((end_date - start_date).days * 0.7)))
            win_thresholds = sorted({
                config["minimum_win_rate"], 60.0, 65.0, 70.0,
            })
            trade_thresholds = sorted({
                config["minimum_prior_trades"], 9, 16, 25,
            })
            confidence_thresholds = sorted({
                config["minimum_confidence"], 35.0, 45.0, 55.0,
            })
            best = None
            for rule, simulated in simulations.items():
                for win_threshold in win_thresholds:
                    for trade_threshold in trade_thresholds:
                        for confidence_threshold in confidence_thresholds:
                            train = [
                                item for item in simulated
                                if _as_date(item["entry_date"]) <= split_date
                                and float(item["win_rate_pct"]) >= win_threshold
                                and int(item["prior_trades"]) >= trade_threshold
                                and float(item["confidence_floor_pct"]) >= confidence_threshold
                            ]
                            trial, _ = replay_shared_capital(
                                train, config["initial_capital"],
                                {**allocation, "capture_executions": False},
                            )
                            completed_count = int(trial["accepted_signals"] or 0) - int(
                                trial["open_positions_at_end"] or 0
                            )
                            if completed_count < 10:
                                continue
                            actual_floor = _wilson_floor(int(trial["winning_trades"] or 0), completed_count)
                            score = (
                                trial["net_return_pct"] > 0,
                                actual_floor,
                                trial["net_return_pct"],
                                -trial["max_drawdown_pct"],
                                completed_count,
                            )
                            if best is None or score > best["score"]:
                                best = {
                                    "score": score, "rule": rule,
                                    "minimum_win_rate": win_threshold,
                                    "minimum_prior_trades": trade_threshold,
                                    "minimum_confidence": confidence_threshold,
                                    "training": {
                                        **trial, "completed_trades": completed_count,
                                        "win_rate_pct": round(
                                            100 * int(trial["winning_trades"] or 0) / completed_count, 2,
                                        ),
                                        "win_rate_floor_pct": round(actual_floor, 2),
                                    },
                                }
            if best:
                validation = [
                    item for item in simulations[best["rule"]]
                    if _as_date(item["entry_date"]) > split_date
                    and float(item["win_rate_pct"]) >= best["minimum_win_rate"]
                    and int(item["prior_trades"]) >= best["minimum_prior_trades"]
                    and float(item["confidence_floor_pct"]) >= best["minimum_confidence"]
                ]
                validation_summary, _ = replay_shared_capital(
                    validation, config["initial_capital"],
                    {**allocation, "capture_executions": False},
                )
                validation_count = int(validation_summary["accepted_signals"] or 0) - int(
                    validation_summary["open_positions_at_end"] or 0
                )
                validation_wins = int(validation_summary["winning_trades"] or 0)
                paper_candidate = {
                    "training_end": split_date.isoformat(),
                    "validation_start": (split_date + timedelta(days=1)).isoformat(),
                    "suggested_config": {
                        "minimum_win_rate": best["minimum_win_rate"],
                        "minimum_prior_trades": best["minimum_prior_trades"],
                        "minimum_confidence": best["minimum_confidence"],
                        "exit_strategy": best["rule"],
                    },
                    "training": best["training"],
                    "validation": {
                        **validation_summary, "completed_trades": validation_count,
                        "win_rate_pct": round(100 * validation_wins / max(1, validation_count), 2),
                        "win_rate_floor_pct": round(_wilson_floor(validation_wins, validation_count), 2),
                    },
                    "paper_ready": (
                        validation_count >= 5
                        and validation_summary["net_return_pct"] > 0
                        and _wilson_floor(validation_wins, validation_count) >= 40
                    ),
                    "note": (
                        "Thresholds and exit were selected on the first 70% of the period, then checked on the "
                        "untouched final 30%. Paper-ready never means future profit is guaranteed."
                    ),
                }
    # The database does not yet contain versioned official NEPSE-index closes.
    # Use a causal equal-weight listed-share proxy and label it explicitly rather
    # than presenting it as the official capitalization-weighted NEPSE index.
    proxy_rows = session.execute(text("""
        WITH prices AS (
            SELECT symbol,session_date,close_price,
                   LAG(close_price) OVER (PARTITION BY symbol ORDER BY session_date) AS prior_close
            FROM market_ohlcv_daily
            WHERE adjusted=TRUE
              AND session_date BETWEEN CAST(:start_date AS date) - INTERVAL '7 days' AND :end_date
        ), daily AS (
            SELECT session_date,AVG(close_price/NULLIF(prior_close,0)-1) AS daily_return
            FROM prices
            WHERE prior_close IS NOT NULL AND session_date BETWEEN :start_date AND :end_date
            GROUP BY session_date ORDER BY session_date
        ) SELECT session_date,daily_return FROM daily
    """), {"start_date": start_date, "end_date": end_date}).mappings().all()
    if raw_config.get("analyze_portfolio") and simulations:
        multi_trade_analysis = _optimize_multi_trade_portfolio(
            simulations, config, allocation, proxy_rows, start_date, end_date,
        )
    summary, curve = replay_shared_capital(accepted, config["initial_capital"], allocation)
    executions = list(summary.pop("executions", []))
    summary["completed_trades"] = len(executions)
    summary["win_rate_pct"] = round(
        100 * int(summary.get("winning_trades") or 0) / max(1, int(summary["completed_trades"])), 2,
    )
    deployed_capital = sum(float(item.get("entry_total") or 0) for item in executions)
    summary["gross_pnl_before_charges"] = round(
        float(summary["realized_pnl"]) + float(summary["total_charges"]), 2,
    )
    summary["capital_turnover_pct"] = round(
        100 * deployed_capital / config["initial_capital"], 2,
    )
    summary["return_on_deployed_capital_pct"] = round(
        100 * float(summary["realized_pnl"]) / deployed_capital, 4,
    ) if deployed_capital else 0.0
    completed_count = int(summary["completed_trades"])
    realized_floor = _wilson_floor(int(summary.get("winning_trades") or 0), completed_count)
    gate_reasons = []
    if completed_count < 10:
        gate_reasons.append(f"Only {completed_count} completed trades; at least 10 are required.")
    if float(summary["net_return_pct"]) <= 0:
        gate_reasons.append("The tested portfolio return is not positive after charges.")
    if realized_floor < 40:
        gate_reasons.append(f"The realized 95% win-rate floor is only {realized_floor:.2f}%.")
    validated_accuracy = bool(paper_candidate and paper_candidate.get("paper_ready"))
    validated_multi = bool(multi_trade_analysis and multi_trade_analysis.get("paper_ready"))
    validated = validated_accuracy or validated_multi
    gate_completed_count = completed_count
    gate_floor = realized_floor
    if validated_multi:
        gate_completed_count = int(multi_trade_analysis["validation"]["completed_trades"])
        gate_floor = float(multi_trade_analysis["validation"]["win_rate_floor_pct"])
    deployment_gate = {
        "decision": "paper_candidate" if validated else "stay_in_cash",
        "paper_ready": validated,
        "completed_trades": gate_completed_count,
        "realized_win_rate_floor_pct": round(gate_floor, 2),
        "reasons": (
            [
                "Passed the untouched diversified portfolio validation gate."
                if validated_multi
                else "Passed the untouched walk-forward validation gate."
            ]
            if validated
            else gate_reasons or [
                "This is an in-sample historical result. Run the accuracy analysis before paper activation."
            ]
        ),
    }
    executed_prior_rates = [float(item["win_rate_pct"]) for item in executions]
    executed_prior_counts = [int(item["prior_trades"]) for item in executions]
    executed_recent_rates = [float(item["recent_win_rate_pct"]) for item in executions]
    eligibility_audit = {
        "minimum_prior_win_rate_pct": config["minimum_win_rate"],
        "minimum_prior_trades": config["minimum_prior_trades"],
        "minimum_prior_confidence_floor_pct": config["minimum_confidence"],
        "minimum_recent_win_rate_pct": config["minimum_recent_win_rate"],
        "executed_minimum_prior_win_rate_pct": (
            round(min(executed_prior_rates), 2) if executed_prior_rates else None
        ),
        "executed_minimum_prior_trades": min(executed_prior_counts) if executed_prior_counts else None,
        "executed_minimum_recent_win_rate_pct": (
            round(min(executed_recent_rates), 2) if executed_recent_rates else None
        ),
        "executed_orders": len(executions),
        "all_executed_orders_passed": all(
            float(item["win_rate_pct"]) >= config["minimum_win_rate"]
            and int(item["prior_trades"]) >= config["minimum_prior_trades"]
            and float(item["confidence_floor_pct"]) >= config["minimum_confidence"]
            and float(item["recent_win_rate_pct"]) >= config["minimum_recent_win_rate"]
            for item in executions
        ),
        "small_sample_orders": sum(int(item["prior_trades"]) < 9 for item in executions),
        "basis": (
            "Eligibility uses only that strategy's trades completed before each signal and its saved strategy "
            "exit. The realized bot win rate measures the subsequent funded orders using the selected bot exit."
        ),
    }
    benchmark_value = 100.0
    benchmark_curve = []
    for row in proxy_rows:
        benchmark_value *= 1 + float(row["daily_return"] or 0)
        benchmark_curve.append({"date": row["session_date"].isoformat(), "value": round(benchmark_value, 4)})
    benchmark_return_pct = round(benchmark_value - 100, 4) if benchmark_curve else None
    return {
        "config": config, "start_date": start_date.isoformat(), "end_date": end_date.isoformat(),
        "summary": summary, "equity_curve": curve,
        "paper_candidate": paper_candidate,
        "short_term_analysis": short_term_analysis,
        "multi_trade_analysis": multi_trade_analysis,
        "deployment_gate": deployment_gate,
        "eligibility_audit": eligibility_audit,
        "exit_selection": {
            "requested": config["exit_strategy"], "selected": selected_exit_strategy,
            "comparison": exit_comparison,
            "note": (
                "Auto-select ranks exits on the first 70% of this history. The displayed full-period result "
                "is descriptive; use the multi-trade analysis for an untouched portfolio validation."
                if config["exit_strategy"] == "auto_best"
                else "This sell rule was selected directly; no cross-exit optimization was performed."
            ),
        },
        "benchmark": {
            "name": "NEPSE listed-share equal-weight proxy",
            "return_pct": benchmark_return_pct, "curve": benchmark_curve,
            "disclaimer": "Official capitalization-weighted NEPSE index history is not stored locally; this is an equal-weight proxy from available adjusted listed-share closes.",
        },
        "trades": [{
            "symbol": item["symbol"], "strategy": item["preset_name"],
            "signal_date": str(item.get("signal_date") or item["entry_date"]),
            "entry_date": str(item["entry_date"]), "entry_price": float(item["entry_price"]),
            "exit_date": str(item["exit_date"]), "exit_price": float(item["exit_price"]),
            "holding_days": int(item.get("holding_days") or 0),
            "exit_reason": item.get("exit_reason"),
            "net_return_pct": float(item.get("net_return_pct") or 0),
            "net_pnl": float(item.get("net_pnl") or 0),
            "quantity": int(item.get("quantity") or 0),
            "total_charges": float(item.get("total_charges") or 0),
            "prior_trades": item["prior_trades"], "prior_win_rate_pct": item["win_rate_pct"],
            "confidence_floor_pct": item["confidence_floor_pct"],
            "prior_expectancy_pct": float(item.get("prior_expectancy_pct") or 0),
            "prior_profit_factor": float(item.get("prior_profit_factor") or 0),
            "recent_trades": int(item.get("recent_trades") or 0),
            "recent_win_rate_pct": float(item.get("recent_win_rate_pct") or 0),
            "recent_expectancy_pct": float(item.get("recent_expectancy_pct") or 0),
            "average_volume_20": float(item.get("average_volume_20") or 0),
        } for item in executions[:1000]],
        "candidate_signals": len(accepted), "rejection_counts": dict(rejection_counts),
        "methodology": (
            "Causal replay: win rate and 95% confidence floor use only trades completed before each signal. "
            "Shared capital, position/sector limits, historical brokerage slabs, SEBON fees, DP charges, "
            "CGT and sell-side slippage assumptions are applied. The displayed rows are orders actually executed "
            "by the shared-capital replay. Results are research evidence, not guaranteed returns."
        ),
    }


def filter_catalog() -> List[Dict[str, str]]:
    return [
        {"field": field, "type": field_type, "label": field.replace("_", " ").title()}
        for field, field_type in FILTER_FIELDS.items()
    ]
