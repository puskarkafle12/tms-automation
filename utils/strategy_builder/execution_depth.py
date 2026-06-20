from __future__ import annotations

from typing import Optional, Tuple

from utils.strategies.execution_price import resolve_sell_limit_price
from utils.strategies.helpers import is_market_depth_available
from utils.strategies.types import MarketSnapshot

from utils.strategy_builder.constants import DEFAULT_RULE_ORDER_QUANTITY


def resolve_buy_limit_price(
    snapshot: MarketSnapshot,
    trigger_ltp: float,
    *,
    max_slippage_percent: float = 1.0,
) -> Tuple[float, str]:
    """Pick a buy limit from top sell (best ask), clamped to slippage above LTP."""
    ltp = float(trigger_ltp or snapshot.ltp or 0)
    top_sell = 0.0
    source = "LTP fallback"
    if snapshot.top_sell_orders:
        candidates = [level for level in snapshot.top_sell_orders if float(level.price or 0) > 0]
        if candidates:
            best = min(candidates, key=lambda item: float(item.price))
            top_sell = float(best.price)
            source = "Top Sell"

    raw_price = top_sell if top_sell > 0 else ltp
    slippage = max(0.0, float(max_slippage_percent or 0))
    max_price = ltp * (1 + slippage / 100.0) if ltp > 0 else raw_price
    price = min(raw_price, max_price) if top_sell > 0 and ltp > 0 else raw_price
    if ltp > 0 and price < ltp:
        price = ltp
    return price, source


def resolve_rule_execution_price(
    snapshot: MarketSnapshot,
    side: str,
    price_source: Optional[str],
    *,
    max_slippage_percent: Optional[float] = None,
) -> Tuple[float, str]:
    source = (price_source or "ltp").lower().replace(" ", "_")
    ltp = float(snapshot.ltp or 0)
    slippage = float(max_slippage_percent or 1.0)

    if source in {"ltp"}:
        return ltp, "LTP"

    if source in {"best_bid", "top_buy"}:
        if side.upper() == "SELL":
            return resolve_sell_limit_price(
                snapshot,
                ltp,
                max_slippage_percent=slippage,
            )
        if snapshot.top_buy_orders:
            best = max(snapshot.top_buy_orders, key=lambda item: float(item.price or 0))
            if best.price > 0:
                return float(best.price), "Best Bid"
        return ltp, "LTP fallback"

    if source in {"best_ask", "top_sell"}:
        if side.upper() == "BUY":
            return resolve_buy_limit_price(snapshot, ltp, max_slippage_percent=slippage)
        if snapshot.top_sell_orders:
            candidates = [level for level in snapshot.top_sell_orders if float(level.price or 0) > 0]
            if candidates:
                best = min(candidates, key=lambda item: float(item.price))
                return float(best.price), "Best Ask"
        return ltp, "LTP fallback"

    return ltp, "LTP"


def _top_buy_qty(snapshot: MarketSnapshot, flat: dict) -> int:
    if snapshot.top_buy_orders:
        return int(max(snapshot.top_buy_orders, key=lambda item: float(item.price or 0)).quantity or 0)
    return int(float(flat.get("top_buy_quantity") or 0))


def _top_sell_qty(snapshot: MarketSnapshot, flat: dict) -> int:
    if snapshot.top_sell_orders:
        candidates = [level for level in snapshot.top_sell_orders if float(level.price or 0) > 0]
        if candidates:
            return int(min(candidates, key=lambda item: float(item.price)).quantity or 0)
    return int(float(flat.get("top_sell_quantity") or 0))


def resolve_depth_order_quantity(
    *,
    order_mode: str,
    order_value: Optional[float],
    snapshot: MarketSnapshot,
    flat: dict,
    side: str,
    form_qty: int,
    holding_qty: int = 0,
) -> Tuple[int, Optional[str]]:
    """Return execution quantity for depth-aware ORDER modes. Second value is partial-fill note."""
    mode = (order_mode or "quantity").lower()
    requested = int(order_value or form_qty or DEFAULT_RULE_ORDER_QUANTITY)
    top_buy = _top_buy_qty(snapshot, flat)
    top_sell = _top_sell_qty(snapshot, flat)
    side_upper = side.upper()

    if mode == "top_buy_qty":
        if side_upper != "SELL":
            return 0, "TOP_BUY_QTY applies to SELL orders only"
        qty = min(max(0, holding_qty), top_buy) if top_buy > 0 else 0
        return qty, None if qty > 0 else "Top buy quantity is zero"

    if mode == "top_sell_qty":
        if side_upper != "BUY":
            return 0, "TOP_SELL_QTY applies to BUY orders only"
        return top_sell if top_sell > 0 else 0, None if top_sell > 0 else "Top sell quantity is zero"

    if mode == "partial_top_buy":
        if side_upper != "SELL":
            return 0, "PARTIAL_TOP_BUY applies to SELL orders only"
        if top_buy <= 0:
            return 0, "Top buy depth unavailable"
        cap = requested if order_value is not None else max(requested, int(form_qty or 0))
        qty = min(max(0, holding_qty), top_buy, cap)
        note = None
        if qty < cap:
            note = f"Partial sell {qty} of {cap} (top buy qty {top_buy})"
        return qty, note

    if mode == "partial_top_sell":
        if side_upper != "BUY":
            return 0, "PARTIAL_TOP_SELL applies to BUY orders only"
        if top_sell <= 0:
            return 0, "Top sell depth unavailable"
        cap = requested if order_value is not None else max(requested, int(form_qty or 0))
        qty = min(top_sell, cap)
        note = None
        if qty < cap:
            note = f"Partial buy {qty} of {cap} (top sell qty {top_sell})"
        return qty, note

    return 0, None


def depth_quantity_sufficient(
    *,
    side: str,
    requested_qty: int,
    snapshot: MarketSnapshot,
    flat: dict,
) -> Tuple[bool, str]:
    """Check whether top-of-book quantity can fully fill the requested size."""
    if not is_market_depth_available(snapshot):
        return False, "Market depth unavailable"
    side_upper = side.upper()
    if side_upper == "SELL":
        top_qty = _top_buy_qty(snapshot, flat)
        label = "top buy"
    else:
        top_qty = _top_sell_qty(snapshot, flat)
        label = "top sell"
    if top_qty <= 0:
        return False, f"No {label} quantity"
    if requested_qty <= top_qty:
        return True, f"{label} qty {top_qty} covers order {requested_qty}"
    return False, f"{label} qty {top_qty} is less than order {requested_qty}"
