from __future__ import annotations

from typing import Dict, Set

BUY_STRATEGIES: Set[str] = {
    "Fixed Price Buy",
    "Quality Pullback Recovery Buy",
    "Confirmed Breakout Buy",
    "Smart Pullback Buy",
    "Mean Reversion Bounce Buy",
    "Order Book Strength Buy",
    "Time-Based Buy",
}

SELL_STRATEGIES: Set[str] = {
    "Fixed Price Sell",
    "Capital Protection Sell",
    "Profit Ladder Sell",
    "Trailing Runner Sell",
    "Technical Weakness Sell",
    "Emergency Exit by Top Buyer",
    "Time-Based Exit",
}

CANONICAL_STRATEGIES: Set[str] = BUY_STRATEGIES | SELL_STRATEGIES

STRATEGY_ALIASES: Dict[str, str] = {
    "Fixed Price": "Fixed Price Buy",
    "Buy Below Price": "Smart Pullback Buy",
    "Dip Buy": "Smart Pullback Buy",
    "Breakout Buy": "Confirmed Breakout Buy",
    "Fast Stop Loss": "Capital Protection Sell",
    "Stop Limit Sell": "Capital Protection Sell",
    "Break-Even Protection": "Capital Protection Sell",
    "Smart Profit Booking": "Profit Ladder Sell",
    "Book Profit + Stop Loss": "Profit Ladder Sell",
    "Partial Profit Booking": "Profit Ladder Sell",
    "Trailing Stop Loss": "Trailing Runner Sell",
    "Emergency Exit": "Emergency Exit by Top Buyer",
}


def canonical_strategy_name(strategy_type: str, side: str = "buy") -> str:
    raw = (strategy_type or "Fixed Price").strip()
    if raw == "Fixed Price":
        return "Fixed Price Buy" if side.lower() == "buy" else "Fixed Price Sell"
    return STRATEGY_ALIASES.get(raw, raw)


def is_buy_strategy(name: str) -> bool:
    return canonical_strategy_name(name, "buy") in BUY_STRATEGIES
