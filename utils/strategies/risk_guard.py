from __future__ import annotations

from utils.strategies.helpers import is_fresh_trade, is_market_depth_available
from utils.strategies.types import AccountState, MarketSnapshot, OrderContext, RiskDecision


DEFAULT_RISK = {
    "max_capital_per_stock_pct": 10.0,
    "max_risk_per_trade_pct": 2.0,
    "max_trades_per_day": 5,
    "max_daily_loss_pct": 5.0,
    "max_consecutive_losses": 2,
    "order_timeout_minutes": 3,
}


def can_place_order(
    *,
    context: OrderContext,
    snapshot: MarketSnapshot,
    account: AccountState,
    price: float,
    qty: int,
    requires_depth: bool = False,
    strategy_expired: bool = False,
) -> RiskDecision:
    if strategy_expired:
        return RiskDecision(False, "STRATEGY_EXPIRED", "Strategy expired")

    if qty <= 0:
        return RiskDecision(False, "INVALID_QTY", "Quantity must be greater than zero")

    if price <= 0:
        return RiskDecision(False, "INVALID_PRICE", "Price must be greater than zero")

    if context.config.require_fresh_trade and not is_fresh_trade(snapshot):
        return RiskDecision(False, "STALE_TRADE_DATA", "Last traded data is stale")

    if requires_depth and not is_market_depth_available(snapshot):
        return RiskDecision(False, "DEPTH_UNAVAILABLE", "Market depth required but unavailable")

    if account.active_orders_same_symbol_side > 0:
        return RiskDecision(False, "DUPLICATE_ACTIVE_ORDER", "Active order already exists for symbol and side")

    if account.trades_today >= DEFAULT_RISK["max_trades_per_day"]:
        return RiskDecision(False, "MAX_TRADES_PER_DAY", "Max trades per day exceeded")

    if account.daily_loss_pct >= DEFAULT_RISK["max_daily_loss_pct"]:
        return RiskDecision(False, "MAX_DAILY_LOSS", "Max daily loss limit hit")

    if account.consecutive_losses >= DEFAULT_RISK["max_consecutive_losses"]:
        return RiskDecision(False, "MAX_CONSECUTIVE_LOSSES", "Consecutive loss limit hit")

    if account.order_failures >= 3:
        return RiskDecision(False, "ORDER_FAILURE_LIMIT", "Order placement failed multiple times")

    side = context.side.lower()
    if side == "sell":
        holding = account.holding_qty if account.holding_qty is not None else context.remaining_qty
        if holding is not None and qty > holding:
            return RiskDecision(False, "INSUFFICIENT_HOLDING", "Insufficient holding quantity")
    elif side == "buy":
        if account.available_balance is not None and price * qty > account.available_balance:
            return RiskDecision(False, "INSUFFICIENT_BALANCE", "Insufficient balance for order")

    return RiskDecision(True, "RISK_OK", "Risk guard passed")
