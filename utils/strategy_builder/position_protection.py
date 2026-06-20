from __future__ import annotations

from datetime import datetime, timezone

from typing import Any, Dict, Optional

from utils.strategy_builder.strategy_models import PositionProtectionConfig


def compute_protective_fields(
    position_state: Dict[str, Any],
    ltp: Optional[float],
    protection: Optional[PositionProtectionConfig],
) -> Dict[str, Any]:
    """Derive stop-loss fields exposed to rule expressions."""
    state = dict(position_state or {})
    fixed_stop = state.get("fixed_stop_loss_price")
    trailing_pct = None
    if protection:
        if protection.fixed_stop_loss_price is not None:
            fixed_stop = protection.fixed_stop_loss_price
        trailing_pct = protection.trailing_stop_pct

    entry_price = state.get("entry_price")
    highest = state.get("highest_price_since_entry")
    if ltp is not None:
        if entry_price is not None:
            highest = max(float(highest or entry_price), float(ltp))
        elif highest is not None:
            highest = max(float(highest), float(ltp))

    current_trailing_stop = state.get("current_trailing_stop")
    if highest is not None and trailing_pct is not None:
        candidate = float(highest) * (1.0 - float(trailing_pct) / 100.0)
        if current_trailing_stop is None:
            current_trailing_stop = candidate
        else:
            current_trailing_stop = max(float(current_trailing_stop), candidate)

    effective_stop = None
    candidates = [value for value in (fixed_stop, current_trailing_stop) if value is not None]
    if candidates:
        effective_stop = max(float(value) for value in candidates)

    return {
        "entry_price": entry_price,
        "highest_price_since_entry": highest,
        "fixed_stop_loss_price": fixed_stop,
        "current_trailing_stop": current_trailing_stop,
        "effective_stop_price": effective_stop,
    }


def seed_position_after_buy(
    position_state: Dict[str, Any],
    *,
    entry_price: float,
    protection: Optional[PositionProtectionConfig],
) -> Dict[str, Any]:
    state = dict(position_state or {})
    state["entry_price"] = float(entry_price)
    state["highest_price_since_entry"] = float(entry_price)
    state["entry_at"] = datetime.now(timezone.utc).isoformat()
    state["holding_scan_count"] = 0
    if protection and protection.fixed_stop_loss_price is not None:
        state["fixed_stop_loss_price"] = float(protection.fixed_stop_loss_price)
    if protection and protection.trailing_stop_pct is not None:
        state["current_trailing_stop"] = float(entry_price) * (1.0 - float(protection.trailing_stop_pct) / 100.0)
    return state
