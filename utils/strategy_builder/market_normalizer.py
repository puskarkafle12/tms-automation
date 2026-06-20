from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from utils.external_data_sources.nepse_alpha.screener import flatten_nepse_alpha_for_screener
from utils.external_data_sources.nepse_alpha.client import get_nepse_alpha_signals_async
from utils.strategies.normalize import normalize_tms_quote
from utils.strategies.types import MarketSnapshot, ScriptDetails


def _pct_distance(value: Optional[float], base: Optional[float]) -> Optional[float]:
    if value is None or base in (None, 0):
        return None
    return ((value - base) / base) * 100.0


def _script_details_to_fields(details: ScriptDetails) -> Dict[str, Any]:
    return {
        "alpha_annualized": details.alpha_annualized,
        "beta_3_month": details.beta_3_month,
        "sharpe_ratio_annualized": details.sharpe_annualized,
        "daily_var_95": details.daily_var_95,
        "volatility_50d": details.volatility_50d,
        "one_year_yield": details.one_year_yield,
        "fifty_two_week_high": details.fifty_two_week_high,
        "fifty_two_week_low": details.fifty_two_week_low,
        "all_time_high": details.all_time_high,
        "all_time_low": details.all_time_low,
        "fundamental_pe_ttm": details.pe,
        "fundamental_pbv": details.pbv,
        "fundamental_roe_ttm": details.roe,
        "fundamental_ps_ttm": details.ps,
        "fundamental_peg_3_5_yrs": details.peg,
        "fundamental_roa_ttm": details.roa,
        "fundamental_dividend_yield": details.dividend_yield,
        "fundamental_payout_ratio": details.payout_ratio,
        "fundamental_qoq_earnings_growth": details.qoq_earnings_growth,
        "fundamental_yoy_earnings_growth": details.yoy_earnings_growth,
        "fundamental_distance_from_graham_number": details.distance_from_graham_number,
        "fundamental_debt_to_equity": details.debt_to_equity,
        "technical_rsi_14": details.rsi_14,
        "technical_mfi_14": details.mfi_14,
        "technical_price_relative_strength": details.price_relative_strength,
        "technical_percent_b": details.percent_b,
        "technical_stochastic_14": details.stochastic_14,
        "technical_macd": details.macd_signal,
        "technical_sma_10": details.sma_10_status,
        "technical_sma_20": details.sma_20_status,
        "technical_sma_50": details.sma_50_status,
        "technical_sma_200": details.sma_200_status,
        "technical_volume_trend": details.volume_trend,
        "technical_3m_price_tend": details.three_month_price_trend,
    }


def _snapshot_to_live(snapshot: MarketSnapshot) -> Dict[str, Any]:
    high = snapshot.high
    low = snapshot.low
    open_price = snapshot.open
    ltp = snapshot.ltp
    return {
        "symbol": snapshot.symbol,
        "ltp": ltp,
        "open": open_price,
        "high": high,
        "low": low,
        "volume": snapshot.volume,
        "previous_close": snapshot.prev_close,
        "change": snapshot.change,
        "change_percent": snapshot.change_percent,
        "last_traded_at": snapshot.last_traded_time,
        "intraday_range": (high - low) if high is not None and low is not None else None,
        "intraday_range_percent": _pct_distance(high, low),
        "distance_from_open": (ltp - open_price) if open_price is not None else None,
        "distance_from_open_percent": _pct_distance(ltp, open_price),
        "distance_from_day_high": (ltp - high) if high is not None else None,
        "distance_from_day_high_percent": _pct_distance(ltp, high),
        "distance_from_day_low": (ltp - low) if low is not None else None,
        "distance_from_day_low_percent": _pct_distance(ltp, low),
    }


def _depth_fields(snapshot: MarketSnapshot) -> Dict[str, Any]:
    buy_levels = snapshot.top_buy_orders or []
    sell_levels = snapshot.top_sell_orders or []
    available = bool(buy_levels or sell_levels)
    best_bid = buy_levels[0].price if buy_levels else None
    best_ask = sell_levels[0].price if sell_levels else None
    spread = (best_ask - best_bid) if best_bid is not None and best_ask is not None else None
    spread_percent = _pct_distance(spread, best_bid) if spread is not None else None
    top_buy_qty = buy_levels[0].quantity if buy_levels else 0
    top_sell_qty = sell_levels[0].quantity if sell_levels else 0
    total_buy_qty = sum(level.quantity for level in buy_levels)
    total_sell_qty = sum(level.quantity for level in sell_levels)
    ratio = (total_buy_qty / total_sell_qty) if total_sell_qty else None
    imbalance = ((total_buy_qty - total_sell_qty) / (total_buy_qty + total_sell_qty)) if (total_buy_qty + total_sell_qty) else None
    return {
        "market_depth_available": available,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread": spread,
        "spread_percent": spread_percent,
        "top_buy_quantity": top_buy_qty,
        "top_sell_quantity": top_sell_qty,
        "total_buy_quantity": total_buy_qty,
        "total_sell_quantity": total_sell_qty,
        "buy_sell_quantity_ratio": ratio,
        "order_book_imbalance": imbalance,
        "buy_levels": [{"level": idx + 1, "price": level.price, "quantity": level.quantity} for idx, level in enumerate(buy_levels)],
        "sell_levels": [{"level": idx + 1, "price": level.price, "quantity": level.quantity} for idx, level in enumerate(sell_levels)],
    }


def _derived_stat_fields(flat: Dict[str, Any], live: Dict[str, Any]) -> Dict[str, Any]:
    ltp = live.get("ltp")
    week_high = flat.get("fifty_two_week_high")
    week_low = flat.get("fifty_two_week_low")
    ath = flat.get("all_time_high")
    atl = flat.get("all_time_low")
    position_pct = None
    if ltp is not None and week_high is not None and week_low is not None and week_high != week_low:
        position_pct = ((ltp - week_low) / (week_high - week_low)) * 100.0
    return {
        "distance_from_52_week_high": (ltp - week_high) if ltp is not None and week_high is not None else None,
        "distance_from_52_week_high_percent": _pct_distance(ltp, week_high),
        "distance_from_52_week_low": (ltp - week_low) if ltp is not None and week_low is not None else None,
        "distance_from_52_week_low_percent": _pct_distance(ltp, week_low),
        "position_in_52_week_range_percent": position_pct,
        "distance_from_all_time_high_percent": _pct_distance(ltp, ath),
        "distance_from_all_time_low_percent": _pct_distance(ltp, atl),
    }


async def build_symbol_snapshot(symbol: str, quote_payload: Optional[dict] = None) -> Dict[str, Any]:
    normalized_symbol = symbol.upper()
    snapshot = normalize_tms_quote(normalized_symbol, quote_payload or {"ltp": 0})
    alpha_payload = await get_nepse_alpha_signals_async(normalized_symbol)
    flat = flatten_nepse_alpha_for_screener(alpha_payload or {"symbol": normalized_symbol})
    live = _snapshot_to_live(snapshot)
    depth = _depth_fields(snapshot)
    derived = _derived_stat_fields(flat, live)
    now = datetime.now(timezone.utc).isoformat()
    return {
        "symbol": normalized_symbol,
        "live": live,
        "statistics": {key: flat.get(key) for key in flat if key.startswith(("alpha_", "beta_", "sharpe_", "daily_", "volatility_", "one_year_", "fifty_two_", "all_time_"))},
        "technical": {key: flat.get(key) for key in flat if key.startswith("technical_")},
        "fundamental": {key: flat.get(key) for key in flat if key.startswith("fundamental_")},
        "market_depth": depth,
        "flat": {**flat, **live, **derived, **depth},
        "metadata": {
            "cached": bool(alpha_payload),
            "source_fetched_at": flat.get("fetched_at"),
            "received_at": now,
        },
    }


def build_symbol_snapshot_from_parts(symbol: str, snapshot: MarketSnapshot, details: ScriptDetails, flat: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    live = _snapshot_to_live(snapshot)
    depth = _depth_fields(snapshot)
    merged_flat = dict(flat or {})
    merged_flat.update(_script_details_to_fields(details))
    merged_flat.update(live)
    merged_flat.update(_derived_stat_fields(merged_flat, live))
    merged_flat.update(depth)
    return {
        "symbol": symbol.upper(),
        "live": live,
        "statistics": {key: merged_flat.get(key) for key in merged_flat if key in {
            "alpha_annualized", "beta_3_month", "sharpe_ratio_annualized", "daily_var_95", "volatility_50d",
            "one_year_yield", "fifty_two_week_high", "fifty_two_week_low", "all_time_high", "all_time_low",
        }},
        "technical": {key: merged_flat.get(key) for key in merged_flat if str(key).startswith("technical_")},
        "fundamental": {key: merged_flat.get(key) for key in merged_flat if str(key).startswith("fundamental_")},
        "market_depth": depth,
        "flat": merged_flat,
        "metadata": {"cached": details.available, "received_at": datetime.now(timezone.utc).isoformat()},
    }
