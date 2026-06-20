import unittest

from utils.strategy_builder.derived_fields import compute_position_performance_fields, enrich_flat_snapshot
from utils.strategy_builder.execution_sizing import resolve_order_quantity
from utils.strategy_builder.history_service import TargetHistory, append_observation, changed_from_to, consecutive_moves
from utils.strategy_builder.math_stats import rolling_slope, rolling_stddev, trend_direction
from utils.strategy_builder.rule_evaluator import evaluate_expression
from utils.strategy_builder.strategy_parser import parse_strategy_query


class DerivedFieldsTest(unittest.TestCase):
    def test_profit_percent(self):
        flat = {"ltp": 520}
        position = {"entry_price": 500, "highest_price_since_entry": 530, "entry_at": "2026-01-01T10:00:00+00:00"}
        metrics = compute_position_performance_fields(flat, position, qty=10)
        self.assertAlmostEqual(metrics["profit_percent"], 4.0)
        self.assertAlmostEqual(metrics["drawdown_from_peak_percent"], ((520 - 530) / 530) * 100)


class ExecutionSizingTest(unittest.TestCase):
    def test_risk_percent_sizing(self):
        qty = resolve_order_quantity(
            order_mode="risk_percent",
            order_value=1,
            ltp=500,
            available_cash=100000,
            entry_price=500,
            stop_loss_price=450,
            board_lot=1,
        )
        self.assertEqual(qty, 20)


class RuntimeFunctionsTest(unittest.TestCase):
    def test_stddev_slope_trend(self):
        values = [100.0, 101.0, 102.0, 103.0, 104.0]
        self.assertGreater(rolling_slope(values), 0)
        self.assertEqual(trend_direction(values), "UP")
        self.assertGreater(rolling_stddev(values), 0)

    def test_changed_from_to(self):
        history = TargetHistory()
        history.previous_enum_values["technical_macd"] = "Bearish"
        history.previous_values["technical_macd"] = "Bullish"
        self.assertTrue(changed_from_to("technical_macd", history, "Bearish", "Bullish"))

    def test_min_total_change_pct(self):
        history = TargetHistory()
        for value in (200, 198, 193):
            append_observation(history, "ltp", value, source_timestamp=f"t-{value}", policy="count_only_new_trade")
        self.assertFalse(consecutive_moves("ltp", history, direction="drop", count=2, min_total_change_pct=5))
        self.assertTrue(consecutive_moves("ltp", history, direction="drop", count=2, min_total_change_pct=1))

    def test_parses_eligibility_signal_blocks(self):
        plan = parse_strategy_query(
            'STRATEGY_VERSION 1\nSIDE BUY\nRULE "A" FOR SYMBOL "CZBIL" {\n'
            "ELIGIBILITY volume > 1000\n"
            "SIGNAL technical_rsi_14 < 70\n"
            "ORDER QUANTITY 10\n}"
        )
        self.assertIsNotNone(plan.rules[0].eligibility)
        self.assertIsNotNone(plan.rules[0].signal)

    def test_depth_imbalance_expression(self):
        flat = {
            "buy_levels": [{"quantity": 300}, {"quantity": 200}],
            "sell_levels": [{"quantity": 100}, {"quantity": 100}],
        }
        node = {
            "type": "function",
            "name": "DEPTH_IMBALANCE",
            "arguments": {"levels": {"type": "literal", "value": 2}},
        }
        result = evaluate_expression(node, flat, TargetHistory())
        self.assertTrue(result.matched)
        self.assertAlmostEqual(result.actual_value, 300 / 700)


if __name__ == "__main__":
    unittest.main()
