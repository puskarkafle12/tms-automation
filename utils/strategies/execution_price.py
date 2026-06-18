from __future__ import annotations

from typing import Optional, Tuple

from utils.strategies.types import MarketSnapshot


def resolve_sell_limit_price(
    snapshot: MarketSnapshot,
    trigger_ltp: float,
    *,
    max_slippage_percent: float = 1.0,
    reference_price: Optional[float] = None,
) -> Tuple[float, str]:
    """Pick a realistic sell limit from top buy, clamped to live LTP and slippage."""
    ltp = float(trigger_ltp or snapshot.ltp or 0)
    if ltp <= 0:
        ltp = float(snapshot.ltp or 0)

    top_buy = 0.0
    source = "LTP fallback"
    if snapshot.top_buy_orders:
        best = max(snapshot.top_buy_orders, key=lambda item: item.price)
        if best.price > 0:
            top_buy = float(best.price)
            source = "Top Buy"

    raw_price = top_buy if top_buy > 0 else ltp
    slippage = max(0.0, float(max_slippage_percent or 0))
    max_price = ltp * (1 + slippage / 100.0) if ltp > 0 else raw_price
    price = min(raw_price, max_price) if ltp > 0 else raw_price

    if reference_price is not None and float(reference_price) > 0:
        min_price = float(reference_price) * (1 - slippage / 100.0)
        price = max(price, min_price)

    if ltp > 0:
        price = min(price, ltp)

    return price, source


def sell_price_exceeds_slippage(
    *,
    requested_price: float,
    execution_price: float,
    max_slippage_percent: float,
) -> bool:
    if requested_price <= 0 or execution_price <= 0:
        return False
    allowed = requested_price * (1 + max(0.0, float(max_slippage_percent or 0)) / 100.0)
    return execution_price > allowed
