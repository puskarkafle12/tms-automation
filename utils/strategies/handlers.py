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


from utils.strategies.execution_price import resolve_sell_limit_price
from utils.strategies.capital_protection import evaluate_capital_protection_core


def _sell_execution_price(
    snapshot: MarketSnapshot,
    fallback: float,
    *,
    max_slippage_percent: float = 1.0,
    reference_price: Optional[float] = None,
) -> Tuple[float, str]:
    return resolve_sell_limit_price(
        snapshot,
        fallback,
        max_slippage_percent=max_slippage_percent,
        reference_price=reference_price,
    )


def _capital_protection_sell_price(
    ctx: OrderContext,
    snapshot: MarketSnapshot,
    *,
    reference_price: float,
) -> Tuple[float, str]:
    return _sell_execution_price(
        snapshot,
        snapshot.ltp,
        max_slippage_percent=ctx.max_allowed_slippage_percent,
        reference_price=reference_price,
    )


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
            price, source = _capital_protection_sell_price(ctx, snapshot, reference_price=ctx.stop_loss_price)
            return StrategyDecision(
                "EXECUTE",
                "SELL_TRIGGERED_CAPITAL_PROTECTION",
                "SELL_TRIGGERED_CAPITAL_PROTECTION: fast stop-loss triggered",
                price=price,
                source=source,
                mutate=mutate,
            )
        return StrategyDecision(
            "TRACK",
            "SELL_TRACK_STOP_LOSS",
            "Stop-loss triggered, confirming",
            tracking_status="Stop-loss triggered",
            mutate=mutate,
        )

    decision = evaluate_capital_protection_core(ctx, snapshot)
    if decision.action != "EXECUTE":
        return decision

    price, source = _capital_protection_sell_price(
        ctx,
        snapshot,
        reference_price=decision.price or snapshot.ltp,
    )
    return StrategyDecision(
        decision.action,
        decision.reason_code,
        decision.reason,
        price=price,
        source=source,
        tracking_status=decision.tracking_status,
        mutate=decision.mutate,
    )


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


def _hold_rule(reason_code: str, reason: str, *, tracking_status: Optional[str] = None) -> StrategyDecision:
    return StrategyDecision(
        "TRACK",
        reason_code,
        reason,
        tracking_status=tracking_status or reason,
    )


def _check_execution_limits(rule, history: "TargetHistory") -> Optional[StrategyDecision]:
    from datetime import datetime, timedelta, timezone

    freq = str(rule.execution.frequency or "once").lower()
    if freq in {"once", "once_per_symbol"} and history.executed:
        return _hold_rule("ALREADY_EXECUTED", "Rule already executed for this symbol")

    max_times = rule.execution.max_times
    if max_times and int(history.execution_count or 0) >= int(max_times):
        return _hold_rule("MAX_EXECUTIONS_REACHED", f"Maximum {max_times} executions reached")

    cooldown = rule.execution.cooldown_minutes
    if cooldown and history.last_executed_at:
        try:
            last = datetime.fromisoformat(str(history.last_executed_at))
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - last < timedelta(minutes=int(cooldown)):
                return _hold_rule("COOLDOWN_ACTIVE", f"Cooldown {cooldown} minutes active")
        except (TypeError, ValueError):
            pass
    return None


def _mark_rule_execution(history: "TargetHistory") -> None:
    from datetime import datetime, timezone

    history.executed = True
    history.execution_count = int(history.execution_count or 0) + 1
    history.last_executed_at = datetime.now(timezone.utc).isoformat()


def evaluate_rule_based_strategy(ctx: OrderContext, snapshot: MarketSnapshot, memory: ScannerMemory, details: ScriptDetails) -> StrategyDecision:
    from dataclasses import replace

    from utils.strategy_builder.derived_fields import enrich_flat_snapshot
    from utils.strategy_builder.execution_depth import (
        depth_quantity_sufficient,
        resolve_depth_order_quantity,
        resolve_rule_execution_price,
    )
    from utils.strategy_builder.execution_sizing import resolve_order_quantity
    from utils.strategy_builder.history_service import (
        deserialize_target_history,
        serialize_target_history,
    )
    from utils.strategy_builder.market_normalizer import build_symbol_snapshot_from_parts
    from utils.strategy_builder.portfolio_guard import portfolio_allows_new_buy
    from utils.strategy_builder.position_exit import evaluate_position_exits
    from utils.strategy_builder.position_protection import (
        compute_protective_fields,
        seed_position_after_buy,
    )
    from utils.strategy_builder.rule_expiration import (
        evaluate_rule_based_expiration,
        should_skip_normal_trigger_after_expiry,
    )
    from utils.strategies.helpers import is_market_depth_available
    from utils.strategy_builder.reference_store import ReferenceEvaluationError, ReferenceStore
    from utils.strategy_builder.execution_quantity import is_holding_dependent_mode
    from utils.strategy_builder.rule_evaluator import evaluate_rule, update_history_from_snapshot
    from utils.strategy_builder.strategy_models import RuleBlock, StrategyPlanAST
    from utils.strategy_builder.strategy_parser import parse_strategy_query

    config = ctx.config.extra or {}
    if config.get("expiration_executed"):
        return _skip("ALREADY_EXECUTED", "Expiration action already executed")

    expiry_decision = evaluate_rule_based_expiration(ctx, snapshot, details)
    if expiry_decision is not None:
        return expiry_decision

    compiled = config.get("compiled_plan")
    if not compiled and config.get("query_text"):
        try:
            compiled = parse_strategy_query(config["query_text"]).model_dump()
        except Exception as exc:
            return _skip("INVALID_RULE_PLAN", f"Could not parse strategy query: {exc}")
    if not compiled:
        return _skip("MISSING_RULE_PLAN", "Rule-based strategy is missing compiled plan data")

    try:
        plan = StrategyPlanAST.model_validate(compiled)
    except Exception as exc:
        return _skip("INVALID_RULE_PLAN", f"Compiled plan is invalid: {exc}")

    symbol = (ctx.symbol or snapshot.symbol or "").upper()
    matching_rules = []
    for rule_data in plan.rules:
        rule = RuleBlock.model_validate(rule_data) if isinstance(rule_data, dict) else rule_data
        if symbol in {item.upper() for item in rule.symbols}:
            matching_rules.append(rule)
    if not matching_rules:
        return _skip("SYMBOL_NOT_IN_PLAN", f"No rule targets {symbol} in this plan")

    # Multiple RULE blocks may intentionally target the same symbol. Evaluate
    # each rule with its own history so confirmations, cooldowns, and execution
    # limits cannot leak between rules. The first rule that executes wins.
    if len(matching_rules) > 1 and not config.get("_single_rule_eval"):
        multi_rule_state = dict(config.get("multi_rule_target_state") or {})
        decisions = []
        for index, rule in enumerate(matching_rules):
            rule_state = dict(multi_rule_state.get(rule.rule_id) or {})
            if index == 0 and not rule_state and config.get("target_state"):
                # Preserve history created before multi-rule state was supported.
                rule_state = dict(config.get("target_state") or {})

            single_plan = plan.model_copy(update={"rules": [rule]}).model_dump()
            single_extra = dict(config)
            single_extra.update(
                {
                    "compiled_plan": single_plan,
                    "target_state": rule_state,
                    "_single_rule_eval": True,
                }
            )
            single_ctx = replace(
                ctx,
                config=replace(ctx.config, extra=single_extra),
            )
            decision = evaluate_rule_based_strategy(single_ctx, snapshot, memory, details)
            decision_mutate = dict(decision.mutate or {})
            multi_rule_state[rule.rule_id] = dict(
                decision_mutate.pop("target_state", rule_state) or {}
            )
            decision.mutate = decision_mutate
            decisions.append(decision)
            if decision.action == "EXECUTE":
                break

        selected = next(
            (decision for decision in decisions if decision.action == "EXECUTE"),
            next(
                (decision for decision in decisions if decision.action != "TRACK"),
                next(
                    (
                        decision
                        for decision in decisions
                        if decision.tracking_status not in {None, "NOT_MATCHED", "Monitoring"}
                    ),
                    decisions[0],
                ),
            ),
        )
        selected.mutate = {
            **dict(selected.mutate or {}),
            "multi_rule_target_state": multi_rule_state,
        }
        return selected

    selected_rule = matching_rules[0]

    normalized = build_symbol_snapshot_from_parts(symbol, snapshot, details)
    target_state = dict(config.get("target_state") or {})
    history = deserialize_target_history(target_state.get(symbol))
    if memory.last_prices and not history.observations.get("ltp"):
        for price in memory.last_prices:
            update_history_from_snapshot(
                history,
                {**normalized["flat"], "ltp": price, "last_traded_at": snapshot.last_traded_time},
            )
    if history.position.get("entry_price"):
        history.position["holding_scan_count"] = int(history.position.get("holding_scan_count") or 0) + 1
    protective = compute_protective_fields(history.position, snapshot.ltp, plan.position_protection)
    history.position.update(protective)
    flat = enrich_flat_snapshot(
        normalized["flat"],
        position_state=history.position,
        order_qty=ctx.remaining_qty or ctx.qty,
    )
    baseline = dict(config.get("schedule_baseline") or {})
    uses_field_references = bool(config.get("uses_field_references"))
    if not uses_field_references:
        if baseline.get("trigger_price") is not None:
            flat["trigger_price"] = float(baseline["trigger_price"])
        if baseline.get("reference_ltp") is not None:
            flat["reference_ltp"] = float(baseline["reference_ltp"])
    flat["_prev_spread_percent"] = history.previous_values.get("spread_percent")
    normalized["flat"] = flat

    max_age = selected_rule.execution.max_data_age_seconds
    if max_age:
        from utils.strategies.helpers import is_quote_within_max_age

        trade_ts = flat.get("last_traded_at") or snapshot.last_traded_time
        if not is_quote_within_max_age(trade_ts, int(max_age)):
            target_state[symbol] = serialize_target_history(history)
            return StrategyDecision(
                "TRACK",
                "STALE_QUOTE",
                f"Last trade data is older than {max_age}s; scan skipped",
                tracking_status="STALE_DATA",
                mutate={"target_state": target_state},
            )

    update_history_from_snapshot(history, flat)

    reference_store: Optional[ReferenceStore] = None
    if uses_field_references:
        from utils.strategy_builder.reference_store import ReferenceRow

        reference_store = ReferenceStore(
            [
                ReferenceRow(
                    rule_name=str(item.get("rule_name") or ""),
                    symbol=str(item.get("symbol") or symbol),
                    field_key=str(item.get("field_key") or ""),
                    field_type=str(item.get("field_type") or "decimal"),
                    numeric_value=item.get("numeric_value"),
                    text_value=item.get("text_value"),
                    boolean_value=item.get("boolean_value"),
                    source=item.get("source"),
                )
                for item in (config.get("field_reference_rows") or [])
            ]
        )

    exit_intent = evaluate_position_exits(
        plan,
        symbol,
        flat,
        history,
        holding_qty=int(memory.holding_qty or 0),
        form_qty=int(ctx.remaining_qty or ctx.qty or 0),
    )
    target_state[symbol] = serialize_target_history(history)
    mutate = {"target_state": target_state}
    if exit_intent and plan.side == "SELL":
        exit_mode = str(exit_intent.get("order_mode") or "").lower()
        if is_holding_dependent_mode(exit_mode):
            return StrategyDecision(
                "EXECUTE",
                "POSITION_EXIT",
                "Position exit rule matched",
                price=snapshot.ltp,
                order_mode=exit_mode,
                order_value=exit_intent.get("order_value"),
                source="Position exit",
                mutate=mutate,
            )
        return StrategyDecision(
            "EXECUTE",
            "POSITION_EXIT",
            "Position exit rule matched",
            price=snapshot.ltp,
            qty=int(exit_intent["qty"]),
            source="Position exit",
            mutate=mutate,
        )

    trigger_on_cross = (selected_rule.execution.trigger or "on_cross") == "on_cross"
    if should_skip_normal_trigger_after_expiry(ctx):
        return StrategyDecision(
            "EXPIRE",
            "EXPIRY_CANCELLED",
            "Monitoring stopped at expiration without trigger",
            expired=True,
            cancelled_reason="EXPIRY_CANCELLED",
            tracking_status="Expired",
            mutate={"expiration_cancelled": True},
        )

    try:
        evaluation = evaluate_rule(
            selected_rule,
            symbol,
            flat,
            history,
            trigger_on_cross=trigger_on_cross,
            reference_store=reference_store,
        )
    except ReferenceEvaluationError as exc:
        return StrategyDecision(
            "NO_TRADE",
            exc.code,
            str(exc),
            tracking_status="BlockedReferenceMissing",
            mutate=mutate,
        )
    target_state[symbol] = serialize_target_history(history)
    mutate = {"target_state": target_state}

    if not evaluation.matched:
        return StrategyDecision(
            "TRACK",
            "TRACKING",
            f"Monitoring: {evaluation.status or 'Monitoring'}",
            tracking_status=evaluation.status or "Monitoring",
            mutate=mutate,
        )

    blocked = _check_execution_limits(selected_rule, history)
    if blocked:
        target_state[symbol] = serialize_target_history(history)
        blocked.mutate = mutate
        return blocked

    if selected_rule.use_strategy:
        from utils.strategy_builder.strategy_delegate import (
            evaluate_delegated_strategy,
            map_delegated_decision_to_rule_action,
        )

        delegated = evaluate_delegated_strategy(
            selected_rule,
            plan_side=plan.side,
            symbol=symbol,
            parent_ctx=ctx,
            snapshot=snapshot,
            memory=memory,
            details=details,
        )
        mapped = map_delegated_decision_to_rule_action(
            delegated,
            symbol=symbol,
            strategy_name=selected_rule.use_strategy,
            mutate=mutate,
        )
        if mapped.action != "EXECUTE":
            return mapped

        qty = int(mapped.qty or ctx.remaining_qty or ctx.qty or 0)
        order_mode = str(selected_rule.order.mode or "quantity").lower()
        if qty <= 0 and not is_holding_dependent_mode(order_mode):
            from utils.strategy_builder.constants import DEFAULT_RULE_ORDER_QUANTITY

            stop_loss = selected_rule.stop_loss_price or flat.get("fixed_stop_loss_price") or flat.get("effective_stop_price")
            qty = resolve_order_quantity(
                order_mode=order_mode,
                order_value=selected_rule.order.value,
                ltp=snapshot.ltp,
                holding_qty=int(memory.holding_qty or 0),
                form_qty=int(ctx.remaining_qty or ctx.qty or 0),
                entry_price=flat.get("entry_price"),
                stop_loss_price=stop_loss,
                depth_supported_qty=int(flat.get("depth_supported_quantity") or 0),
            )
            if qty <= 0:
                qty = ctx.remaining_qty or ctx.qty or DEFAULT_RULE_ORDER_QUANTITY

        exec_price = float(mapped.price or snapshot.ltp or 0)
        _mark_rule_execution(history)
        if plan.side == "BUY" and snapshot.ltp:
            history.position = seed_position_after_buy(
                history.position,
                entry_price=float(snapshot.ltp),
                protection=plan.position_protection,
            )
            target_state[symbol] = serialize_target_history(history)
            mapped.mutate = dict(mapped.mutate or {})
            mapped.mutate["target_state"] = target_state

        return StrategyDecision(
            "EXECUTE",
            mapped.reason_code or "STRATEGY_EXECUTE",
            mapped.reason or f"{selected_rule.use_strategy} matched for {symbol}",
            price=exec_price,
            qty=qty if not is_holding_dependent_mode(order_mode) else None,
            order_mode=order_mode if is_holding_dependent_mode(order_mode) else None,
            order_value=selected_rule.order.value if is_holding_dependent_mode(order_mode) else None,
            source=mapped.source or selected_rule.use_strategy,
            leg_id=mapped.leg_id,
            mutate=mapped.mutate,
        )

    execution_mode = str(config.get("execution_mode") or "live").lower()
    if execution_mode in {"validate_only", "paper", "shadow"}:
        return StrategyDecision(
            "TRACK",
            "TRACKING",
            f"Matched ({execution_mode})",
            tracking_status=f"Matched ({execution_mode})",
            mutate=mutate,
        )

    price_source = str(selected_rule.order.price_source or "ltp").lower()
    depth_modes = {"top_buy_qty", "top_sell_qty", "partial_top_buy", "partial_top_sell"}
    order_mode = str(selected_rule.order.mode or "quantity").lower()

    if price_source not in {"ltp"} or order_mode in depth_modes:
        if not is_market_depth_available(snapshot):
            missing_depth = str(selected_rule.execution.missing_market_depth or "wait").lower()
            if missing_depth == "skip":
                return StrategyDecision(
                    "TRACK",
                    "DEPTH_UNAVAILABLE",
                    "Market depth unavailable for depth-based order",
                    tracking_status="DEPTH_UNAVAILABLE",
                    mutate=mutate,
                )
            return StrategyDecision(
                "TRACK",
                "TRACKING",
                "Waiting for market depth",
                tracking_status="Waiting for depth",
                mutate=mutate,
            )

    depth_qty, depth_note = resolve_depth_order_quantity(
        order_mode=order_mode,
        order_value=selected_rule.order.value,
        snapshot=snapshot,
        flat=flat,
        side=plan.side,
        form_qty=int(ctx.remaining_qty or ctx.qty or 0),
        holding_qty=int(memory.holding_qty or 0),
    )
    if order_mode in depth_modes:
        qty = depth_qty
        if qty <= 0:
            return StrategyDecision(
                "TRACK",
                "DEPTH_QTY_UNAVAILABLE",
                depth_note or "Depth quantity unavailable",
                tracking_status="DEPTH_QTY_UNAVAILABLE",
                mutate=mutate,
            )
    else:
        stop_loss = selected_rule.stop_loss_price or flat.get("fixed_stop_loss_price") or flat.get("effective_stop_price")
        if is_holding_dependent_mode(order_mode):
            qty = None
        else:
            qty = resolve_order_quantity(
                order_mode=order_mode,
                order_value=selected_rule.order.value,
                ltp=snapshot.ltp,
                holding_qty=int(memory.holding_qty or 0),
                form_qty=int(ctx.remaining_qty or ctx.qty or 0),
                entry_price=flat.get("entry_price"),
                stop_loss_price=stop_loss,
                depth_supported_qty=int(flat.get("depth_supported_quantity") or 0),
            )
            if qty <= 0:
                from utils.strategy_builder.constants import DEFAULT_RULE_ORDER_QUANTITY

                qty = ctx.remaining_qty or ctx.qty or DEFAULT_RULE_ORDER_QUANTITY

    exec_price, price_label = resolve_rule_execution_price(
        snapshot,
        plan.side,
        price_source,
        max_slippage_percent=selected_rule.execution.max_slippage_pct,
    )
    if exec_price <= 0:
        exec_price = float(snapshot.ltp or 0)

    sufficient = True
    sufficiency_msg = ""
    if qty is not None:
        sufficient, sufficiency_msg = depth_quantity_sufficient(
            side=plan.side,
            requested_qty=int(qty),
            snapshot=snapshot,
            flat=flat,
        )
    reason = f"Rule matched for {symbol}"
    if depth_note:
        reason = f"{reason} ({depth_note})"
    elif qty is not None and not sufficient and order_mode == "quantity" and price_source in {"top_buy", "best_bid", "top_sell", "best_ask"}:
        reason = f"{reason} — partial fill likely: {sufficiency_msg}"

    if plan.side == "BUY" and qty is not None:
        portfolio_state = dict(config.get("portfolio_state") or {})
        allowed, reason = portfolio_allows_new_buy(
            plan.portfolio_limits,
            portfolio_state,
            proposed_amount=float(qty) * float(snapshot.ltp or 0),
        )
        if not allowed:
            return StrategyDecision(
                "TRACK",
                "PORTFOLIO_BLOCKED",
                reason,
                tracking_status=reason,
                mutate=mutate,
            )

    _mark_rule_execution(history)
    if plan.side == "BUY" and snapshot.ltp:
        history.position = seed_position_after_buy(
            history.position,
            entry_price=float(snapshot.ltp),
            protection=plan.position_protection,
        )
        target_state[symbol] = serialize_target_history(history)
        mutate = {"target_state": target_state}

    return StrategyDecision(
        "EXECUTE",
        "RULE_MATCHED",
        reason,
        price=exec_price,
        qty=qty,
        order_mode=order_mode if is_holding_dependent_mode(order_mode) else None,
        order_value=selected_rule.order.value if is_holding_dependent_mode(order_mode) else None,
        source=price_label,
        mutate=mutate,
    )


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
    "Technical Buy": evaluate_rule_based_strategy,
    "Technical Sell": evaluate_rule_based_strategy,
    "Custom Query Buy": evaluate_rule_based_strategy,
    "Custom Query Sell": evaluate_rule_based_strategy,
}
