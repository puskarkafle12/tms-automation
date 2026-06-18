import unittest
from datetime import datetime, timedelta

from utils.strategies.aliases import STRATEGY_ALIASES, canonical_strategy_name
from utils.strategies.handlers import (
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
from utils.strategies.helpers import get_buy_pressure, is_rising, range_position
from utils.strategies.risk_guard import can_place_order
from utils.strategies.scoring import calculate_buy_score, score_decision
from utils.strategies.types import AccountState, MarketSnapshot, OrderBookLevel, OrderContext, ScannerMemory, ScriptDetails, StrategyConfig
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


class TestHelpers(unittest.TestCase):
    def test_range_position_and_buy_pressure(self):
        snapshot = _snapshot(ltp=200, low=195, high=202, top_buy_orders=[OrderBookLevel(198, 40000)], top_sell_orders=[OrderBookLevel(199, 20000)])
        self.assertAlmostEqual(range_position(snapshot), (200 - 195) / 7, places=4)
        self.assertAlmostEqual(get_buy_pressure(snapshot) or 0, 40000 / 60000, places=4)

    def test_is_rising(self):
        self.assertTrue(is_rising([197, 199, 201], 3))


class TestAliases(unittest.TestCase):
    def test_legacy_names_map_to_canonical(self):
        self.assertEqual(canonical_strategy_name("Dip Buy", "buy"), "Smart Pullback Buy")
        self.assertEqual(canonical_strategy_name("Fast Stop Loss", "sell"), "Capital Protection Sell")
        self.assertIn("Breakout Buy", STRATEGY_ALIASES)

    def test_all_aliases_resolve_to_canonical(self):
        for legacy, canonical in STRATEGY_ALIASES.items():
            side = "sell" if canonical in {
                "Capital Protection Sell", "Profit Ladder Sell", "Trailing Runner Sell",
                "Emergency Exit by Top Buyer",
            } else "buy"
            self.assertEqual(canonical_strategy_name(legacy, side), canonical)

    def test_fixed_price_side_resolution(self):
        self.assertEqual(canonical_strategy_name("Fixed Price", "buy"), "Fixed Price Buy")
        self.assertEqual(canonical_strategy_name("Fixed Price", "sell"), "Fixed Price Sell")


class TestBuyStrategies(unittest.TestCase):
    def test_fixed_price_buy_no_trade_then_execute(self):
        decision = evaluate_fixed_price_buy(_ctx(target_price=198), _snapshot(ltp=200), ScannerMemory(), ScriptDetails())
        self.assertEqual(decision.action, "TRACK")
        decision = evaluate_fixed_price_buy(_ctx(target_price=198), _snapshot(ltp=198), ScannerMemory(), ScriptDetails())
        self.assertEqual(decision.action, "EXECUTE")

    def test_quality_pullback_recovery_buy(self):
        memory = ScannerMemory(last_prices=[197, 199, 201], previous_ltp=199, previous_volume=80000)
        decision = evaluate_quality_pullback_recovery_buy(_ctx(canonical_strategy="Quality Pullback Recovery Buy"), _snapshot(ltp=201, volume=90000), memory, _details())
        self.assertEqual(decision.action, "EXECUTE")

    def test_confirmed_breakout_rejects_chasing(self):
        memory = ScannerMemory(last_prices=[200, 201, 203], previous_ltp=201, previous_volume=80000)
        decision = evaluate_confirmed_breakout_buy(_ctx(canonical_strategy="Confirmed Breakout Buy", target_price=203), _snapshot(ltp=214, change_percent=7, volume=90000), memory, _details())
        self.assertEqual(decision.action, "NO_TRADE")

    def test_confirmed_breakout_executes_when_confirmed(self):
        memory = ScannerMemory(last_prices=[200, 201, 203], previous_ltp=201, previous_volume=80000)
        decision = evaluate_confirmed_breakout_buy(
            _ctx(canonical_strategy="Confirmed Breakout Buy", target_price=203),
            _snapshot(ltp=204, high=200, open=200, prev_close=200, change_percent=2, volume=90000),
            memory,
            _details(rsi_14=55),
        )
        self.assertEqual(decision.action, "EXECUTE")
        self.assertEqual(decision.reason_code, "BUY_ALLOWED_BREAKOUT")

    def test_smart_pullback_buy(self):
        memory = ScannerMemory(last_prices=[196, 198, 199], previous_ltp=198)
        decision = evaluate_smart_pullback_buy(_ctx(canonical_strategy="Smart Pullback Buy"), _snapshot(ltp=196, high=202, low=195), memory, _details())
        self.assertEqual(decision.action, "EXECUTE")

    def test_mean_reversion_bounce_buy(self):
        memory = ScannerMemory(last_prices=[197, 199, 200], previous_ltp=199, previous_volume=80000)
        decision = evaluate_mean_reversion_bounce_buy(_ctx(canonical_strategy="Mean Reversion Bounce Buy"), _snapshot(ltp=200, volume=90000), memory, _details())
        self.assertIn(decision.action, {"EXECUTE", "WATCH"})

    def test_order_book_strength_skips_without_depth(self):
        decision = evaluate_order_book_strength_buy(_ctx(canonical_strategy="Order Book Strength Buy"), _snapshot(), ScannerMemory(), _details())
        self.assertEqual(decision.action, "SKIP")

    def test_order_book_strength_executes_with_depth(self):
        memory = ScannerMemory(previous_ltp=199)
        snapshot = _snapshot(
            ltp=200,
            open=198,
            top_buy_orders=[OrderBookLevel(199, 60000)],
            top_sell_orders=[OrderBookLevel(200, 40000)],
        )
        decision = evaluate_order_book_strength_buy(_ctx(canonical_strategy="Order Book Strength Buy"), snapshot, memory, _details())
        self.assertEqual(decision.action, "EXECUTE")
        self.assertEqual(decision.reason_code, "BUY_ALLOWED_ORDER_BOOK")


class TestSellStrategies(unittest.TestCase):
    def test_fixed_price_sell(self):
        decision = evaluate_fixed_price_sell(_ctx(side="sell", canonical_strategy="Fixed Price Sell", target_price=220), _snapshot(ltp=220), ScannerMemory(), _details())
        self.assertEqual(decision.action, "EXECUTE")

    def test_capital_protection_trailing_stop_ratchet_moves_up(self):
        ctx = _ctx(
            side="sell",
            canonical_strategy="Capital Protection Sell",
            average_buy_price=400,
            target_price=400,
            stop_loss_price=385,
            highest_tracked_price=420,
            config=StrategyConfig(trailing_stop_pct=3),
        )
        decision = evaluate_capital_protection_sell(ctx, _snapshot(ltp=408), ScannerMemory(), _details())
        self.assertEqual(decision.action, "TRACK")
        self.assertEqual(decision.mutate.get("highest_tracked_price"), 420)

        decision = evaluate_capital_protection_sell(
            _ctx(
                side="sell",
                canonical_strategy="Capital Protection Sell",
                average_buy_price=400,
                target_price=400,
                stop_loss_price=385,
                highest_tracked_price=420,
                below_stop_loss_check_count=1,
                config=StrategyConfig(trailing_stop_pct=3),
            ),
            _snapshot(ltp=407),
            ScannerMemory(),
            _details(),
        )
        self.assertEqual(decision.action, "EXECUTE")
        self.assertLessEqual(decision.price, 407)

    def test_capital_protection_sell_confirms_before_execute(self):
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
        self.assertEqual(decision.reason_code, "SELL_TRACK_STOP_LOSS")

    def test_capital_protection_sell_triggers_stop(self):
        ctx = _ctx(
            side="sell",
            canonical_strategy="Capital Protection Sell",
            average_buy_price=200,
            target_price=200,
            config=StrategyConfig(stop_loss_pct=3),
            below_stop_loss_check_count=1,
        )
        decision = evaluate_capital_protection_sell(ctx, _snapshot(ltp=193), ScannerMemory(), _details())
        self.assertEqual(decision.action, "EXECUTE")
        self.assertEqual(decision.reason_code, "SELL_TRIGGERED_CAPITAL_PROTECTION")
        self.assertLessEqual(decision.price, 193)

    def test_capital_protection_fast_stop_loss_legacy(self):
        ctx = _ctx(
            side="sell",
            canonical_strategy="Capital Protection Sell",
            legacy_alias="Fast Stop Loss",
            stop_loss_price=194,
            below_stop_loss_check_count=1,
            last_checked_ltp=196,
        )
        decision = evaluate_capital_protection_sell(ctx, _snapshot(ltp=192), ScannerMemory(), _details())
        self.assertEqual(decision.action, "EXECUTE")
        self.assertEqual(decision.reason_code, "SELL_TRIGGERED_CAPITAL_PROTECTION")

    def test_profit_ladder_sell(self):
        ctx = _ctx(side="sell", canonical_strategy="Profit Ladder Sell", average_buy_price=200, target_price=200, config=StrategyConfig(target1_sell_pct=30, target2_sell_pct=30))
        decision = evaluate_profit_ladder_sell(ctx, _snapshot(ltp=208), ScannerMemory(), _details())
        self.assertEqual(decision.action, "EXECUTE")
        self.assertEqual(decision.qty, 30)

    def test_trailing_runner_sell(self):
        ctx = _ctx(side="sell", canonical_strategy="Trailing Runner Sell", remaining_qty=40, highest_tracked_price=230, config=StrategyConfig(trailing_stop_pct=3))
        decision = evaluate_trailing_runner_sell(ctx, _snapshot(ltp=223), ScannerMemory(), _details())
        self.assertEqual(decision.action, "EXECUTE")

    def test_technical_weakness_sell(self):
        memory = ScannerMemory(last_prices=[200, 198, 196], previous_ltp=198)
        decision = evaluate_technical_weakness_sell(
            _ctx(side="sell", canonical_strategy="Technical Weakness Sell"),
            _snapshot(ltp=196, open=200, prev_close=200),
            memory,
            _details(macd_signal="Bearish", rsi_14=32, volume_trend="Down"),
        )
        self.assertEqual(decision.action, "EXECUTE")

    def test_emergency_exit_fallback(self):
        decision = evaluate_emergency_exit(
            _ctx(side="sell", canonical_strategy="Emergency Exit by Top Buyer", emergency_execution=True),
            _snapshot(ltp=198),
            ScannerMemory(),
            _details(),
        )
        self.assertEqual(decision.action, "EXECUTE")
        self.assertEqual(decision.source, "LTP fallback")

    def test_emergency_exit_uses_top_buyer(self):
        decision = evaluate_emergency_exit(
            _ctx(side="sell", canonical_strategy="Emergency Exit by Top Buyer", emergency_execution=True),
            _snapshot(ltp=198, top_buy_orders=[OrderBookLevel(197, 5000)]),
            ScannerMemory(),
            _details(),
        )
        self.assertEqual(decision.action, "EXECUTE")
        self.assertEqual(decision.source, "Top Buy")
        self.assertEqual(decision.price, 197)


class TestWrappers(unittest.TestCase):
    def test_time_based_buy_expires(self):
        ctx = _ctx(
            canonical_strategy="Time-Based Buy",
            expiry_time=datetime.utcnow() - timedelta(minutes=1),
        )
        decision = evaluate_time_based_buy(ctx, _snapshot(), ScannerMemory(), _details(), evaluate_fixed_price_buy)
        self.assertEqual(decision.action, "EXPIRE")
        self.assertEqual(decision.reason_code, "STRATEGY_EXPIRED")

    def test_time_based_buy_delegates_to_wrapped_strategy(self):
        ctx = _ctx(
            canonical_strategy="Time-Based Buy",
            target_price=198,
            expiry_time=datetime.utcnow() + timedelta(hours=1),
            config=StrategyConfig(wrapped_strategy_type="Fixed Price Buy"),
        )
        decision = evaluate_time_based_buy(ctx, _snapshot(ltp=198), ScannerMemory(), _details(), evaluate_fixed_price_buy)
        self.assertEqual(decision.action, "EXECUTE")

    def test_time_based_exit_sells_on_expiry(self):
        ctx = _ctx(
            side="sell",
            canonical_strategy="Time-Based Exit",
            expiry_time=datetime.utcnow() - timedelta(minutes=1),
            expiry_action="Sell using Top Buy",
            emergency_execution=True,
        )
        decision = evaluate_time_based_exit(ctx, _snapshot(ltp=198), ScannerMemory(), _details())
        self.assertEqual(decision.action, "EXECUTE")

    def test_time_based_exit_monitors_before_expiry(self):
        ctx = _ctx(
            side="sell",
            canonical_strategy="Time-Based Exit",
            expiry_time=datetime.utcnow() + timedelta(hours=1),
        )
        decision = evaluate_time_based_exit(ctx, _snapshot(ltp=198), ScannerMemory(), _details())
        self.assertEqual(decision.action, "TRACK")


class TestRiskGuard(unittest.TestCase):
    def test_rejects_invalid_qty(self):
        risk = can_place_order(
            context=_ctx(),
            snapshot=_snapshot(),
            account=AccountState(),
            price=100,
            qty=0,
        )
        self.assertFalse(risk.allowed)
        self.assertEqual(risk.reason_code, "INVALID_QTY")

    def test_rejects_duplicate_active_order(self):
        risk = can_place_order(
            context=_ctx(),
            snapshot=_snapshot(),
            account=AccountState(active_orders_same_symbol_side=1),
            price=100,
            qty=10,
        )
        self.assertFalse(risk.allowed)
        self.assertEqual(risk.reason_code, "DUPLICATE_ACTIVE_ORDER")

    def test_rejects_insufficient_holding_on_sell(self):
        risk = can_place_order(
            context=_ctx(side="sell", remaining_qty=5),
            snapshot=_snapshot(),
            account=AccountState(holding_qty=5),
            price=100,
            qty=10,
        )
        self.assertFalse(risk.allowed)
        self.assertEqual(risk.reason_code, "INSUFFICIENT_HOLDING")

    def test_passes_valid_buy(self):
        risk = can_place_order(
            context=_ctx(),
            snapshot=_snapshot(),
            account=AccountState(available_balance=5000),
            price=100,
            qty=10,
        )
        self.assertTrue(risk.allowed)
        self.assertEqual(risk.reason_code, "RISK_OK")


class TestScoring(unittest.TestCase):
    def test_score_decision_thresholds(self):
        self.assertEqual(score_decision(80), "BUY_ALLOWED")
        self.assertEqual(score_decision(60), "WATCH_ONLY")
        self.assertEqual(score_decision(40), "NO_TRADE")

    def test_calculate_buy_score_positive(self):
        memory = ScannerMemory(last_prices=[197, 199, 201], previous_ltp=199, previous_volume=80000)
        score = calculate_buy_score(_snapshot(ltp=201, volume=90000), memory, _details())
        self.assertGreater(score, 55)


if __name__ == "__main__":
    unittest.main()
