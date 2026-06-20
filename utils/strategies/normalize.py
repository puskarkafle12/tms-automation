from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional

from utils.external_data_sources.nepse_alpha import get_nepse_alpha_signals
from utils.strategies.helpers import safe_number
from utils.strategies.types import MarketSnapshot, OrderBookLevel, ScriptDetails

_DETAILS_CACHE: Dict[str, Dict[str, Any]] = {}
_DETAILS_TTL_SECONDS = 30 * 60


def _parse_sma_status(value: Optional[str]) -> Optional[str]:
    if not value:
        return "unknown"
    lowered = value.lower()
    if "below" in lowered:
        return "below"
    if "above" in lowered:
        return "above"
    return "unknown"


def _find_signal_value(rows: List[Dict[str, Any]], *needles: str) -> Optional[str]:
    for row in rows:
        indicator = str(row.get("indicator") or "").lower()
        if any(needle.lower() in indicator for needle in needles):
            if row.get("symbol_value"):
                return str(row["symbol_value"])
            if row.get("signal"):
                return str(row["signal"])
    return None


def normalize_tms_quote(symbol: str, quote: Optional[Dict[str, Any]]) -> MarketSnapshot:
    payload = quote or {}
    top_buy = [
        OrderBookLevel(price=float(item.get("price") or 0), quantity=float(item.get("quantity") or 0))
        for item in (payload.get("topBuy") or [])
        if safe_number(item.get("price")) is not None
    ]
    top_sell = [
        OrderBookLevel(price=float(item.get("price") or 0), quantity=float(item.get("quantity") or 0))
        for item in (payload.get("topSell") or [])
        if safe_number(item.get("price")) is not None
    ]
    return MarketSnapshot(
        symbol=(symbol or payload.get("security", {}).get("symbol") or "").upper(),
        ltp=float(safe_number(payload.get("ltp")) or 0.0),
        open=safe_number(payload.get("openPrice") or payload.get("open")),
        high=safe_number(payload.get("dayHigh") or payload.get("high")),
        low=safe_number(payload.get("dayLow") or payload.get("low")),
        volume=safe_number(payload.get("volume")),
        prev_close=safe_number(payload.get("closePrice") or payload.get("previousClose")),
        change=safe_number(payload.get("change")),
        change_percent=safe_number(payload.get("changePercentage") or payload.get("percentChange")),
        last_traded_time=str(payload.get("lastTradedTime") or "") or None,
        top_buy_orders=top_buy,
        top_sell_orders=top_sell,
    )


def normalize_nepse_alpha_payload(payload: Dict[str, Any]) -> ScriptDetails:
    stats = payload.get("statistical_performance") or {}
    fundamentals = payload.get("fundamental_signals") or []
    technicals = payload.get("technical_signals") or []

    macd = _find_signal_value(technicals, "macd")
    volume_trend = _find_signal_value(technicals, "volume trend")
    three_month = _find_signal_value(technicals, "3 month", "three month")

    details = ScriptDetails(
        alpha_annualized=safe_number(stats.get("alpha_anualized") or stats.get("alpha_annualized")),
        beta_3_month=safe_number(stats.get("beta_3_month")),
        sharpe_annualized=safe_number(stats.get("sharpe_ratio_anualized") or stats.get("sharpe_ratio_annualized")),
        daily_var_95=safe_number(stats.get("daily_var_95_ci") or stats.get("daily_var_95")),
        volatility_50d=safe_number(stats.get("50d")),
        one_year_yield=safe_number(stats.get("1_year_yield")),
        pe=safe_number(_find_signal_value(fundamentals, "pe")),
        pbv=safe_number(_find_signal_value(fundamentals, "pbv")),
        roe=safe_number(_find_signal_value(fundamentals, "roe")),
        ps=safe_number(_find_signal_value(fundamentals, "ps")),
        peg=safe_number(_find_signal_value(fundamentals, "peg")),
        roa=safe_number(_find_signal_value(fundamentals, "roa")),
        dividend_yield=safe_number(_find_signal_value(fundamentals, "dividend yield")),
        payout_ratio=safe_number(_find_signal_value(fundamentals, "payout ratio")),
        qoq_earnings_growth=safe_number(_find_signal_value(fundamentals, "qoq")),
        yoy_earnings_growth=safe_number(_find_signal_value(fundamentals, "yoy")),
        distance_from_graham_number=safe_number(_find_signal_value(fundamentals, "graham")),
        debt_to_equity=safe_number(_find_signal_value(fundamentals, "debt to equity")),
        rsi_14=safe_number(_find_signal_value(technicals, "rsi 14", "rsi")),
        mfi_14=safe_number(_find_signal_value(technicals, "mfi 14", "mfi")),
        price_relative_strength=safe_number(_find_signal_value(technicals, "price relative strength")),
        percent_b=safe_number(_find_signal_value(technicals, "percent b", "%b")),
        stochastic_14=safe_number(_find_signal_value(technicals, "stochastic 14", "stochastic")),
        macd_signal=macd,
        sma_10_status=_parse_sma_status(_find_signal_value(technicals, "sma 10")),
        sma_20_status=_parse_sma_status(_find_signal_value(technicals, "sma 20")),
        sma_50_status=_parse_sma_status(_find_signal_value(technicals, "sma 50")),
        sma_200_status=_parse_sma_status(_find_signal_value(technicals, "sma 200")),
        volume_trend=volume_trend,
        three_month_price_trend=three_month,
        available=True,
    )

    week_range = stats.get("52_weeks_high_low") or stats.get("52_week_high_low")
    if week_range:
        parts = re.split(r"[/]", str(week_range))
        if len(parts) >= 2:
            details.fifty_two_week_high = safe_number(parts[0])
            details.fifty_two_week_low = safe_number(parts[1])

    details.all_time_high = safe_number(stats.get("all_time_high"))
    details.all_time_low = safe_number(stats.get("all_time_low"))
    details.reference_ltp = safe_number(stats.get("ltp"))
    return details


_DETAILS_FAILURE_TTL_SECONDS = 90


def _cached_script_details(symbol: str, *, force_refresh: bool = False) -> tuple[ScriptDetails, bool]:
    """Return (details, network_attempted). network_attempted is False on cache hit."""
    normalized = (symbol or "").strip().upper()
    if not normalized:
        return ScriptDetails(available=False, fetch_error="Symbol is required"), False

    now = time.time()
    cached = _DETAILS_CACHE.get(normalized)
    if not force_refresh and cached and now < float(cached.get("expires_at") or 0):
        return cached["details"], False

    last_error: Optional[str] = None
    details = ScriptDetails(available=False, fetch_error=None)
    for attempt in range(2):
        try:
            payload = get_nepse_alpha_signals(
                normalized,
                force_refresh_key=attempt > 0,
            )
            details = normalize_nepse_alpha_payload(payload)
            last_error = None
            break
        except Exception as exc:
            last_error = str(exc)
            details = ScriptDetails(available=False, fetch_error=last_error)

    ttl = _DETAILS_TTL_SECONDS if details.available else _DETAILS_FAILURE_TTL_SECONDS
    _DETAILS_CACHE[normalized] = {
        "details": details,
        "expires_at": now + ttl,
    }
    return details, True


def get_script_details(symbol: str, *, force_refresh: bool = False) -> ScriptDetails:
    details, _ = _cached_script_details(symbol, force_refresh=force_refresh)
    return details


def get_script_details_fetch_meta(symbol: str, *, force_refresh: bool = False) -> tuple[ScriptDetails, bool]:
    """Return script details and whether a network fetch was attempted (cache miss)."""
    return _cached_script_details(symbol, force_refresh=force_refresh)
