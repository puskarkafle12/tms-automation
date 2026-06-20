from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def _pct_change(current: Optional[float], base: Optional[float]) -> Optional[float]:
    if current is None or base in (None, 0):
        return None
    return ((current - base) / base) * 100.0


def _position_in_range(value: Optional[float], low: Optional[float], high: Optional[float]) -> Optional[float]:
    if value is None or low is None or high is None or high == low:
        return None
    return ((value - low) / (high - low)) * 100.0


def compute_market_position_fields(flat: Dict[str, Any]) -> Dict[str, Any]:
    ltp = flat.get("ltp")
    open_price = flat.get("open")
    high = flat.get("high")
    low = flat.get("low")
    prev_close = flat.get("previous_close")
    return {
        "opening_gap_percent": _pct_change(open_price, prev_close),
        "position_in_intraday_range_percent": _position_in_range(ltp, low, high),
        "distance_from_previous_close_percent": _pct_change(ltp, prev_close),
    }


def compute_position_performance_fields(
    flat: Dict[str, Any],
    position_state: Dict[str, Any],
    *,
    qty: Optional[int] = None,
) -> Dict[str, Any]:
    ltp = flat.get("ltp")
    entry = position_state.get("entry_price")
    highest = position_state.get("highest_price_since_entry")
    holding_scans = int(position_state.get("holding_scan_count") or 0)
    entry_at = position_state.get("entry_at")

    profit_percent = _pct_change(ltp, entry)
    runup_percent = _pct_change(highest, entry) if highest is not None and entry else None
    drawdown_from_peak_percent = _pct_change(ltp, highest) if highest not in (None, 0) else None
    distance_from_entry_percent = profit_percent
    unrealized_profit = None
    if ltp is not None and entry is not None and qty:
        unrealized_profit = (float(ltp) - float(entry)) * int(qty)

    time_since_entry_minutes = None
    if entry_at:
        try:
            parsed = datetime.fromisoformat(str(entry_at).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            time_since_entry_minutes = (datetime.now(timezone.utc) - parsed).total_seconds() / 60.0
        except (TypeError, ValueError):
            time_since_entry_minutes = None

    return {
        "profit_percent": profit_percent,
        "unrealized_profit": unrealized_profit,
        "runup_percent": runup_percent,
        "drawdown_from_peak_percent": drawdown_from_peak_percent,
        "distance_from_entry_percent": distance_from_entry_percent,
        "holding_scan_count": holding_scans if entry else None,
        "time_since_entry_minutes": time_since_entry_minutes,
    }


def compute_volatility_risk_fields(flat: Dict[str, Any]) -> Dict[str, Any]:
    vol = flat.get("volatility_50d")
    var95 = flat.get("daily_var_95")
    beta = flat.get("beta_3_month")
    ltp = flat.get("ltp")
    stop = flat.get("effective_stop_price") or flat.get("fixed_stop_loss_price")
    entry = flat.get("entry_price")

    volatility_risk_score = None
    if vol is not None:
        volatility_risk_score = float(vol) * (1.0 + (abs(float(beta)) * 0.1 if beta is not None else 0))

    stop_distance_percent = None
    if ltp not in (None, 0) and stop is not None:
        stop_distance_percent = abs((float(ltp) - float(stop)) / float(ltp)) * 100.0

    position_risk_percent = None
    if entry not in (None, 0) and stop is not None:
        position_risk_percent = abs((float(entry) - float(stop)) / float(entry)) * 100.0

    return {
        "volatility_risk_score": volatility_risk_score,
        "stop_distance_percent": stop_distance_percent,
        "position_risk_percent": position_risk_percent,
        "daily_var_95": var95,
        "beta_3_month": beta,
    }


def compute_liquidity_fields(flat: Dict[str, Any], order_qty: int = 0) -> Dict[str, Any]:
    qty = max(0, int(order_qty or 0))
    top_buy = float(flat.get("top_buy_quantity") or 0)
    top_sell = float(flat.get("top_sell_quantity") or 0)
    total_buy = float(flat.get("total_buy_quantity") or 0)
    total_sell = float(flat.get("total_sell_quantity") or 0)
    total_depth = total_buy + total_sell
    spread_pct = flat.get("spread_percent")

    order_quantity_to_top_buy_ratio = (qty / top_buy) if top_buy > 0 and qty else None
    order_quantity_to_top_sell_ratio = (qty / top_sell) if top_sell > 0 and qty else None
    order_quantity_to_total_depth_ratio = (qty / total_depth) if total_depth > 0 and qty else None

    estimated_slippage_percent = spread_pct
    depth_supported_quantity = int(min(total_buy, total_sell)) if total_buy and total_sell else int(max(total_buy, total_sell))

    prev_spread = flat.get("_prev_spread_percent")
    spread_change_percent = None
    if spread_pct is not None and prev_spread is not None:
        spread_change_percent = float(spread_pct) - float(prev_spread)

    return {
        "order_quantity_to_top_buy_ratio": order_quantity_to_top_buy_ratio,
        "order_quantity_to_top_sell_ratio": order_quantity_to_top_sell_ratio,
        "order_quantity_to_total_depth_ratio": order_quantity_to_total_depth_ratio,
        "estimated_slippage_percent": estimated_slippage_percent,
        "depth_supported_quantity": depth_supported_quantity,
        "spread_change_percent": spread_change_percent,
    }


def compute_sector_relative_fields(flat: Dict[str, Any], base_field: str) -> Dict[str, float]:
    value = flat.get(base_field)
    sector_high = flat.get(f"{base_field}_sector_high")
    sector_low = flat.get(f"{base_field}_sector_low")
    result: Dict[str, float] = {}
    if value is not None and sector_high is not None:
        result[f"{base_field}_distance_from_sector_high_percent"] = _pct_change(value, sector_high) or 0.0
    if value is not None and sector_low is not None:
        result[f"{base_field}_distance_from_sector_low_percent"] = _pct_change(value, sector_low) or 0.0
    sector_position = _position_in_range(value, sector_low, sector_high)
    if sector_position is not None:
        result[f"{base_field}_sector_position_percent"] = sector_position
    return result


def sector_position_percent(flat: Dict[str, Any], base_field: str) -> Optional[float]:
    return compute_sector_relative_fields(flat, base_field).get(f"{base_field}_sector_position_percent")


def enrich_flat_snapshot(
    flat: Dict[str, Any],
    *,
    position_state: Optional[Dict[str, Any]] = None,
    order_qty: int = 0,
) -> Dict[str, Any]:
    merged = dict(flat)
    merged.update(compute_market_position_fields(merged))
    if position_state:
        merged.update(compute_position_performance_fields(merged, position_state, qty=order_qty))
    merged.update(compute_volatility_risk_fields(merged))
    merged.update(compute_liquidity_fields(merged, order_qty=order_qty))
    for key in list(merged.keys()):
        if key.startswith(("fundamental_", "technical_", "alpha_", "beta_", "sharpe_", "daily_", "volatility_", "one_year_")):
            if key.endswith("_sector_high") or key.endswith("_sector_low"):
                continue
            if isinstance(merged.get(key), (int, float)):
                merged.update(compute_sector_relative_fields(merged, key))
    return merged
