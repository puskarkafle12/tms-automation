"""Real-time multi-scan scenarios for rule-based buy/sell strategies."""

import unittest

from unit_tests.strategies.rule_based_scan_simulator import (
    default_details,
    default_snapshot,
    first_execute_index,
    simulate_scans,
)
from utils.strategy_builder.history_service import TargetHistory, serialize_target_history
from utils.strategy_builder.position_protection import seed_position_after_buy


class RuleBasedRealtimeMatrixTest(unittest.TestCase):
    def test_simple_ltp_buy_waits_then_executes(self):
        query = """
STRATEGY_VERSION 1
SIDE BUY
RULE "LTP Buy" FOR SYMBOL "CZBIL" {
    WHEN ltp <= 200
    ORDER QUANTITY 100
    EXECUTE ONCE
}
"""
        decisions = simulate_scans(query, price_series=[201.0, 200.0], execution_mode="live")
        self.assertEqual(decisions[0].action, "TRACK")
        self.assertEqual(decisions[1].action, "EXECUTE")
        self.assertEqual(decisions[1].qty, 100)
        self.assertEqual(first_execute_index(decisions), 1)

    def test_confirm_true_for_two_scans(self):
        query = """
STRATEGY_VERSION 1
SIDE BUY
RULE "RSI Confirm" FOR SYMBOL "CZBIL" {
    WHEN technical_rsi_14 > 30
    CONFIRM TRUE_FOR 2 SCANS
    TRIGGER LEVEL
    ORDER QUANTITY 50
    EXECUTE ONCE
}
"""
        decisions = simulate_scans(
            query,
            price_series=[200.0, 200.0],
            execution_mode="live",
            details=default_details(rsi_14=35.0),
            snapshot_builder=lambda ltp, idx: default_snapshot(
                ltp=ltp,
                last_traded_time=f"2026-01-01 10:00:{idx:02d}",
            ),
        )
        self.assertEqual(decisions[0].action, "TRACK")
        self.assertEqual(decisions[1].action, "EXECUTE")
        self.assertEqual(decisions[1].qty, 50)

    def test_eligibility_gates_signal(self):
        query = """
STRATEGY_VERSION 1
SIDE BUY
RULE "Eligibility" FOR SYMBOL "CZBIL" {
    ELIGIBILITY volume > 100000
    SIGNAL technical_rsi_14 < 70
    ORDER QUANTITY 10
    EXECUTE ONCE
}
"""
        low_vol = simulate_scans(
            query,
            price_series=[200.0],
            execution_mode="live",
            details=default_details(rsi_14=50.0),
            snapshot_builder=lambda ltp, _: default_snapshot(ltp=ltp, volume=50000.0),
        )
        self.assertEqual(low_vol[0].action, "TRACK")

        high_vol = simulate_scans(
            query,
            price_series=[200.0],
            execution_mode="live",
            details=default_details(rsi_14=50.0),
            snapshot_builder=lambda ltp, _: default_snapshot(ltp=ltp, volume=150000.0),
        )
        self.assertEqual(high_vol[0].action, "EXECUTE")
        self.assertEqual(high_vol[0].qty, 10)

    def test_consecutive_rises_with_min_change(self):
        query = """
STRATEGY_VERSION 1
SIDE BUY
RULE "Rises" FOR SYMBOL "CZBIL" {
    WHEN CONSECUTIVE_RISES(field=ltp, count=2, min_total_change_pct=1)
    ORDER QUANTITY 20
    EXECUTE ONCE
}
"""

        def rising_snapshot(ltp: float, scan_idx: int):
            return default_snapshot(
                ltp=ltp,
                last_traded_time=f"2026-01-01 10:00:{scan_idx:02d}",
            )

        decisions = simulate_scans(
            query,
            price_series=[200.0, 203.0, 206.0],
            execution_mode="live",
            snapshot_builder=rising_snapshot,
        )
        execute_idx = first_execute_index(decisions)
        self.assertIsNotNone(execute_idx)
        self.assertEqual(decisions[execute_idx].action, "EXECUTE")

    def test_paper_mode_tracks_instead_of_execute(self):
        query = """
STRATEGY_VERSION 1
SIDE BUY
RULE "Paper" FOR SYMBOL "CZBIL" {
    WHEN ltp <= 200
    ORDER QUANTITY 100
    EXECUTE ONCE
}
"""
        decisions = simulate_scans(query, price_series=[200.0], execution_mode="paper")
        self.assertEqual(decisions[0].action, "TRACK")
        self.assertIn("paper", (decisions[0].tracking_status or "").lower())

    def test_live_mode_executes_same_query(self):
        query = """
STRATEGY_VERSION 1
SIDE BUY
RULE "Live" FOR SYMBOL "CZBIL" {
    WHEN ltp <= 200
    ORDER QUANTITY 100
    EXECUTE ONCE
}
"""
        decisions = simulate_scans(query, price_series=[200.0], execution_mode="live")
        self.assertEqual(decisions[0].action, "EXECUTE")

    def test_amount_sizing(self):
        query = """
STRATEGY_VERSION 1
SIDE BUY
RULE "Amount" FOR SYMBOL "CZBIL" {
    WHEN ltp <= 200
    ORDER AMOUNT 10000
    EXECUTE ONCE
}
"""
        decisions = simulate_scans(query, price_series=[200.0], execution_mode="live")
        self.assertEqual(decisions[0].action, "EXECUTE")
        self.assertEqual(decisions[0].qty, 50)

    def test_portfolio_guard_blocks_buy(self):
        query = """
STRATEGY_VERSION 1
SIDE BUY
RULE "Guarded" FOR SYMBOL "CZBIL" {
    WHEN ltp <= 200
    ORDER QUANTITY 100
    EXECUTE ONCE
}
"""
        decisions = simulate_scans(
            query,
            price_series=[200.0],
            execution_mode="live",
            portfolio_state={"daily_buy_amount": 950},
            compiled_plan_overrides={"portfolio_limits": {"max_total_buy_amount": 1000}},
        )
        self.assertEqual(decisions[0].action, "TRACK")
        self.assertEqual(decisions[0].reason_code, "PORTFOLIO_BLOCKED")

    def test_position_exit_profit_sell(self):
        query = """
STRATEGY_VERSION 1
SIDE SELL
POSITION_EXIT {
    SELL PERCENT_OF_HOLDING 50 WHEN profit_percent >= 5
}
RULE "Hold" FOR SYMBOL "CZBIL" {
    WHEN ltp > 0
    ORDER QUANTITY 10
    EXECUTE ONCE
}
"""
        position = seed_position_after_buy({}, entry_price=500.0, protection=None)
        history = TargetHistory()
        history.position = position
        target_state = {"CZBIL": serialize_target_history(history)}

        decisions = simulate_scans(
            query,
            price_series=[530.0],
            execution_mode="live",
            strategy_type="Custom Query Sell",
            side="sell",
            qty=100,
            holding_qty=100,
            target_state=target_state,
        )
        self.assertEqual(decisions[0].action, "EXECUTE")
        self.assertEqual(decisions[0].reason_code, "POSITION_EXIT")
        self.assertIsNone(decisions[0].qty)
        self.assertEqual(decisions[0].order_mode, "percent_of_holding")
        self.assertEqual(decisions[0].order_value, 50)

    def test_derived_52_week_position_buy(self):
        query = """
STRATEGY_VERSION 1
SIDE BUY
RULE "52W Position" FOR SYMBOL "CZBIL" {
    WHEN position_in_52_week_range_percent < 30
    ORDER QUANTITY 10
    EXECUTE ONCE
}
"""

        decisions = simulate_scans(
            query,
            price_series=[110.0],
            execution_mode="live",
            details_builder=lambda ltp, _: default_details(
                fifty_two_week_high=300.0,
                fifty_two_week_low=100.0,
            ),
        )
        self.assertEqual(decisions[0].action, "EXECUTE")

    def test_universe_percentile_fails_closed_without_context(self):
        query = """
STRATEGY_VERSION 1
SIDE BUY
RULE "Rank" FOR SYMBOL "CZBIL" {
    WHEN UNIVERSE_PERCENTILE(volume, operator=gte, threshold=80)
    ORDER QUANTITY 10
    EXECUTE ONCE
}
"""
        decisions = simulate_scans(query, price_series=[200.0], execution_mode="live")
        self.assertEqual(decisions[0].action, "TRACK")

    def test_symbol_not_in_plan_skips(self):
        query = """
STRATEGY_VERSION 1
SIDE BUY
RULE "Other" FOR SYMBOL "NABIL" {
    WHEN ltp <= 200
    ORDER QUANTITY 10
    EXECUTE ONCE
}
"""
        decisions = simulate_scans(query, price_series=[200.0], symbol="CZBIL", execution_mode="live")
        self.assertEqual(decisions[0].action, "SKIP")

    def test_changed_from_to_macd_signal_executes_on_transition(self):
        query = """
STRATEGY_VERSION 1
SIDE BUY
RULE "MACD Flip" FOR SYMBOL "CZBIL" {
    WHEN technical_macd CHANGED FROM "Bearish" TO "Bullish"
    ORDER QUANTITY 25
    TRIGGER LEVEL
    EXECUTE ONCE
}
"""
        decisions = simulate_scans(
            query,
            price_series=[200.0, 200.0],
            execution_mode="live",
            details_builder=lambda _ltp, idx: default_details(
                macd_signal="Bearish" if idx == 0 else "Bullish",
            ),
        )
        self.assertEqual(decisions[0].action, "TRACK")
        self.assertEqual(decisions[1].action, "EXECUTE")
        self.assertEqual(decisions[1].qty, 25)

    def test_quantity_sizing(self):
        query = """
STRATEGY_VERSION 1
SIDE BUY
RULE "Qty" FOR SYMBOL "CZBIL" {
    WHEN ltp <= 200
    ORDER QUANTITY 75
    EXECUTE ONCE
}
"""
        decisions = simulate_scans(query, price_series=[200.0], execution_mode="live")
        self.assertEqual(decisions[0].action, "EXECUTE")
        self.assertEqual(decisions[0].qty, 75)

    def test_sell_all_available_defers_quantity_to_execution(self):
        query = """
STRATEGY_VERSION 1
SIDE SELL
RULE "Liquidate" FOR SYMBOL "CZBIL" {
    WHEN ltp >= 200
    ORDER ALL_AVAILABLE
    EXECUTE ONCE
}
"""
        decisions = simulate_scans(
            query,
            price_series=[200.0],
            execution_mode="live",
            strategy_type="Custom Query Sell",
            side="sell",
            qty=100,
            holding_qty=80,
        )
        self.assertEqual(decisions[0].action, "EXECUTE")
        self.assertIsNone(decisions[0].qty)
        self.assertEqual(decisions[0].order_mode, "all_available")

    def test_sell_rule_with_zero_holding_still_evaluates_as_track(self):
        query = """
STRATEGY_VERSION 1
SIDE SELL
RULE "Sell" FOR SYMBOL "CZBIL" {
    WHEN ltp >= 200
    ORDER QUANTITY 10
    EXECUTE ONCE
}
"""
        decisions = simulate_scans(
            query,
            price_series=[200.0],
            execution_mode="live",
            strategy_type="Custom Query Sell",
            side="sell",
            qty=10,
            holding_qty=0,
        )
        self.assertEqual(decisions[0].action, "EXECUTE")
        self.assertEqual(decisions[0].qty, 10)


if __name__ == "__main__":
    unittest.main()
