from __future__ import annotations

from typing import Any, Dict, Optional

from utils.strategy_builder.strategy_models import PortfolioLimits


def portfolio_allows_new_buy(
    limits: Optional[PortfolioLimits],
    portfolio_state: Dict[str, Any],
    *,
    proposed_amount: float = 0,
) -> tuple[bool, str]:
    if not limits:
        return True, ""
    state = dict(portfolio_state or {})
    if state.get("pause_new_buys"):
        return False, "Portfolio kill switch: new buys paused."
    max_daily = limits.max_total_buy_amount
    if max_daily is not None:
        spent = float(state.get("daily_buy_amount") or 0)
        if spent + proposed_amount > float(max_daily):
            return False, f"Daily buy amount limit exceeded ({max_daily})."
    max_orders = getattr(limits, "max_daily_orders", None) or getattr(limits, "max_open_orders", None)
    if max_orders is not None and int(state.get("daily_order_count") or 0) >= int(max_orders):
        return False, f"Daily order limit reached ({max_orders})."
    max_loss_pct = getattr(limits, "max_daily_loss_pct", None)
    if max_loss_pct is not None:
        daily_loss = float(state.get("portfolio_daily_loss_percent") or 0)
        if daily_loss <= -abs(float(max_loss_pct)):
            return False, f"Daily loss limit reached ({max_loss_pct}%)."
    return True, ""
