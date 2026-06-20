from __future__ import annotations

from typing import Any, Dict, Optional

from utils.strategies.types import MarketSnapshot

from utils.strategy_builder.constants import DEFAULT_RULE_ORDER_QUANTITY


def resolve_order_quantity(
    *,
    order_mode: str,
    order_value: Optional[float],
    ltp: Optional[float],
    holding_qty: int = 0,
    available_cash: Optional[float] = None,
    board_lot: int = 1,
    entry_price: Optional[float] = None,
    stop_loss_price: Optional[float] = None,
    depth_supported_qty: int = 0,
    form_qty: int = 0,
) -> int:
    mode = (order_mode or "quantity").lower()
    price = float(ltp or entry_price or 0)
    value = float(order_value or 0)

    if mode == "quantity":
        if value == -1:
            return max(0, int(form_qty) or DEFAULT_RULE_ORDER_QUANTITY)
        return max(0, int(value or form_qty or DEFAULT_RULE_ORDER_QUANTITY))

    if mode == "amount" and price > 0 and value > 0:
        raw = int(value / price)
        return max(board_lot, (raw // board_lot) * board_lot) if board_lot > 1 else raw

    if mode == "percent_of_holding" and holding_qty > 0:
        pct = value if value > 0 else 100.0
        return max(1, int(holding_qty * pct / 100.0))

    if mode == "percent_of_available_cash" and available_cash and price > 0:
        pct = value if value > 0 else 100.0
        budget = available_cash * pct / 100.0
        raw = int(budget / price)
        return max(board_lot, (raw // board_lot) * board_lot) if board_lot > 1 else raw

    if mode == "target_position_value" and price > 0 and value > 0:
        raw = int(value / price)
        return max(board_lot, (raw // board_lot) * board_lot) if board_lot > 1 else raw

    if mode == "all_available":
        return max(0, int(holding_qty))

    if mode == "sell_up_to" and holding_qty > 0:
        cap = int(value) if value > 0 else holding_qty
        return max(1, min(holding_qty, cap))

    if mode in {"risk_percent", "max_loss_amount"} and entry_price and stop_loss_price:
        risk_per_share = abs(float(entry_price) - float(stop_loss_price))
        if risk_per_share <= 0:
            return max(0, int(form_qty))
        if mode == "risk_percent" and available_cash and value > 0:
            allowed_loss = available_cash * value / 100.0
        elif mode == "max_loss_amount" and value > 0:
            allowed_loss = value
        else:
            return max(0, int(form_qty))
        raw = int(allowed_loss / risk_per_share)
        return max(board_lot, (raw // board_lot) * board_lot) if board_lot > 1 else max(1, raw)

    if mode in {"top_buy_qty", "top_sell_qty", "partial_top_buy", "partial_top_sell"}:
        return 0

    if depth_supported_qty > 0 and mode == "quantity":
        return min(max(0, int(form_qty)), depth_supported_qty)

    return max(0, int(form_qty or 0))
