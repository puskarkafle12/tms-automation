from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable, Dict, Optional, Tuple

from utils.strategies.helpers import (
    get_buy_pressure,
    has_enough_scans,
    is_falling,
    is_market_depth_available,
    is_rising,
    is_volume_increasing,
    range_position,
)
from utils.strategies.scoring import calculate_buy_score, score_decision
from utils.strategies.types import MarketSnapshot, OrderContext, ScannerMemory, ScriptDetails, StrategyDecision


def _track(status: str) -> StrategyDecision:
    return StrategyDecision("TRACK", "TRACKING", f"Monitoring: {status}", tracking_status=status)


def _execute(price: float, reason_code: str, reason: str, *, qty: Optional[int] = None, source: str = "LTP", leg_id: Optional[str] = None, score: Optional[float] = None) -> StrategyDecision:
    return StrategyDecision("EXECUTE", reason_code, reason, score=score, price=price, qty=qty, source=source, leg_id=leg_id)


def _watch(reason_code: str, reason: str, score: Optional[float] = None) -> StrategyDecision:
    return StrategyDecision("WATCH", reason_code, reason, score=score, tracking_status="Watching")


def _skip(reason_code: str, reason: str) -> StrategyDecision:
    return StrategyDecision("SKIP", reason_code, reason, tracking_status="Skipped")


def _no_trade(reason_code: str, reason: str, score: Optional[float] = None) -> StrategyDecision:
    return StrategyDecision("NO_TRADE", reason_code, reason, score=score, tracking_status="No trade")


def _sell_execution_price(snapshot: MarketSnapshot, fallback: float) -> Tuple[float, str]:
    if snapshot.top_buy_orders:
        best = max(snapshot.top_buy_orders, key=lambda item: item.price)
        if best.price > 0:
            return best.price, "Top Buy"
    return fallback, "LTP fallback"


def evaluate_fixed_price_buy(ctx: OrderContext, snapshot: MarketSnapshot, memory: ScannerMemory, details: ScriptDetails) -> StrategyDecision:
    target = ctx.target_price
    if snapshot.ltp <= target:
        return _execute(target, "BUY_ALLOWED_FIXED_PRICE", f"Fixed price buy: LTP {snapshot.ltp} <= target {target}")
    return _track("pending")


def evaluate_fixed_price_sell(ctx: OrderContext, snapshot: MarketSnapshot, memory: ScannerMemory, details: ScriptDetails) -> StrategyDecision:
    target = ctx.target_price
    if snapshot.ltp >= target:
        return _execute(target, "SELL_ALLOWED_FIXED_PRICE", f"Fixed price sell: LTP {snapshot.ltp} >= target {target}")
    return _track("pending")


def evaluate_quality_pullback_recovery_buy(ctx: OrderContext, snapshot: MarketSnapshot, memory: ScannerMemory, details: ScriptDetails) -> StrategyDecision:
    if not details.available:
        return _skip("SCRIPT_DETAILS_UNAVAILABLE", "Quality Pullback Recovery Buy requires Nepse Alpha script details")

    score = calculate_buy_score(snapshot, memory, details)
    min_score = ctx.config.min_buy_score
    quality_ok = (
        (details.roe or 0) >= 15
        and (details.yoy_earnings_growth or 0) >= 15
        and (details.pe or 0) > 0
        and (details.pe or 0) <= 35
        and (details.pbv or 0) > 0
        and (details.pbv or 0) <= 6
    )
    technical_ok = (
        details.rsi_14 is not None
        and 35 <= details.rsi_14 <= 60
        and details.mfi_14 is not None
        and 25 <= details.mfi_14 <= 60
        and (details.stochastic_14 or 100) <= 45
        and (details.percent_b or 100) <= 45
        and details.macd_signal == "Bullish"
    )
    live_recovery = (
        snapshot.open is not None
        and snapshot.ltp >= snapshot.open
        and snapshot.prev_close is not None
        and snapshot.ltp >= snapshot.prev_close * 0.995
        and range_position(snapshot) >= 0.55
        and memory.previous_ltp is not None
        and snapshot.ltp > memory.previous_ltp
        and (not ctx.config.require_volume_increase or is_volume_increasing(snapshot, memory))
    )

    if score < min_score:
        return _no_trade("BUY_REJECTED_SCORE_LOW", f"BUY_REJECTED_SCORE_LOW: score {score:.0f} < required {min_score:.0f}", score=score)
    if is_falling(memory.last_prices, 3):
        return _no_trade("BUY_REJECTED_PRICE_FALLING", "BUY_REJECTED_PRICE_FALLING: last 3 scans are falling", score=score)
    if quality_ok and technical_ok and live_recovery:
        return _execute(snapshot.ltp, "BUY_ALLOWED_QUALITY_RECOVERY", f"BUY_ALLOWED_QUALITY_RECOVERY: score {score:.0f}, RSI {details.rsi_14}, MACD {details.macd_signal}, LTP recovered above open", score=score)
    if score_decision(score) == "WATCH_ONLY":
        return _watch("BUY_WATCH_QUALITY_RECOVERY", f"WATCH_ONLY: score {score:.0f}, waiting for recovery confirmation", score=score)
    return _no_trade("BUY_NO_TRADE_QUALITY_RECOVERY", "Quality recovery conditions not met", score=score)


def evaluate_confirmed_breakout_buy(ctx: OrderContext, snapshot: MarketSnapshot, memory: ScannerMemory, details: ScriptDetails) -> StrategyDecision:
    target = ctx.target_price
    breakout = (
        snapshot.high is not None
        and snapshot.ltp > snapshot.high
        and snapshot.open is not None
        and snapshot.ltp > snapshot.open
        and snapshot.prev_close is not None
        and snapshot.ltp > snapshot.prev_close
    ) or (target > 0 and snapshot.ltp >= target)

    if snapshot.change_percent is not None and snapshot.change_percent > 6:
        return _no_trade("BUY_REJECTED_CHASING", "NO_TRADE: change percent too high (>6%)")
    if details.rsi_14 is not None and details.rsi_14 >= 70:
        return _no_trade("BUY_REJECTED_OVERBOUGHT", "NO_TRADE: RSI overbought")

    recent_confirmed = has_enough_scans(memory, 3) and is_rising(memory.last_prices, 3)
    volume_confirmed = is_volume_increasing(snapshot, memory)

    if breakout and recent_confirmed and volume_confirmed:
        return _execute(snapshot.ltp, "BUY_ALLOWED_BREAKOUT", "BUY_ALLOWED: confirmed breakout with rising scans and volume")
    return _watch("BUY_WATCH_BREAKOUT", "Waiting for confirmed breakout")


def evaluate_smart_pullback_buy(ctx: OrderContext, snapshot: MarketSnapshot, memory: ScannerMemory, details: ScriptDetails) -> StrategyDecision:
    target = ctx.target_price
    if target > 0 and snapshot.ltp <= target:
        return _execute(target, "BUY_ALLOWED_SMART_PULLBACK", f"Smart Pullback Buy: LTP {snapshot.ltp} <= target {target}")

    if snapshot.high and snapshot.high > 0:
        pullback_pct = ((snapshot.high - snapshot.ltp) / snapshot.high) * 100.0
    else:
        pullback_pct = 0.0

    near_zone = 1.5 <= pullback_pct <= 4.0
    recovery = has_enough_scans(memory, 3) and memory.last_prices[-1] > memory.last_prices[-2] and memory.last_prices[-2] >= memory.last_prices[-3]
    not_weak = snapshot.low is None or snapshot.ltp >= snapshot.low * 1.01
    if details.rsi_14 is not None:
        not_weak = not_weak and details.rsi_14 >= 35

    if is_falling(memory.last_prices, 3):
        return _no_trade("BUY_REJECTED_PRICE_FALLING", "BUY_REJECTED_PRICE_FALLING: price still falling")
    if near_zone and recovery and not_weak:
        return _execute(snapshot.ltp, "BUY_ALLOWED_SMART_PULLBACK", "BUY_ALLOWED: pullback recovery detected")
    return _watch("BUY_WATCH_SMART_PULLBACK", "Waiting for pullback recovery")


def evaluate_mean_reversion_bounce_buy(ctx: OrderContext, snapshot: MarketSnapshot, memory: ScannerMemory, details: ScriptDetails) -> StrategyDecision:
    if not details.available:
        return _skip("SCRIPT_DETAILS_UNAVAILABLE", "Mean Reversion Bounce Buy requires Nepse Alpha script details")

    setup = (
        (details.three_month_price_trend or "").lower().find("mean") >= 0
        and details.rsi_14 is not None
        and 35 <= details.rsi_14 <= 55
        and (details.stochastic_14 or 100) <= 35
        and (details.percent_b or 100) <= 40
    )
    bounce = (
        memory.previous_ltp is not None
        and snapshot.ltp > memory.previous_ltp
        and snapshot.open is not None
        and snapshot.ltp >= snapshot.open * 0.995
        and is_volume_increasing(snapshot, memory)
    )
    risk_ok = (details.beta_3_month is None or details.beta_3_month <= 1.3) and (
        details.sharpe_annualized is None or details.sharpe_annualized > -1
    )
    score = calculate_buy_score(snapshot, memory, details)

    if setup and bounce and risk_ok and score >= ctx.config.min_buy_score:
        return _execute(snapshot.ltp, "BUY_ALLOWED_MEAN_REVERSION", f"BUY_ALLOWED: mean reversion bounce, score {score:.0f}", score=score)
    if setup and not bounce:
        return _watch("BUY_WATCH_MEAN_REVERSION", "WATCH: mean reversion setup without bounce confirmation", score=score)
    return _no_trade("BUY_NO_TRADE_MEAN_REVERSION", "Mean reversion conditions not met", score=score)


def evaluate_order_book_strength_buy(ctx: OrderContext, snapshot: MarketSnapshot, memory: ScannerMemory, details: ScriptDetails) -> StrategyDecision:
    if not is_market_depth_available(snapshot):
        return _skip("BUY_SKIPPED_DEPTH_UNAVAILABLE", "BUY_SKIPPED_DEPTH_UNAVAILABLE: Order Book Strength Buy requires market depth")

    buy_pressure = get_buy_pressure(snapshot)
    if buy_pressure is None:
        return _skip("BUY_SKIPPED_DEPTH_UNAVAILABLE", "BUY_SKIPPED_DEPTH_UNAVAILABLE: buy pressure unavailable")

    price_ok = (
        snapshot.open is not None
        and snapshot.ltp >= snapshot.open
        and memory.previous_ltp is not None
        and snapshot.ltp > memory.previous_ltp
    )
    if buy_pressure >= 0.60 and price_ok:
        return _execute(snapshot.ltp, "BUY_ALLOWED_ORDER_BOOK", f"BUY_ALLOWED: buy pressure {buy_pressure:.0%}")
    return _watch("BUY_WATCH_ORDER_BOOK", f"WATCH: buy pressure {buy_pressure:.0%}")


def evaluate_capital_protection_sell(ctx: OrderContext, snapshot: MarketSnapshot, memory: ScannerMemory, details: ScriptDetails) -> StrategyDecision:
    entry = ctx.entry_price()
    if entry is None or entry <= 0:
        entry = ctx.target_price

    stop_pct = ctx.config.stop_loss_pct
    break_even_pct = ctx.config.break_even_trigger_pct
    initial_stop = ctx.stop_loss_price if ctx.stop_loss_price else entry * (1 - stop_pct / 100.0)
    break_even_trigger = entry * (1 + break_even_pct / 100.0)

    stop_price = entry if ctx.config.break_even_armed or (ctx.target_reached and snapshot.ltp >= break_even_trigger) else initial_stop
    mutate: Dict[str, object] = {}
    if snapshot.ltp >= break_even_trigger:
        ctx.config.break_even_armed = True
        stop_price = entry
        mutate["break_even_armed"] = True

    if ctx.legacy_alias == "Stop Limit Sell" and ctx.stop_loss_price and snapshot.ltp <= ctx.stop_loss_price:
        limit = ctx.stop_limit_price or ctx.target_price
        if limit > 0:
            return _execute(limit, "SELL_TRIGGERED_STOP_LIMIT", "SELL: stop-limit trigger reached", source="Stop limit")

    if ctx.legacy_alias == "Fast Stop Loss" and ctx.stop_loss_price and snapshot.ltp <= ctx.stop_loss_price:
        count = ctx.below_stop_loss_check_count + 1
        fast_fall = snapshot.ltp <= ctx.stop_loss_price * 0.99
        sharp_drop = ctx.last_checked_ltp is not None and snapshot.ltp <= ctx.last_checked_ltp * 0.99
        mutate = {"below_stop_loss_check_count": count}
        if fast_fall or sharp_drop or count >= 2:
            price, source = _sell_execution_price(snapshot, snapshot.ltp)
            return StrategyDecision("EXECUTE", "SELL_TRIGGERED_CAPITAL_PROTECTION", "SELL_TRIGGERED_CAPITAL_PROTECTION: fast stop-loss triggered", price=price, source=source, mutate=mutate)
        return StrategyDecision("TRACK", "SELL_TRACK_STOP_LOSS", "Stop-loss triggered, confirming", tracking_status="Stop-loss triggered", mutate=mutate)

    if snapshot.ltp <= stop_price:
        price, source = _sell_execution_price(snapshot, snapshot.ltp)
        return StrategyDecision("EXECUTE", "SELL_TRIGGERED_CAPITAL_PROTECTION", f"SELL_TRIGGERED_CAPITAL_PROTECTION: LTP {snapshot.ltp:.2f} <= stop {stop_price:.2f}", price=price, source=source, mutate=mutate)

    mutate["below_stop_loss_check_count"] = 0
    return StrategyDecision("TRACK", "SELL_TRACK_CAPITAL_PROTECTION", "Capital protection monitoring", tracking_status="Monitoring", mutate=mutate)


def evaluate_profit_ladder_sell(ctx: OrderContext, snapshot: MarketSnapshot, memory: ScannerMemory, details: ScriptDetails) -> StrategyDecision:
    entry = ctx.average_buy_price or ctx.target_price
    if entry <= 0:
        return _track("Failed")

    target1 = entry * (1 + ctx.config.target1_pct / 100.0)
    target2 = entry * (1 + ctx.config.target2_pct / 100.0)
    if ctx.profit_target_price:
        target1 = ctx.profit_target_price
    if ctx.book_profit_price:
        target1 = ctx.book_profit_price

    legs = ctx.partial_legs
    if legs:
        executed = set(ctx.executed_legs or [])
        for index, leg in enumerate(legs):
            leg_id = str(leg.get("id") or index)
            target = float(leg.get("targetPrice") or 0)
            percent = float(leg.get("sellPercent") or 0)
            if leg_id not in executed and target > 0 and percent > 0 and snapshot.ltp >= target:
                leg_qty = max(1, int(ctx.qty * percent / 100.0))
                price, source = _sell_execution_price(snapshot, snapshot.ltp)
                return _execute(price, "SELL_TRIGGERED_PROFIT_LADDER", f"SELL: partial profit leg {leg_id} reached", qty=min(leg_qty, ctx.remaining_qty), source=source, leg_id=leg_id)
    else:
        if not ctx.config.sold_target1 and snapshot.ltp >= target1:
            sell_qty = max(1, int(ctx.qty * ctx.config.target1_sell_pct / 100.0))
            price, source = _sell_execution_price(snapshot, snapshot.ltp)
            return StrategyDecision(
                "EXECUTE",
                "SELL_TRIGGERED_PROFIT_LADDER",
                f"SELL: target1 hit at {target1:.2f}",
                price=price,
                qty=min(sell_qty, ctx.remaining_qty),
                source=source,
                mutate={"sold_target1": True},
            )
        if not ctx.config.sold_target2 and snapshot.ltp >= target2:
            sell_qty = max(1, int(ctx.qty * ctx.config.target2_sell_pct / 100.0))
            price, source = _sell_execution_price(snapshot, snapshot.ltp)
            return StrategyDecision(
                "EXECUTE",
                "SELL_TRIGGERED_PROFIT_LADDER",
                f"SELL: target2 hit at {target2:.2f}",
                price=price,
                qty=min(sell_qty, ctx.remaining_qty),
                source=source,
                mutate={"sold_target2": True},
            )

    if ctx.legacy_alias in {"Smart Profit Booking", "Book Profit + Stop Loss"}:
        return _evaluate_legacy_smart_profit(ctx, snapshot, memory, details)

    high = max(ctx.highest_tracked_price or snapshot.ltp, snapshot.ltp)
    return StrategyDecision("TRACK", "SELL_TRACK_PROFIT_LADDER", "Profit ladder monitoring", tracking_status="Tracking highest price", mutate={"highest_tracked_price": high})


def _evaluate_legacy_smart_profit(ctx: OrderContext, snapshot: MarketSnapshot, memory: ScannerMemory, details: ScriptDetails) -> StrategyDecision:
    if ctx.legacy_alias == "Book Profit + Stop Loss" and ctx.stop_loss_price and snapshot.ltp <= ctx.stop_loss_price:
        price, source = _sell_execution_price(snapshot, snapshot.ltp)
        return _execute(price, "SELL_TRIGGERED_PROFIT_LADDER", "SELL: OCO stop-loss side triggered", source=source)

    target = ctx.book_profit_price if ctx.legacy_alias == "Book Profit + Stop Loss" else ctx.profit_target_price
    if not ctx.target_reached:
        if target and snapshot.ltp >= target:
            return StrategyDecision(
                "TRACK",
                "SELL_TRACK_PROFIT_LADDER",
                "Profit target reached",
                tracking_status="Profit target reached",
                mutate={"target_reached": True, "target_reached_at": datetime.utcnow(), "highest_tracked_price": snapshot.ltp},
            )
        return _track("Profit target waiting")

    high = max(ctx.highest_tracked_price or snapshot.ltp, snapshot.ltp)
    drop = ((high - snapshot.ltp) / high) * 100.0 if high else 0.0
    trailing = ctx.trailing_drop_percent
    if drop >= trailing and drop > ctx.stable_band_percent:
        price, source = _sell_execution_price(snapshot, snapshot.ltp)
        return _execute(price, "SELL_TRIGGERED_PROFIT_LADDER", "SELL: profit trailing drop detected", source=source)
    return StrategyDecision("TRACK", "SELL_TRACK_PROFIT_LADDER", "Tracking highest price", tracking_status="Tracking highest price", mutate={"highest_tracked_price": high})


def evaluate_trailing_runner_sell(ctx: OrderContext, snapshot: MarketSnapshot, memory: ScannerMemory, details: ScriptDetails) -> StrategyDecision:
    if ctx.activation_price and snapshot.ltp < ctx.activation_price:
        return _track("Waiting activation")

    high = max(ctx.highest_tracked_price or snapshot.ltp, snapshot.ltp)
    trailing_pct = ctx.trailing_drop_percent or ctx.config.trailing_stop_pct
    trailing_stop = high * (1 - trailing_pct / 100.0)

    if ctx.remaining_qty > 0 and snapshot.ltp <= trailing_stop:
        price, source = _sell_execution_price(snapshot, snapshot.ltp)
        return _execute(price, "SELL_TRIGGERED_TRAILING_RUNNER", f"SELL_TRIGGERED_TRAILING_RUNNER: LTP {snapshot.ltp:.2f} <= trailing stop {trailing_stop:.2f}", qty=ctx.remaining_qty, source=source)

    return StrategyDecision("TRACK", "SELL_TRACK_TRAILING_RUNNER", "Trailing runner monitoring", tracking_status="Tracking highest price", mutate={"highest_tracked_price": high})


def evaluate_technical_weakness_sell(ctx: OrderContext, snapshot: MarketSnapshot, memory: ScannerMemory, details: ScriptDetails) -> StrategyDecision:
    if not details.available:
        return _skip("SCRIPT_DETAILS_UNAVAILABLE", "Technical Weakness Sell requires Nepse Alpha script details")

    technical_weak = (
        details.macd_signal != "Bullish"
        or (details.rsi_14 is not None and details.rsi_14 < 35)
        or (details.mfi_14 is not None and details.mfi_14 < 30)
        or details.volume_trend == "Down"
    )
    price_weak = (
        snapshot.open is not None
        and snapshot.ltp < snapshot.open
        and snapshot.prev_close is not None
        and snapshot.ltp < snapshot.prev_close
        and has_enough_scans(memory, 3)
        and is_falling(memory.last_prices, 3)
    )
    if technical_weak and price_weak:
        price, source = _sell_execution_price(snapshot, snapshot.ltp)
        return _execute(price, "SELL_TRIGGERED_TECHNICAL_WEAKNESS", "SELL: technical and price weakness confirmed", source=source)
    return _watch("SELL_WATCH_TECHNICAL_WEAKNESS", "Watching for technical weakness")


def evaluate_emergency_exit(ctx: OrderContext, snapshot: MarketSnapshot, memory: ScannerMemory, details: ScriptDetails) -> StrategyDecision:
    if not ctx.emergency_execution:
        return _no_trade("EMERGENCY_NOT_CONFIRMED", "Emergency exit requires confirmation")

    if is_market_depth_available(snapshot) and snapshot.top_buy_orders:
        buyers = sorted(snapshot.top_buy_orders, key=lambda item: item.price, reverse=True)
        best = buyers[0]
        sell_qty = min(ctx.remaining_qty, int(best.quantity)) if best.quantity else ctx.remaining_qty
        if ctx.config.allow_split_emergency_exit and sell_qty < ctx.remaining_qty:
            return _execute(best.price, "SELL_TRIGGERED_EMERGENCY_EXIT", f"Emergency exit: sell {sell_qty} at top buyer {best.price}", qty=sell_qty, source="Top Buy")
        return _execute(best.price, "SELL_TRIGGERED_EMERGENCY_EXIT", f"Emergency exit: sell to best buyer at {best.price}", qty=ctx.remaining_qty or sell_qty, source="Top Buy")

    return _execute(snapshot.ltp, "SELL_TRIGGERED_EMERGENCY_EXIT", "Emergency exit: LTP fallback (depth unavailable)", source="LTP fallback")


def evaluate_time_based_buy(ctx: OrderContext, snapshot: MarketSnapshot, memory: ScannerMemory, details: ScriptDetails, wrapped_handler: Callable) -> StrategyDecision:
    now = datetime.utcnow()
    if ctx.expiry_time and now >= ctx.expiry_time:
        return StrategyDecision("EXPIRE", "STRATEGY_EXPIRED", "Buy strategy expired", expired=True, cancelled_reason="Buy strategy expired", tracking_status="Expired")

    wrapped_name = ctx.config.wrapped_strategy_type or "Quality Pullback Recovery Buy"
    wrapped_ctx = OrderContext(**{**ctx.__dict__, "canonical_strategy": wrapped_name, "strategy_type": wrapped_name})
    return wrapped_handler(wrapped_ctx, snapshot, memory, details)


def evaluate_time_based_exit(ctx: OrderContext, snapshot: MarketSnapshot, memory: ScannerMemory, details: ScriptDetails) -> StrategyDecision:
    now = datetime.utcnow()
    if ctx.expiry_time and now >= ctx.expiry_time:
        action = ctx.expiry_action or "Cancel strategy"
        if action == "Sell using Top Buy":
            return evaluate_emergency_exit(ctx, snapshot, memory, details)
        return StrategyDecision("EXPIRE", "STRATEGY_EXPIRED", "Strategy expired", expired=True, cancelled_reason="Strategy expired", tracking_status="Expired")
    return _track("Monitoring")


HANDLERS: Dict[str, Callable] = {
    "Fixed Price Buy": evaluate_fixed_price_buy,
    "Fixed Price Sell": evaluate_fixed_price_sell,
    "Quality Pullback Recovery Buy": evaluate_quality_pullback_recovery_buy,
    "Confirmed Breakout Buy": evaluate_confirmed_breakout_buy,
    "Smart Pullback Buy": evaluate_smart_pullback_buy,
    "Mean Reversion Bounce Buy": evaluate_mean_reversion_bounce_buy,
    "Order Book Strength Buy": evaluate_order_book_strength_buy,
    "Capital Protection Sell": evaluate_capital_protection_sell,
    "Profit Ladder Sell": evaluate_profit_ladder_sell,
    "Trailing Runner Sell": evaluate_trailing_runner_sell,
    "Technical Weakness Sell": evaluate_technical_weakness_sell,
    "Emergency Exit by Top Buyer": evaluate_emergency_exit,
}
