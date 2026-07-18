from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from sqlalchemy import text

from utils.backtesting.nepse_charges import (
    DEFAULT_DP_CHARGE,
    NEPSE_EQUITY_CHARGE_MODEL,
    buy_charges,
    maximum_affordable_quantity,
    normalize_charge_model,
    sell_charges,
)
from utils.strategy_builder.history_service import TargetHistory
from utils.strategy_builder.rule_evaluator import evaluate_rule, update_history_from_snapshot
from utils.strategy_builder.strategy_parser import StrategyQueryError, parse_strategy_query
from utils.technical_indicators import INDICATOR_FIELDS, calculate_indicator_rows


CHART_URL = "https://merolagani.com/handlers/TechnicalChartHandler.ashx"
NEPAL_TZ = ZoneInfo("Asia/Kathmandu")
SYMBOL_RE = re.compile(r"^[A-Z0-9./-]{1,30}$")
HISTORICAL_FIELDS = {
    "symbol", "ltp", "open", "high", "low", "volume", "previous_close", "change",
    "change_percent", "last_traded_at", "received_at", "intraday_range",
    "intraday_range_percent", "distance_from_open", "distance_from_open_percent",
    "distance_from_day_high", "distance_from_day_high_percent", "distance_from_day_low",
    "distance_from_day_low_percent", "position_in_52_week_range_percent",
    "distance_from_52_week_high", "distance_from_52_week_high_percent",
    "distance_from_52_week_low", "distance_from_52_week_low_percent",
    "technical_rsi_14", "technical_macd", "technical_sma_10", "technical_sma_20",
    "technical_sma_50", "technical_sma_200", "technical_volume_trend",
} | set(INDICATOR_FIELDS)
HISTORICAL_FUNCTIONS = {
    "PREVIOUS", "CHANGE", "CHANGE_PERCENT", "CONSECUTIVE_DROPS", "CONSECUTIVE_RISES",
    "CROSSES_ABOVE", "CROSSES_BELOW", "REMAINS_ABOVE", "REMAINS_BELOW",
    "TRUE_FOR_SCANS", "MATCHES_IN_LAST", "AVERAGE", "MIN_VALUE", "MAX_VALUE",
    "SUM_VALUE", "STDDEV", "SLOPE", "TREND",
}


class BacktestError(ValueError):
    pass


@dataclass(frozen=True)
class Bar:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    extras: Dict[str, Any] = field(default_factory=dict)

    @property
    def day(self) -> str:
        return datetime.fromtimestamp(self.timestamp, NEPAL_TZ).date().isoformat()


def _epoch_start(value: date) -> int:
    return int(datetime(value.year, value.month, value.day, tzinfo=timezone.utc).timestamp())


def fetch_historical_bars(symbol: str, start_date: date, end_date: date) -> List[Bar]:
    clean_symbol = str(symbol or "").strip().upper()
    if not SYMBOL_RE.fullmatch(clean_symbol):
        raise BacktestError("Enter a valid uppercase NEPSE symbol.")
    if start_date >= end_date:
        raise BacktestError("Start date must be before end date.")
    if (end_date - start_date).days > 7305:
        raise BacktestError("Backtests are limited to 20 years.")

    from utils.backtesting.cache import cached_history
    try:
        cached = cached_history(clean_symbol, start_date, end_date)
    except Exception:
        cached = None
    if cached is not None:
        result = [Bar(
            timestamp=int(item["source_timestamp"] or datetime(
                item["session_date"].year, item["session_date"].month,
                item["session_date"].day, 15, 0, tzinfo=NEPAL_TZ,
            ).timestamp()),
            open=float(item["open_price"]), high=float(item["high_price"]),
            low=float(item["low_price"]), close=float(item["close_price"]),
            volume=float(item["volume"] or 0),
            extras={"quality_flags": item.get("quality_flags") or [], "cached": True},
        ) for item in cached]
        if len(result) >= 2:
            return result

    bars: Dict[int, Bar] = {}
    # The chart handler accepts the complete supported date range. Fetching it
    # once per symbol is important for a 60-preset, whole-market scan.
    for attempt in range(2):
        params = urlencode({
            "type": "get_advanced_chart",
            "symbol": clean_symbol,
            "resolution": "1D",
            "rangeStartDate": _epoch_start(start_date),
            "rangeEndDate": _epoch_start(end_date + timedelta(days=1)) - 1,
            "from": "",
            "isAdjust": 1,
            "currencyCode": "NPR",
        })
        request = Request(
            f"{CHART_URL}?{params}",
            headers={
                "Accept": "application/json",
                "Referer": f"https://merolagani.com/CompanyDetail.aspx?symbol={clean_symbol}",
                "User-Agent": "TMS-Automation-Backtester/1.0",
            },
        )
        try:
            with urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            if attempt == 0:
                continue
            from utils.backtesting.cache import store_cache_failure
            try:
                store_cache_failure(clean_symbol, start_date, end_date, str(exc))
            except Exception:
                pass
            raise BacktestError("Historical market data is temporarily unavailable.") from exc
        if not isinstance(payload, dict):
            raise BacktestError("Historical chart data returned an invalid response.")
        if payload.get("s") != "ok":
            break
        columns = [payload.get(key) or [] for key in ("t", "o", "h", "l", "c", "v")]
        if len({len(column) for column in columns}) != 1:
            raise BacktestError("Historical chart data contains misaligned OHLCV columns.")
        for values in zip(*columns):
            try:
                bar = Bar(int(values[0]), *(float(value) for value in values[1:]))
            except (TypeError, ValueError):
                continue
            bar_date = datetime.fromtimestamp(bar.timestamp, NEPAL_TZ).date()
            if start_date <= bar_date <= end_date and min(bar.open, bar.high, bar.low, bar.close) > 0:
                bars[bar.timestamp] = bar
        break

    result = sorted(bars.values(), key=lambda item: item.timestamp)
    if len(result) < 2:
        from utils.backtesting.cache import store_cache_failure
        try:
            store_cache_failure(clean_symbol, start_date, end_date, "Not enough historical data was returned.")
        except Exception:
            pass
        raise BacktestError(f"Not enough historical data was returned for {clean_symbol}.")
    from utils.backtesting.cache import store_history
    try:
        store_history(clean_symbol, result, start_date, end_date)
    except Exception:
        pass
    return result


def fetch_combined_snapshot_bars(symbol: str, start_date: date, end_date: date) -> List[Bar]:
    """Load point-in-time combined-market snapshots without using today's cache for old dates."""
    from database import SessionLocal

    clean_symbol = str(symbol or "").strip().upper()
    if not SYMBOL_RE.fullmatch(clean_symbol):
        raise BacktestError("Enter a valid uppercase NEPSE symbol.")
    session = SessionLocal()
    try:
        try:
            rows = session.execute(
                text(
                    """
                    SELECT snapshot_date, data
                    FROM merolagani_daily_stocks
                    WHERE symbol = :symbol
                      AND snapshot_date BETWEEN :start_date AND :end_date
                    ORDER BY snapshot_date ASC
                    """
                ),
                {"symbol": clean_symbol, "start_date": start_date, "end_date": end_date},
            ).mappings().all()
        except Exception as exc:
            raise BacktestError("The combined snapshot database is temporarily unavailable.") from exc
    finally:
        session.close()

    bars: List[Bar] = []
    for item in rows:
        payload = item.get("data") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                continue
        if not isinstance(payload, dict):
            continue

        def numeric(*keys: str) -> Optional[float]:
            for key in keys:
                value = payload.get(key)
                if isinstance(value, bool) or value is None:
                    continue
                try:
                    return float(str(value).replace(",", ""))
                except ValueError:
                    continue
            return None

        close = numeric("ltp", "ml_ltp", "close")
        open_price = numeric("open", "ml_open") or close
        raw_high = numeric("high", "ml_high") or close
        raw_low = numeric("low", "ml_low") or close
        if not close or not open_price or not raw_high or not raw_low:
            continue
        # Some upstream rows have swapped/partial OHLC fields. Enforce a valid bar
        # while preserving the point-in-time close used by the combined table.
        high = max(open_price, raw_high, raw_low, close)
        low = min(open_price, raw_high, raw_low, close)
        snapshot_date = item["snapshot_date"]
        timestamp = int(datetime(
            snapshot_date.year, snapshot_date.month, snapshot_date.day, 15, 0, tzinfo=NEPAL_TZ
        ).timestamp())
        bars.append(Bar(
            timestamp=timestamp,
            open=open_price,
            high=high,
            low=low,
            close=close,
            volume=numeric("qty", "volume", "ml_quantity") or 0.0,
            extras=dict(payload),
        ))
    if len(bars) < 2:
        raise BacktestError(
            f"Not enough combined daily snapshots are stored for {clean_symbol} in this period. "
            "Choose Auto/MeroLagani for a longer price history."
        )
    return bars


def _ema(values: List[float], period: int) -> List[Optional[float]]:
    output: List[Optional[float]] = []
    current: Optional[float] = None
    multiplier = 2 / (period + 1)
    for value in values:
        current = value if current is None else (value - current) * multiplier + current
        output.append(current)
    return output


def _rsi(values: List[float], period: int = 14) -> List[Optional[float]]:
    output: List[Optional[float]] = [None] * len(values)
    gains: List[float] = []
    losses: List[float] = []
    for index in range(1, len(values)):
        delta = values[index] - values[index - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
        if index < period:
            continue
        window_gains = gains[index - period:index]
        window_losses = losses[index - period:index]
        avg_gain = sum(window_gains) / period
        avg_loss = sum(window_losses) / period
        output[index] = 100.0 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss))
    return output


def _sma(values: List[float], index: int, period: int) -> Optional[float]:
    if index + 1 < period:
        return None
    window = values[index + 1 - period:index + 1]
    return sum(window) / period


def _collect_requirements(node: Any, fields: set[str], functions: set[str]) -> None:
    if hasattr(node, "model_dump"):
        node = node.model_dump(mode="python")
    if isinstance(node, dict):
        if node.get("type") == "field":
            fields.add(str(node.get("name") or ""))
        if node.get("type") == "function":
            functions.add(str(node.get("name") or "").upper())
            field_arg = (node.get("arguments") or {}).get("field")
            if isinstance(field_arg, str):
                fields.add(field_arg)
        for value in node.values():
            _collect_requirements(value, fields, functions)
    elif isinstance(node, (list, tuple)):
        for value in node:
            _collect_requirements(value, fields, functions)


def _validate_historical_plan(
    plan: Any, symbol: str, *, available_fields: Optional[set[str]] = None,
) -> List[Any]:
    rules = [rule for rule in plan.rules if symbol in {item.upper() for item in rule.symbols}]
    if not rules:
        raise BacktestError(f'The query does not contain a rule for symbol "{symbol}".')
    fields: set[str] = set()
    functions: set[str] = set()
    for rule in rules:
        if rule.use_strategy:
            raise BacktestError("Named live strategies are not backtestable yet; use explicit WHEN conditions.")
        _collect_requirements(rule, fields, functions)
    allowed_fields = HISTORICAL_FIELDS | (available_fields or set())
    unsupported_fields = sorted(field for field in fields if field and field not in allowed_fields)
    unsupported_functions = sorted(name for name in functions if name and name not in HISTORICAL_FUNCTIONS)
    if unsupported_fields or unsupported_functions:
        details = []
        if unsupported_fields:
            details.append("fields: " + ", ".join(unsupported_fields))
        if unsupported_functions:
            details.append("functions: " + ", ".join(unsupported_functions))
        raise BacktestError("This query needs live-only data (" + "; ".join(details) + ").")
    return rules


def _historical_rows(symbol: str, bars: List[Bar]) -> Iterable[Dict[str, Any]]:
    closes = [bar.close for bar in bars]
    indicator_rows = calculate_indicator_rows(bars)
    rolling_highs: List[float] = []
    rolling_lows: List[float] = []
    for index, bar in enumerate(bars):
        previous_close = closes[index - 1] if index else bar.open
        change = bar.close - previous_close
        range_value = bar.high - bar.low
        window_52 = bars[max(0, index - 251):index + 1]
        high_52 = max(item.high for item in window_52)
        low_52 = min(item.low for item in window_52)
        rolling_highs.append(high_52)
        rolling_lows.append(low_52)
        range_52 = high_52 - low_52
        row: Dict[str, Any] = {
            "symbol": symbol, "ltp": bar.close, "open": bar.open, "high": bar.high,
            "low": bar.low, "volume": bar.volume, "previous_close": previous_close,
            "change": change, "change_percent": change / previous_close * 100 if previous_close else None,
            "last_traded_at": datetime.fromtimestamp(bar.timestamp, NEPAL_TZ).isoformat(),
            "received_at": datetime.fromtimestamp(bar.timestamp, NEPAL_TZ).isoformat(),
            "intraday_range": range_value,
            "intraday_range_percent": range_value / bar.low * 100 if bar.low else None,
            "distance_from_open": bar.close - bar.open,
            "distance_from_open_percent": (bar.close - bar.open) / bar.open * 100 if bar.open else None,
            "distance_from_day_high": bar.high - bar.close,
            "distance_from_day_high_percent": (bar.high - bar.close) / bar.high * 100 if bar.high else None,
            "distance_from_day_low": bar.close - bar.low,
            "distance_from_day_low_percent": (bar.close - bar.low) / bar.low * 100 if bar.low else None,
            "distance_from_52_week_high": high_52 - bar.close,
            "distance_from_52_week_high_percent": (high_52 - bar.close) / high_52 * 100,
            "distance_from_52_week_low": bar.close - low_52,
            "distance_from_52_week_low_percent": (bar.close - low_52) / low_52 * 100,
            "position_in_52_week_range_percent": (bar.close - low_52) / range_52 * 100 if range_52 else 50.0,
            **indicator_rows[index],
        }
        # Point-in-time combined fields (fundamentals, sector values, and source
        # technicals) are safe only because they came from this exact snapshot day.
        for key, value in bar.extras.items():
            row.setdefault(str(key), value)
        yield row


def _daily_returns(equity_curve: List[Dict[str, Any]]) -> List[float]:
    values = [float(point["value"]) for point in equity_curve]
    return [values[index] / values[index - 1] - 1 for index in range(1, len(values)) if values[index - 1] > 0]


def _risk_metrics(
    *, equity_curve: List[Dict[str, Any]], trades: List[Dict[str, Any]],
    initial_capital: float, market_bars: List[Bar], exposure_bars: int,
    benchmark_return_pct: float, risk_free_rate_pct: float,
) -> Dict[str, Any]:
    returns = _daily_returns(equity_curve)
    mean_return = sum(returns) / len(returns) if returns else 0.0
    variance = sum((value - mean_return) ** 2 for value in returns) / max(len(returns) - 1, 1)
    volatility = math.sqrt(variance)
    downside = [min(value, 0.0) for value in returns]
    downside_deviation = math.sqrt(sum(value * value for value in downside) / max(len(downside), 1))
    annual_return = mean_return * 252
    risk_free_daily = risk_free_rate_pct / 100 / 252
    sharpe = (mean_return - risk_free_daily) / volatility * math.sqrt(252) if volatility else None
    sortino = (mean_return - risk_free_daily) / downside_deviation * math.sqrt(252) if downside_deviation else None
    final_equity = float(equity_curve[-1]["value"]) if equity_curve else initial_capital
    calendar_days = max((datetime.fromtimestamp(market_bars[-1].timestamp, NEPAL_TZ).date() - datetime.fromtimestamp(market_bars[0].timestamp, NEPAL_TZ).date()).days, 1)
    years = calendar_days / 365.25
    cagr = ((final_equity / initial_capital) ** (1 / years) - 1) * 100 if final_equity > 0 and years >= 0.08 else None
    wins = [trade for trade in trades if trade["pnl"] > 0]
    losses = [trade for trade in trades if trade["pnl"] < 0]
    average_win = sum(trade["return_pct"] for trade in wins) / len(wins) if wins else 0.0
    average_loss = abs(sum(trade["return_pct"] for trade in losses) / len(losses)) if losses else 0.0
    win_rate = len(wins) / len(trades) if trades else 0.0
    expectancy = win_rate * average_win - (1 - win_rate) * average_loss
    max_win_streak = max_loss_streak = current_win = current_loss = 0
    for trade in trades:
        if trade["pnl"] > 0:
            current_win += 1
            current_loss = 0
        elif trade["pnl"] < 0:
            current_loss += 1
            current_win = 0
        max_win_streak = max(max_win_streak, current_win)
        max_loss_streak = max(max_loss_streak, current_loss)
    net_return_pct = (final_equity / initial_capital - 1) * 100
    return {
        "cagr_pct": round(cagr, 2) if cagr is not None else None,
        "annual_volatility_pct": round(volatility * math.sqrt(252) * 100, 2),
        "sharpe_ratio": round(sharpe, 2) if sharpe is not None else None,
        "sortino_ratio": round(sortino, 2) if sortino is not None else None,
        "exposure_pct": round(exposure_bars / max(len(market_bars), 1) * 100, 2),
        "expectancy_pct": round(expectancy, 2),
        "average_win_pct": round(average_win, 2),
        "average_loss_pct": round(average_loss, 2),
        "payoff_ratio": round(average_win / average_loss, 2) if average_loss else None,
        "average_holding_days": round(sum(trade["holding_days"] for trade in trades) / len(trades), 2) if trades else 0,
        "max_consecutive_wins": max_win_streak,
        "max_consecutive_losses": max_loss_streak,
        "benchmark_return_pct": round(benchmark_return_pct, 2),
        "alpha_vs_benchmark_pct": round(net_return_pct - benchmark_return_pct, 2),
    }


def run_backtest(
    *, symbol: str, query_text: str, start_date: date, end_date: date,
    initial_capital: float = 100000, stop_loss_pct: float = 5,
    take_profit_pct: float = 10, min_holding_days: int = 0,
    max_holding_days: int = 20, fee_pct: float = 0.4,
    fixed_fee: float = 0, slippage_pct: float = 0.1, position_size_pct: float = 100,
    trailing_stop_pct: Optional[float] = None, max_volume_participation_pct: float = 10,
    risk_free_rate_pct: float = 4, data_source: str = "auto",
    charge_model: str = NEPSE_EQUITY_CHARGE_MODEL, investor_type: str = "individual",
    apply_cgt: bool = True, dp_charge: float = DEFAULT_DP_CHARGE,
    bars: Optional[List[Bar]] = None,
    prepared_rows: Optional[List[Dict[str, Any]]] = None,
    compact: bool = False,
    include_trades: bool = False,
    entry_signals: Optional[List[bool]] = None,
) -> Dict[str, Any]:
    clean_symbol = str(symbol or "").strip().upper()
    if initial_capital <= 0:
        raise BacktestError("Initial capital must be greater than zero.")
    if not (0 < stop_loss_pct <= 100 and 0 < take_profit_pct <= 500):
        raise BacktestError("Stop loss and take profit must be positive percentages.")
    if not (0 <= min_holding_days <= max_holding_days <= 365) or max_holding_days < 1:
        raise BacktestError("Holding days must satisfy 0 <= minimum <= maximum <= 365.")
    if not (0 <= fee_pct <= 10):
        raise BacktestError("Fee must be between 0% and 10%.")
    if fixed_fee < 0 or not (0 <= slippage_pct <= 10):
        raise BacktestError("Fixed fee and slippage cannot be negative.")
    try:
        charge_model = normalize_charge_model(charge_model)
    except ValueError as exc:
        raise BacktestError(str(exc)) from exc
    if investor_type not in {"individual", "institution", "institutional", "entity", "other", "non_resident"}:
        raise BacktestError("Investor type must be individual, institution, or other.")
    if dp_charge < 0:
        raise BacktestError("DP charge cannot be negative.")
    if not (0 < position_size_pct <= 100):
        raise BacktestError("Position size must be between 0% and 100% of available cash.")
    if trailing_stop_pct is not None and not (0 < trailing_stop_pct <= 100):
        raise BacktestError("Trailing stop must be between 0% and 100%.")
    if not (0 < max_volume_participation_pct <= 100):
        raise BacktestError("Volume participation must be between 0% and 100%.")
    try:
        plan = parse_strategy_query(query_text)
    except StrategyQueryError as exc:
        raise BacktestError(str(exc)) from exc
    if plan.backtest:
        config = plan.backtest
        initial_capital = config.initial_capital
        fee_pct = config.fee_pct
        fixed_fee = config.fixed_fee
        slippage_pct = config.slippage_pct
        stop_loss_pct = config.stop_loss_pct
        take_profit_pct = config.take_profit_pct
        trailing_stop_pct = config.trailing_stop_pct
        min_holding_days = config.min_holding_days
        max_holding_days = config.max_holding_days
        position_size_pct = config.position_size_pct
        max_volume_participation_pct = config.max_volume_participation_pct
        risk_free_rate_pct = config.risk_free_rate_pct
        data_source = config.data_source
        try:
            charge_model = normalize_charge_model(config.charge_model)
        except ValueError as exc:
            raise BacktestError(str(exc)) from exc
        investor_type = config.investor_type
        apply_cgt = config.apply_cgt
        dp_charge = config.dp_charge
        if initial_capital <= 0 or not (0 < stop_loss_pct <= 100) or not (0 < take_profit_pct <= 500):
            raise BacktestError("BACKTEST capital, stop loss, and take profit values are invalid.")
        if not (0 <= fee_pct <= 10 and 0 <= slippage_pct <= 10 and fixed_fee >= 0):
            raise BacktestError("BACKTEST fee or slippage values are invalid.")
        if not (0 <= min_holding_days <= max_holding_days <= 365 and max_holding_days >= 1 and 0 < position_size_pct <= 100):
            raise BacktestError("BACKTEST holding days or position size is invalid.")
        if trailing_stop_pct is not None and not (0 < trailing_stop_pct <= 100):
            raise BacktestError("BACKTEST trailing stop is invalid.")
        if not (0 < max_volume_participation_pct <= 100):
            raise BacktestError("BACKTEST volume participation is invalid.")
        if investor_type not in {"individual", "institution", "institutional", "entity", "other", "non_resident"}:
            raise BacktestError("BACKTEST investor type must be individual, institution, or other.")
        if dp_charge < 0:
            raise BacktestError("BACKTEST DP charge cannot be negative.")
    if plan.side != "BUY":
        raise BacktestError("The backtester currently expects a BUY entry strategy.")
    source_key = str(data_source or "auto").strip().lower()
    if source_key not in {"auto", "combined", "merolagani"}:
        raise BacktestError("Data source must be auto, combined, or merolagani.")
    resolved_source = "provided_test_data"
    if bars is not None:
        market_bars = bars
    elif source_key == "combined":
        market_bars = fetch_combined_snapshot_bars(clean_symbol, start_date, end_date)
        resolved_source = "combined_daily_snapshots"
    elif source_key == "merolagani":
        market_bars = fetch_historical_bars(clean_symbol, start_date, end_date)
        resolved_source = "merolagani_chart"
    else:
        try:
            combined_bars = fetch_combined_snapshot_bars(clean_symbol, start_date, end_date)
            requested_days = max((end_date - start_date).days, 1)
            coverage_days = (datetime.fromtimestamp(combined_bars[-1].timestamp, NEPAL_TZ).date() - datetime.fromtimestamp(combined_bars[0].timestamp, NEPAL_TZ).date()).days
            if coverage_days >= requested_days * 0.8:
                market_bars = combined_bars
                resolved_source = "combined_daily_snapshots"
            else:
                raise BacktestError("Combined snapshot coverage is incomplete.")
        except BacktestError:
            market_bars = fetch_historical_bars(clean_symbol, start_date, end_date)
            resolved_source = "merolagani_chart"
    available_fields = set().union(*(set(bar.extras) for bar in market_bars)) if market_bars else set()
    rules = _validate_historical_plan(plan, clean_symbol, available_fields=available_fields)

    histories = {rule.rule_id: TargetHistory() for rule in rules}
    rows = prepared_rows if prepared_rows is not None else list(_historical_rows(clean_symbol, market_bars))
    if len(rows) != len(market_bars):
        raise BacktestError("Prepared historical rows do not match the market bars.")
    if entry_signals is not None and len(entry_signals) != len(market_bars):
        raise BacktestError("Compiled entry signals do not match the market bars.")
    pending_signal: Optional[Dict[str, Any]] = None
    position: Optional[Dict[str, Any]] = None
    cash = float(initial_capital)
    trades: List[Dict[str, Any]] = []
    equity_curve: List[Dict[str, Any]] = []
    total_fees = 0.0
    total_taxes = 0.0
    total_broker_commission = 0.0
    total_sebon_fees = 0.0
    total_dp_charges = 0.0
    total_slippage_cost = 0.0
    exposure_bars = 0
    rejected_orders = 0

    for index, (bar, row) in enumerate(zip(market_bars, rows)):
        if pending_signal and position is None:
            raw_entry_price = bar.open
            entry_price = raw_entry_price * (1 + slippage_pct / 100)
            entry_day = date.fromisoformat(bar.day)
            budget = cash * position_size_pct / 100
            order_mode = str(pending_signal.get("order_mode") or "percent_of_available_cash")
            order_value = pending_signal.get("order_value")
            if order_mode == "quantity" and order_value is not None and float(order_value) > 0:
                quantity = math.floor(float(order_value))
            elif order_mode in {"amount", "target_position_value"} and order_value is not None:
                budget = min(budget, float(order_value))
                quantity = maximum_affordable_quantity(
                    budget, entry_price, entry_day, charge_model=charge_model,
                    fee_pct=fee_pct, fixed_fee=fixed_fee,
                )
            elif order_mode == "percent_of_available_cash" and order_value is not None:
                budget = min(budget, cash * float(order_value) / 100)
                quantity = maximum_affordable_quantity(
                    budget, entry_price, entry_day, charge_model=charge_model,
                    fee_pct=fee_pct, fixed_fee=fixed_fee,
                )
            elif order_mode == "risk_percent" and order_value is not None:
                risk_budget = cash * float(order_value) / 100
                per_share_risk = entry_price * stop_loss_pct / 100
                quantity = math.floor(risk_budget / per_share_risk) if per_share_risk else 0
            else:
                quantity = maximum_affordable_quantity(
                    budget, entry_price, entry_day, charge_model=charge_model,
                    fee_pct=fee_pct, fixed_fee=fixed_fee,
                )
            affordable = maximum_affordable_quantity(
                cash, entry_price, entry_day, charge_model=charge_model,
                fee_pct=fee_pct, fixed_fee=fixed_fee,
            )
            quantity = min(quantity, affordable)
            if bar.volume > 0:
                quantity = min(quantity, math.floor(bar.volume * max_volume_participation_pct / 100))
            if quantity > 0:
                entry_cost = quantity * entry_price
                entry_charge_details = buy_charges(
                    entry_cost, entry_day, charge_model=charge_model,
                    fee_pct=fee_pct, fixed_fee=fixed_fee,
                )
                entry_fee = entry_charge_details["total"]
                cash -= entry_cost + entry_fee
                total_fees += entry_fee
                total_broker_commission += entry_charge_details["broker_commission"]
                total_sebon_fees += entry_charge_details["sebon_fee"]
                total_slippage_cost += quantity * (entry_price - raw_entry_price)
                position = {
                    "entry_index": index, "entry_date": bar.day, "entry_price": entry_price,
                    "quantity": quantity, "entry_fee": entry_fee, "entry_cost": entry_cost,
                    "entry_charges": entry_charge_details, "rule_name": pending_signal["rule_name"],
                    "signal_date": pending_signal["signal_date"], "highest_price": bar.high,
                }
            else:
                rejected_orders += 1
            pending_signal = None

        if position:
            exposure_bars += 1
            position["highest_price"] = max(position["highest_price"], bar.high)
            fixed_stop_price = position["entry_price"] * (1 - stop_loss_pct / 100)
            trailing_price = position["highest_price"] * (1 - trailing_stop_pct / 100) if trailing_stop_pct else 0
            stop_price = max(fixed_stop_price, trailing_price)
            target_price = position["entry_price"] * (1 + take_profit_pct / 100)
            held_days = index - position["entry_index"]
            exit_price: Optional[float] = None
            exit_reason = ""
            if bar.low <= stop_price:
                raw_exit_price, exit_reason = min(bar.open, stop_price), "trailing_stop" if trailing_price >= fixed_stop_price and trailing_stop_pct else "stop_loss"
            elif held_days >= min_holding_days and bar.high >= target_price:
                raw_exit_price, exit_reason = max(bar.open, target_price), "take_profit"
            elif held_days >= max_holding_days:
                raw_exit_price, exit_reason = bar.close, "max_holding_days"
            elif index == len(market_bars) - 1:
                raw_exit_price, exit_reason = bar.close, "end_of_data"
            if exit_reason:
                exit_price = raw_exit_price * (1 - slippage_pct / 100)
            if exit_price is not None:
                proceeds = position["quantity"] * exit_price
                exit_charge_details = sell_charges(
                    proceeds, date.fromisoformat(bar.day),
                    entry_total_cost=position["entry_cost"] + position["entry_fee"],
                    holding_days=held_days, investor_type=investor_type,
                    apply_cgt=apply_cgt, dp_charge=dp_charge,
                    charge_model=charge_model, fee_pct=fee_pct, fixed_fee=fixed_fee,
                )
                exit_fee = exit_charge_details["total"]
                tax = exit_charge_details["capital_gains_tax"]
                non_tax_exit_fee = exit_fee - tax
                cash += proceeds - exit_fee
                total_fees += non_tax_exit_fee
                total_taxes += tax
                total_broker_commission += exit_charge_details["broker_commission"]
                total_sebon_fees += exit_charge_details["sebon_fee"]
                total_dp_charges += exit_charge_details["dp_charge"]
                total_slippage_cost += position["quantity"] * (raw_exit_price - exit_price)
                pnl = proceeds - exit_fee - position["quantity"] * position["entry_price"] - position["entry_fee"]
                invested = position["quantity"] * position["entry_price"] + position["entry_fee"]
                gross_pnl = proceeds - position["entry_cost"]
                net_pnl_before_tax = exit_charge_details["profit_before_tax"]
                trades.append({
                    "id": len(trades) + 1, "symbol": clean_symbol, "rule_name": position["rule_name"],
                    "signal_date": position["signal_date"], "entry_date": position["entry_date"],
                    "entry_price": round(position["entry_price"], 2), "exit_date": bar.day,
                    "exit_price": round(exit_price, 2), "quantity": position["quantity"],
                    "holding_days": held_days, "exit_reason": exit_reason,
                    "fees": round(position["entry_fee"] + non_tax_exit_fee, 2),
                    "broker_commission": round(position["entry_charges"]["broker_commission"] + exit_charge_details["broker_commission"], 2),
                    "buy_broker_commission": round(position["entry_charges"]["broker_commission"], 2),
                    "sell_broker_commission": round(exit_charge_details["broker_commission"], 2),
                    "sebon_fee": round(position["entry_charges"]["sebon_fee"] + exit_charge_details["sebon_fee"], 2),
                    "buy_sebon_fee": round(position["entry_charges"]["sebon_fee"], 2),
                    "sell_sebon_fee": round(exit_charge_details["sebon_fee"], 2),
                    "dp_charge": round(exit_charge_details["dp_charge"], 2),
                    "capital_gains_tax": round(tax, 2),
                    "capital_gains_tax_rate_pct": round(exit_charge_details["tax_rate"] * 100, 4),
                    "total_charges": round(position["entry_fee"] + exit_fee, 2),
                    "gross_pnl": round(gross_pnl, 2),
                    "net_pnl_before_tax": round(net_pnl_before_tax, 2),
                    "slippage_cost": round(position["quantity"] * ((position["entry_price"] - market_bars[position["entry_index"]].open) + (raw_exit_price - exit_price)), 2),
                    "pnl": round(pnl, 2), "return_pct": round(pnl / invested * 100, 2),
                    "result": "win" if pnl > 0 else "loss" if pnl < 0 else "break_even",
                })
                position = None

        market_value = position["quantity"] * bar.close if position else 0
        equity_curve.append({"time": bar.timestamp, "date": bar.day, "value": round(cash + market_value, 2)})

        if position is None and index < len(market_bars) - 1:
            if entry_signals is not None:
                rule = rules[0]
                history = histories[rule.rule_id]
                if entry_signals[index] and (not rule.execution.max_times or history.execution_count < rule.execution.max_times):
                    pending_signal = {"rule_name": rule.name, "signal_date": bar.day,
                                      "order_mode": rule.order.mode, "order_value": rule.order.value}
                    history.execution_count += 1
            else:
                for rule in rules:
                    history = histories[rule.rule_id]
                    if rule.execution.max_times and history.execution_count >= rule.execution.max_times:
                        continue
                    update_history_from_snapshot(history, row)
                    result = evaluate_rule(
                        rule, clean_symbol, row, history,
                        trigger_on_cross=(rule.execution.trigger or "on_cross") != "level",
                    )
                    if result.final_result:
                        pending_signal = {
                            "rule_name": rule.name, "signal_date": bar.day,
                            "order_mode": rule.order.mode, "order_value": rule.order.value,
                        }
                        history.execution_count += 1
                        if (rule.execution.frequency or "once") in {"once", "once_per_symbol"}:
                            history.executed = True
                        break
        else:
            if entry_signals is None:
                for rule in rules:
                    update_history_from_snapshot(histories[rule.rule_id], row)

    wins = [trade for trade in trades if trade["pnl"] > 0]
    losses = [trade for trade in trades if trade["pnl"] < 0]
    gross_profit = sum(trade["pnl"] for trade in wins)
    gross_loss = abs(sum(trade["pnl"] for trade in losses))
    peak = initial_capital
    max_drawdown = 0.0
    for point in equity_curve:
        peak = max(peak, point["value"])
        if peak:
            max_drawdown = max(max_drawdown, (peak - point["value"]) / peak * 100)
    final_equity = equity_curve[-1]["value"] if equity_curve else initial_capital
    benchmark_entry = market_bars[0].open * (1 + slippage_pct / 100)
    benchmark_exit = market_bars[-1].close * (1 - slippage_pct / 100)
    benchmark_entry_day = date.fromisoformat(market_bars[0].day)
    benchmark_exit_day = date.fromisoformat(market_bars[-1].day)
    benchmark_quantity = maximum_affordable_quantity(
        initial_capital, benchmark_entry, benchmark_entry_day,
        charge_model=charge_model, fee_pct=fee_pct, fixed_fee=fixed_fee,
    )
    benchmark_entry_gross = benchmark_quantity * benchmark_entry
    benchmark_buy_charges = buy_charges(
        benchmark_entry_gross, benchmark_entry_day, charge_model=charge_model,
        fee_pct=fee_pct, fixed_fee=fixed_fee,
    )
    benchmark_entry_total = benchmark_entry_gross + benchmark_buy_charges["total"]
    benchmark_exit_gross = benchmark_quantity * benchmark_exit
    benchmark_sell_charges = sell_charges(
        benchmark_exit_gross, benchmark_exit_day, entry_total_cost=benchmark_entry_total,
        holding_days=(benchmark_exit_day - benchmark_entry_day).days,
        investor_type=investor_type, apply_cgt=apply_cgt, dp_charge=dp_charge,
        charge_model=charge_model, fee_pct=fee_pct, fixed_fee=fixed_fee,
    )
    benchmark_final = initial_capital - benchmark_entry_total + benchmark_exit_gross - benchmark_sell_charges["total"]
    benchmark_return_pct = (benchmark_final / initial_capital - 1) * 100 if initial_capital else 0
    advanced_metrics = _risk_metrics(
        equity_curve=equity_curve, trades=trades, initial_capital=initial_capital,
        market_bars=market_bars, exposure_bars=exposure_bars,
        benchmark_return_pct=benchmark_return_pct, risk_free_rate_pct=risk_free_rate_pct,
    )
    chart_bars = [] if compact else [
        {"time": bar.timestamp, "date": bar.day, "open": bar.open, "high": bar.high,
         "low": bar.low, "close": bar.close, "volume": bar.volume}
        for bar in market_bars
    ]
    return {
        "symbol": clean_symbol,
        "data_source": (
            "Point-in-time combined daily snapshot archive" if resolved_source == "combined_daily_snapshots"
            else "MeroLagani TechnicalChartHandler (adjusted daily OHLCV)" if resolved_source == "merolagani_chart"
            else "Provided test OHLCV"
        ),
        "data_source_key": resolved_source,
        "period": {"start": market_bars[0].day, "end": market_bars[-1].day, "bars": len(market_bars)},
        "assumptions": {
            "entry": "Signal at daily close; entry at next available session open",
            "intraday_priority": "Stop loss is applied first if stop and target are both touched",
            "charge_model": charge_model,
            "investor_type": investor_type,
            "capital_gains_tax_enabled": apply_cgt,
            "dp_charge_each_sell": dp_charge if charge_model == NEPSE_EQUITY_CHARGE_MODEL else 0,
            "brokerage_schedule": "Historical equity slabs; current rates effective 2024-05-14",
            "sebon_transaction_fee_pct_each_side": .015 if charge_model == NEPSE_EQUITY_CHARGE_MODEL else 0,
            "capital_gains_tax_policy": "Listed shares: individual 7.5% up to 365 days, 5% after 365 days; institution 10%",
            "legacy_flat_fee_pct_each_side": fee_pct if charge_model != NEPSE_EQUITY_CHARGE_MODEL else 0,
            "legacy_fixed_fee_each_order": fixed_fee if charge_model != NEPSE_EQUITY_CHARGE_MODEL else 0,
            "slippage_pct_each_side": slippage_pct,
            "position_size_pct": position_size_pct,
            "trailing_stop_pct": trailing_stop_pct,
            "min_holding_days": min_holding_days,
            "max_holding_days": max_holding_days,
            "max_volume_participation_pct": max_volume_participation_pct,
        },
        "summary": {
            "initial_capital": round(initial_capital, 2), "final_equity": round(final_equity, 2),
            "net_profit": round(final_equity - initial_capital, 2),
            "net_return_pct": round((final_equity / initial_capital - 1) * 100, 2),
            "total_trades": len(trades), "wins": len(wins), "losses": len(losses),
            "win_rate_pct": round(len(wins) / len(trades) * 100, 2) if trades else 0,
            "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss else None,
            "gross_profit": round(gross_profit, 2), "gross_loss": round(gross_loss, 2),
            "largest_winning_trade": round(max((trade["pnl"] for trade in wins), default=0), 2),
            "largest_losing_trade": round(min((trade["pnl"] for trade in losses), default=0), 2),
            "maximum_holding_days": max((int(trade["holding_days"]) for trade in trades), default=0),
            "max_drawdown_pct": round(max_drawdown, 2),
            "average_trade_pct": round(sum(trade["return_pct"] for trade in trades) / len(trades), 2) if trades else 0,
            "total_fees": round(total_fees, 2), "total_taxes": round(total_taxes, 2),
            "total_charges": round(total_fees + total_taxes, 2),
            "total_broker_commission": round(total_broker_commission, 2),
            "total_sebon_fees": round(total_sebon_fees, 2),
            "total_dp_charges": round(total_dp_charges, 2),
            "total_slippage_cost": round(total_slippage_cost, 2),
            "rejected_orders": rejected_orders,
            **advanced_metrics,
        },
        "trades": trades if (not compact or include_trades) else [],
        "bars": chart_bars,
        "equity_curve": [] if compact else equity_curve,
    }
