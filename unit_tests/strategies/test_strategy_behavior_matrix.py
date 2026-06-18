"""Behaviour matrix: every canonical strategy × scenarios with order expectations."""

import unittest
from datetime import datetime, timedelta

from utils.strategies.aliases import CANONICAL_STRATEGIES
from utils.strategies.handlers import (
    HANDLERS,
    evaluate_capital_protection_sell,
    evaluate_confirmed_breakout_buy,
    evaluate_emergency_exit,
    evaluate_fixed_price_buy,
    evaluate_fixed_price_sell,
    evaluate_mean_reversion_bounce_buy,
    evaluate_order_book_strength_buy,
    evaluate_profit_ladder_sell,
    evaluate_quality_pullback_recovery_buy,
    evaluate_smart_pullback_buy,
    evaluate_technical_weakness_sell,
    evaluate_time_based_buy,
    evaluate_time_based_exit,
    evaluate_trailing_runner_sell,
)
from utils.strategies.types import MarketSnapshot, OrderBookLevel, OrderContext, ScannerMemory, ScriptDetails, StrategyConfig, StrategyDecision


def _snapshot(**kwargs) -> MarketSnapshot:
    defaults = dict(
        symbol="CZBIL",
        ltp=200.0,
        open=200.0,
        high=202.0,
        low=195.0,
        volume=82902.0,
        prev_close=200.0,
        change=-3.0,
        change_percent=-1.5,
        last_traded_time=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    )
    defaults.update(kwargs)
    return MarketSnapshot(**defaults)


def _ctx(**kwargs) -> OrderContext:
    defaults = dict(
        strategy_type="Fixed Price Buy",
        canonical_strategy="Fixed Price Buy",
        side="buy",
        symbol="CZBIL",
        qty=100,
        remaining_qty=100,
        target_price=198.0,
        config=StrategyConfig(),
    )
    defaults.update(kwargs)
    return OrderContext(**defaults)


def _details(**kwargs) -> ScriptDetails:
    defaults = dict(
        available=True,
        roe=21.0,
        yoy_earnings_growth=52.0,
        pe=27.0,
        pbv=3.0,
        macd_signal="Bullish",
        rsi_14=46.0,
        mfi_14=41.0,
        stochastic_14=25.0,
        percent_b=32.0,
        three_month_price_trend="Mean reverting",
        beta_3_month=1.1,
        sharpe_annualized=0.5,
    )
    defaults.update(kwargs)
    return ScriptDetails(**defaults)


def _assert_execute(
    decision: StrategyDecision,
    *,
    price: float | None = None,
    qty: int | None = None,
    source: str | None = None,
    reason_code: str | None = None,
) -> None:
    assert decision.action == "EXECUTE", decision.action
    if price is not None:
        assert decision.price == price, decision.price
    if qty is not None:
        assert decision.qty == qty, decision.qty
    if source is not None:
        assert decision.source == source, decision.source
    if reason_code is not None:
        assert decision.reason_code == reason_code, decision.reason_code


class TestStrategyBehaviorMatrix(unittest.TestCase):
    """One test class per strategy group — documents TMS order behaviour."""

  # --- Fixed Price Buy ---
    def test_fixed_price_buy_waits_then_limit_buy_at_target(self):
        wait = evaluate_fixed_price_buy(_ctx(target_price=198), _snapshot(ltp=200), ScannerMemory(), _details())
        self.assertEqual(wait.action, "TRACK")

        go = evaluate_fixed_price_buy(_ctx(target_price=198, qty=50), _snapshot(ltp=198), ScannerMemory(), _details())
        _assert_execute(go, price=198.0, reason_code="BUY_ALLOWED_FIXED_PRICE")
        self.assertIsNone(go.qty)  # full qty applied by monitor layer

    # --- Quality Pullback Recovery Buy ---
    def test_quality_pullback_low_score_no_order(self):
        memory = ScannerMemory(last_prices=[197, 199, 201], previous_ltp=199, previous_volume=80000)
        decision = evaluate_quality_pullback_recovery_buy(
            _ctx(canonical_strategy="Quality Pullback Recovery Buy", config=StrategyConfig(min_buy_score=200)),
            _snapshot(ltp=201, volume=90000),
            memory,
            _details(),
        )
        self.assertEqual(decision.action, "NO_TRADE")

    def test_quality_pullback_falling_scans_no_order(self):
        memory = ScannerMemory(last_prices=[201, 199, 197], previous_ltp=199, previous_volume=80000)
        decision = evaluate_quality_pullback_recovery_buy(
            _ctx(canonical_strategy="Quality Pullback Recovery Buy"),
            _snapshot(ltp=197, volume=90000),
            memory,
            _details(),
        )
        self.assertEqual(decision.action, "NO_TRADE")

    def test_quality_pullback_execute_limit_at_ltp(self):
        memory = ScannerMemory(last_prices=[197, 199, 201], previous_ltp=199, previous_volume=80000)
        decision = evaluate_quality_pullback_recovery_buy(
            _ctx(canonical_strategy="Quality Pullback Recovery Buy"),
            _snapshot(ltp=201, volume=90000),
            memory,
            _details(),
        )
        _assert_execute(decision, price=201.0, reason_code="BUY_ALLOWED_QUALITY_RECOVERY")

    # --- Confirmed Breakout Buy ---
    def test_breakout_chase_blocked(self):
        memory = ScannerMemory(last_prices=[200, 201, 203], previous_ltp=201, previous_volume=80000)
        decision = evaluate_confirmed_breakout_buy(
            _ctx(canonical_strategy="Confirmed Breakout Buy"),
            _snapshot(ltp=214, change_percent=7, volume=90000),
            memory,
            _details(),
        )
        self.assertEqual(decision.action, "NO_TRADE")

    def test_breakout_execute_at_ltp(self):
        memory = ScannerMemory(last_prices=[200, 201, 203], previous_ltp=201, previous_volume=80000)
        decision = evaluate_confirmed_breakout_buy(
            _ctx(canonical_strategy="Confirmed Breakout Buy"),
            _snapshot(ltp=204, high=200, open=200, prev_close=200, change_percent=2, volume=90000),
            memory,
            _details(rsi_14=55),
        )
        _assert_execute(decision, price=204.0, reason_code="BUY_ALLOWED_BREAKOUT")

    # --- Smart Pullback Buy ---
    def test_smart_pullback_trigger_price_limit_buy(self):
        decision = evaluate_smart_pullback_buy(
            _ctx(canonical_strategy="Smart Pullback Buy", target_price=195),
            _snapshot(ltp=194, high=202),
            ScannerMemory(),
            _details(),
        )
        _assert_execute(decision, price=195.0, reason_code="BUY_ALLOWED_SMART_PULLBACK")

    def test_smart_pullback_recovery_limit_at_ltp(self):
        memory = ScannerMemory(last_prices=[196, 198, 199], previous_ltp=198)
        decision = evaluate_smart_pullback_buy(
            _ctx(canonical_strategy="Smart Pullback Buy", target_price=0),
            _snapshot(ltp=197, high=202, low=190),
            memory,
            _details(),
        )
        _assert_execute(decision, price=197.0, reason_code="BUY_ALLOWED_SMART_PULLBACK")

    # --- Mean Reversion Bounce Buy ---
    def test_mean_reversion_skips_without_details(self):
        decision = evaluate_mean_reversion_bounce_buy(
            _ctx(canonical_strategy="Mean Reversion Bounce Buy"),
            _snapshot(),
            ScannerMemory(),
            _details(available=False),
        )
        self.assertEqual(decision.action, "SKIP")

  # --- Order Book Strength Buy ---
    def test_order_book_skip_without_depth(self):
        decision = evaluate_order_book_strength_buy(
            _ctx(canonical_strategy="Order Book Strength Buy"),
            _snapshot(),
            ScannerMemory(),
            _details(),
        )
        self.assertEqual(decision.action, "SKIP")

    def test_order_book_execute_at_ltp(self):
        memory = ScannerMemory(previous_ltp=199)
        snapshot = _snapshot(
            ltp=200,
            open=198,
            top_buy_orders=[OrderBookLevel(199, 60000)],
            top_sell_orders=[OrderBookLevel(200, 40000)],
        )
        decision = evaluate_order_book_strength_buy(
            _ctx(canonical_strategy="Order Book Strength Buy"),
            snapshot,
            memory,
            _details(),
        )
        _assert_execute(decision, price=200.0, reason_code="BUY_ALLOWED_ORDER_BOOK")

    # --- Fixed Price Sell ---
    def test_fixed_price_sell_waits_then_limit_sell(self):
        wait = evaluate_fixed_price_sell(
            _ctx(side="sell", canonical_strategy="Fixed Price Sell", target_price=220),
            _snapshot(ltp=218),
            ScannerMemory(),
            _details(),
        )
        self.assertEqual(wait.action, "TRACK")

        go = evaluate_fixed_price_sell(
            _ctx(side="sell", canonical_strategy="Fixed Price Sell", target_price=220),
            _snapshot(ltp=220),
            ScannerMemory(),
            _details(),
        )
        _assert_execute(go, price=220.0, reason_code="SELL_ALLOWED_FIXED_PRICE")

    # --- Capital Protection Sell ---
    def test_capital_protection_first_scan_confirms_only(self):
        ctx = _ctx(
            side="sell",
            canonical_strategy="Capital Protection Sell",
            average_buy_price=200,
            target_price=200,
            config=StrategyConfig(stop_loss_pct=3),
            below_stop_loss_check_count=0,
        )
        decision = evaluate_capital_protection_sell(ctx, _snapshot(ltp=193), ScannerMemory(), _details())
        self.assertEqual(decision.action, "TRACK")
        self.assertEqual(decision.mutate.get("below_stop_loss_check_count"), 1)

    def test_capital_protection_second_scan_limit_sell_clamped(self):
        ctx = _ctx(
            side="sell",
            canonical_strategy="Capital Protection Sell",
            average_buy_price=200,
            target_price=200,
            config=StrategyConfig(stop_loss_pct=3),
            below_stop_loss_check_count=1,
        )
        decision = evaluate_capital_protection_sell(ctx, _snapshot(ltp=193), ScannerMemory(), _details())
        _assert_execute(decision, reason_code="SELL_TRIGGERED_CAPITAL_PROTECTION")
        self.assertLessEqual(decision.price, 193)

    # --- Profit Ladder Sell ---
    def test_profit_ladder_partial_sell_target1(self):
        ctx = _ctx(
            side="sell",
            canonical_strategy="Profit Ladder Sell",
            average_buy_price=200,
            target_price=200,
            config=StrategyConfig(target1_sell_pct=30, target2_sell_pct=30),
        )
        decision = evaluate_profit_ladder_sell(ctx, _snapshot(ltp=208), ScannerMemory(), _details())
        _assert_execute(decision, qty=30, reason_code="SELL_TRIGGERED_PROFIT_LADDER")
        self.assertTrue(decision.mutate.get("sold_target1"))

    def test_profit_ladder_partial_sell_target2(self):
        ctx = _ctx(
            side="sell",
            canonical_strategy="Profit Ladder Sell",
            average_buy_price=200,
            target_price=200,
            config=StrategyConfig(target1_sell_pct=30, target2_sell_pct=30, sold_target1=True),
        )
        decision = evaluate_profit_ladder_sell(ctx, _snapshot(ltp=216), ScannerMemory(), _details())
        _assert_execute(decision, qty=30, reason_code="SELL_TRIGGERED_PROFIT_LADDER")
        self.assertTrue(decision.mutate.get("sold_target2"))

    # --- Trailing Runner Sell ---
    def test_trailing_runner_tracks_then_sells_remaining(self):
        track = evaluate_trailing_runner_sell(
            _ctx(side="sell", canonical_strategy="Trailing Runner Sell", remaining_qty=40, highest_tracked_price=230, config=StrategyConfig(trailing_stop_pct=3)),
            _snapshot(ltp=228),
            ScannerMemory(),
            _details(),
        )
        self.assertEqual(track.action, "TRACK")

        go = evaluate_trailing_runner_sell(
            _ctx(side="sell", canonical_strategy="Trailing Runner Sell", remaining_qty=40, highest_tracked_price=230, config=StrategyConfig(trailing_stop_pct=3)),
            _snapshot(ltp=223),
            ScannerMemory(),
            _details(),
        )
        _assert_execute(go, qty=40, reason_code="SELL_TRIGGERED_TRAILING_RUNNER")

    # --- Technical Weakness Sell ---
    def test_technical_weakness_watch_when_partial(self):
        memory = ScannerMemory(last_prices=[200, 198, 196], previous_ltp=198)
        decision = evaluate_technical_weakness_sell(
            _ctx(side="sell", canonical_strategy="Technical Weakness Sell"),
            _snapshot(ltp=196, open=200, prev_close=200),
            memory,
            _details(macd_signal="Bullish", rsi_14=50),
        )
        self.assertEqual(decision.action, "WATCH")

    def test_technical_weakness_full_exit(self):
        memory = ScannerMemory(last_prices=[200, 198, 196], previous_ltp=198)
        decision = evaluate_technical_weakness_sell(
            _ctx(side="sell", canonical_strategy="Technical Weakness Sell"),
            _snapshot(ltp=196, open=200, prev_close=200),
            memory,
            _details(macd_signal="Bearish", rsi_14=32, volume_trend="Down"),
        )
        _assert_execute(decision, reason_code="SELL_TRIGGERED_TECHNICAL_WEAKNESS")

    # --- Emergency Exit ---
    def test_emergency_requires_confirmation(self):
        decision = evaluate_emergency_exit(
            _ctx(side="sell", canonical_strategy="Emergency Exit by Top Buyer", emergency_execution=False),
            _snapshot(ltp=198, top_buy_orders=[OrderBookLevel(197, 5000)]),
            ScannerMemory(),
            _details(),
        )
        self.assertEqual(decision.action, "NO_TRADE")

    def test_emergency_top_buy_limit_sell(self):
        decision = evaluate_emergency_exit(
            _ctx(side="sell", canonical_strategy="Emergency Exit by Top Buyer", emergency_execution=True),
            _snapshot(ltp=198, top_buy_orders=[OrderBookLevel(197, 5000)]),
            ScannerMemory(),
            _details(),
        )
        _assert_execute(decision, price=197.0, source="Top Buy", reason_code="SELL_TRIGGERED_EMERGENCY_EXIT")

    def test_emergency_split_partial_qty(self):
        decision = evaluate_emergency_exit(
            _ctx(
                side="sell",
                canonical_strategy="Emergency Exit by Top Buyer",
                emergency_execution=True,
                remaining_qty=100,
                config=StrategyConfig(allow_split_emergency_exit=True),
            ),
            _snapshot(ltp=198, top_buy_orders=[OrderBookLevel(197, 40)]),
            ScannerMemory(),
            _details(),
        )
        _assert_execute(decision, price=197.0, qty=40, source="Top Buy")

    # --- Time wrappers ---
    def test_time_based_buy_expires_no_order(self):
        ctx = _ctx(canonical_strategy="Time-Based Buy", expiry_time=datetime.utcnow() - timedelta(minutes=1))
        decision = evaluate_time_based_buy(ctx, _snapshot(), ScannerMemory(), _details(), evaluate_fixed_price_buy)
        self.assertEqual(decision.action, "EXPIRE")

    def test_time_based_exit_cancel_expires(self):
        ctx = _ctx(
            side="sell",
            canonical_strategy="Time-Based Exit",
            expiry_time=datetime.utcnow() - timedelta(minutes=1),
            expiry_action="Cancel strategy",
        )
        decision = evaluate_time_based_exit(ctx, _snapshot(ltp=198), ScannerMemory(), _details())
        self.assertEqual(decision.action, "EXPIRE")

    def test_all_canonical_strategies_have_handler_or_wrapper(self):
        core = set(HANDLERS)
        self.assertEqual(core | {"Time-Based Buy", "Time-Based Exit"}, CANONICAL_STRATEGIES)


if __name__ == "__main__":
    unittest.main()
