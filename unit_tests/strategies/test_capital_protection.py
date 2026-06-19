import unittest
from datetime import datetime, timedelta

from utils.strategies.capital_protection import (
    compute_capital_protection_stops,
    evaluate_capital_protection_core,
    trailing_pct_for_volatility,
)
from utils.strategies.handlers import evaluate_capital_protection_sell
from utils.strategies.types import MarketSnapshot, OrderBookLevel, OrderContext, ScannerMemory, ScriptDetails, StrategyConfig


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
        strategy_type="Capital Protection Sell",
        canonical_strategy="Capital Protection Sell",
        side="sell",
        symbol="CZBIL",
        qty=100,
        remaining_qty=100,
        target_price=200.0,
        config=StrategyConfig(),
    )
    defaults.update(kwargs)
    return OrderContext(**defaults)


class TestCapitalProtectionHelpers(unittest.TestCase):
    def test_trailing_pct_widens_with_day_range(self):
        self.assertEqual(trailing_pct_for_volatility(3.0, 1.0), 3.0)
        self.assertEqual(trailing_pct_for_volatility(3.0, 1.4), 3.0)
        self.assertEqual(trailing_pct_for_volatility(3.0, 2.0), 3.0)
        self.assertEqual(trailing_pct_for_volatility(3.0, 4.0), 4.0)
        self.assertEqual(trailing_pct_for_volatility(3.0, 6.0), 5.0)

    def test_break_even_arms_after_one_point_five_percent_peak(self):
        stops = compute_capital_protection_stops(
            entry_price=200.0,
            stop_pct=5.0,
            trailing_pct=3.0,
            highest_ltp=203.0,
            snapshot=_snapshot(ltp=203.0, high=204, low=198, prev_close=200),
        )
        self.assertEqual(stops.break_even, 200.0)
        self.assertEqual(stops.effective_stop, 200.0)

    def test_effective_stop_uses_max_of_hard_trail_and_break_even(self):
        stops = compute_capital_protection_stops(
            entry_price=400.0,
            stop_pct=5.0,
            trailing_pct=3.0,
            highest_ltp=420.0,
            snapshot=_snapshot(ltp=408.0, high=421, low=419, prev_close=400),
            hard_stop_override=385.0,
        )
        self.assertAlmostEqual(stops.trail_stop, 420 * 0.97, places=2)
        self.assertGreater(stops.effective_stop, 385.0)


class TestCapitalProtectionCore(unittest.TestCase):
    def test_stale_data_skips_without_state_change(self):
        old_time = (datetime.utcnow() - timedelta(minutes=45)).strftime("%Y-%m-%d %H:%M:%S")
        decision = evaluate_capital_protection_core(
            _ctx(average_buy_price=200, below_stop_loss_check_count=2),
            _snapshot(ltp=180, last_traded_time=old_time),
        )
        self.assertEqual(decision.action, "SKIP")
        self.assertEqual(decision.reason_code, "STALE_DATA_SKIP")
        self.assertFalse(decision.mutate)

    def test_new_peak_resets_scans_and_raises_trail(self):
        decision = evaluate_capital_protection_core(
            _ctx(average_buy_price=400, highest_tracked_price=420, below_stop_loss_check_count=1),
            _snapshot(ltp=425, high=426, low=410, prev_close=400),
        )
        self.assertEqual(decision.action, "TRACK")
        self.assertEqual(decision.reason_code, "SELL_TRACK_NEW_PEAK")
        self.assertEqual(decision.mutate.get("highest_tracked_price"), 425)
        self.assertEqual(decision.mutate.get("below_stop_loss_check_count"), 0)

    def test_safe_zone_resets_scans(self):
        decision = evaluate_capital_protection_core(
            _ctx(average_buy_price=400, highest_tracked_price=420, below_stop_loss_check_count=1, stop_loss_price=385),
            _snapshot(ltp=408, high=421, low=419, prev_close=400),
        )
        self.assertEqual(decision.reason_code, "SELL_TRACK_CAPITAL_PROTECTION")
        self.assertEqual(decision.mutate.get("below_stop_loss_check_count"), 0)

    def test_depth_support_holds_when_bids_defend_stop(self):
        decision = evaluate_capital_protection_core(
            _ctx(average_buy_price=200, config=StrategyConfig(stop_loss_pct=3)),
            _snapshot(
                ltp=193,
                high=202,
                low=192,
                prev_close=200,
                top_buy_orders=[
                    OrderBookLevel(194, 5000),
                    OrderBookLevel(193.5, 4000),
                ],
                top_sell_orders=[OrderBookLevel(195, 1000)],
            ),
        )
        self.assertEqual(decision.reason_code, "SELL_TRACK_DEPTH_SUPPORT")
        self.assertEqual(decision.mutate.get("below_stop_loss_check_count"), 0)

    def test_confirms_then_executes_after_two_scans_below_stop(self):
        first = evaluate_capital_protection_core(
            _ctx(average_buy_price=200, config=StrategyConfig(stop_loss_pct=3)),
            _snapshot(ltp=193, high=202, low=192, prev_close=200),
        )
        self.assertEqual(first.action, "TRACK")
        self.assertEqual(first.reason_code, "SELL_TRACK_STOP_LOSS")
        self.assertEqual(first.mutate.get("below_stop_loss_check_count"), 1)

        second = evaluate_capital_protection_core(
            _ctx(
                average_buy_price=200,
                config=StrategyConfig(stop_loss_pct=3),
                below_stop_loss_check_count=1,
            ),
            _snapshot(ltp=192.5, high=202, low=192, prev_close=200),
        )
        self.assertEqual(second.action, "EXECUTE")
        self.assertEqual(second.reason_code, "SELL_TRIGGERED_CAPITAL_PROTECTION")


class TestCapitalProtectionHandler(unittest.TestCase):
    def test_handler_clamps_execute_price_to_ltp(self):
        decision = evaluate_capital_protection_sell(
            _ctx(
                average_buy_price=200,
                config=StrategyConfig(stop_loss_pct=3),
                below_stop_loss_check_count=1,
            ),
            _snapshot(ltp=193, high=202, low=192, prev_close=200),
            ScannerMemory(),
            ScriptDetails(),
        )
        self.assertEqual(decision.action, "EXECUTE")
        self.assertLessEqual(decision.price, 193)

    def test_trailing_peak_then_execute_on_second_breach(self):
        track = evaluate_capital_protection_sell(
            _ctx(
                average_buy_price=400,
                highest_tracked_price=420,
                stop_loss_price=385,
                config=StrategyConfig(trailing_stop_pct=3),
            ),
            _snapshot(ltp=408, high=421, low=419, prev_close=400),
            ScannerMemory(),
            ScriptDetails(),
        )
        self.assertEqual(track.action, "TRACK")

        execute = evaluate_capital_protection_sell(
            _ctx(
                average_buy_price=400,
                highest_tracked_price=420,
                stop_loss_price=385,
                below_stop_loss_check_count=1,
                config=StrategyConfig(trailing_stop_pct=3),
            ),
            _snapshot(ltp=407, high=421, low=419, prev_close=400),
            ScannerMemory(),
            ScriptDetails(),
        )
        self.assertEqual(execute.action, "EXECUTE")

    def test_fast_stop_loss_legacy_still_executes(self):
        decision = evaluate_capital_protection_sell(
            _ctx(
                legacy_alias="Fast Stop Loss",
                stop_loss_price=194,
                below_stop_loss_check_count=1,
                last_checked_ltp=196,
            ),
            _snapshot(ltp=192),
            ScannerMemory(),
            ScriptDetails(),
        )
        self.assertEqual(decision.action, "EXECUTE")
        self.assertEqual(decision.reason_code, "SELL_TRIGGERED_CAPITAL_PROTECTION")


if __name__ == "__main__":
    unittest.main()
