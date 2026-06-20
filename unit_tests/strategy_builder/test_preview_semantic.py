import unittest

from utils.strategy_builder.preview_builder import (
    _estimate_price_boundary,
    build_quantity_preview,
    build_rule_preview,
    build_trigger_preview,
    format_preview_value,
)
from utils.strategy_builder.rule_evaluator import evaluate_rule, update_history_from_snapshot
from utils.strategy_builder.strategy_parser import parse_strategy_query
from utils.strategy_builder.history_service import TargetHistory


SELL_52W_QUERY = """STRATEGY_VERSION 1
SIDE SELL
RULE "Sell 100 Percent At 52 Week High" FOR SYMBOL "API" {
    WHEN position_in_52_week_range_percent >= 95
    ORDER PERCENT_OF_HOLDING 100
    CONFIRM TRUE_FOR 2 SCANS
    TRIGGER LEVEL
    MAX_SLIPPAGE_PCT 1
    EXECUTE ONCE PER SYMBOL
}
"""

LTP_QUERY = """STRATEGY_VERSION 1
SIDE BUY
RULE "Buy" FOR SYMBOL "API" {
    WHEN ltp >= 500
    ORDER QUANTITY 100
    EXECUTE ONCE
}
"""

RSI_QUERY = """STRATEGY_VERSION 1
SIDE BUY
RULE "RSI" FOR SYMBOL "API" {
    WHEN technical_rsi_14 <= 30
    ORDER QUANTITY 100
    EXECUTE ONCE
}
"""


class PreviewBuilderTest(unittest.TestCase):
    def test_52_week_position_price_calculation(self):
        flat = {"fifty_two_week_low": 250.0, "fifty_two_week_high": 400.0}
        price, is_exact, warnings = _estimate_price_boundary(
            "position_in_52_week_range_percent",
            "gte",
            95.0,
            flat,
        )
        self.assertAlmostEqual(price, 392.5)
        self.assertFalse(is_exact)
        self.assertEqual(warnings, [])

    def test_percent_not_formatted_as_price(self):
        rendered = format_preview_value("position_in_52_week_range_percent", 95)
        self.assertIn("%", rendered)
        self.assertNotIn("Rs.", rendered)

    def test_52_week_strategy_trigger_preview(self):
        plan = parse_strategy_query(SELL_52W_QUERY)
        rule = plan.rules[0]
        flat = {
            "position_in_52_week_range_percent": 81.8,
            "fifty_two_week_low": 250.0,
            "fifty_two_week_high": 400.0,
            "ltp": 343.0,
        }
        history = TargetHistory()
        update_history_from_snapshot(history, flat)
        evaluation = evaluate_rule(rule, "API", flat, history, trigger_on_cross=False)
        trigger = build_trigger_preview(rule, flat, evaluation)
        self.assertIn("52-week range position", trigger.strategy_text)
        self.assertIn("%", trigger.target_display or "")
        self.assertAlmostEqual(trigger.estimated_price or 0, 392.5, places=1)
        self.assertFalse(trigger.is_exact_price)

    def test_direct_ltp_trigger_is_exact_price(self):
        plan = parse_strategy_query(LTP_QUERY)
        rule = plan.rules[0]
        flat = {"ltp": 480.0}
        history = TargetHistory()
        evaluation = evaluate_rule(rule, "API", flat, history, trigger_on_cross=False)
        trigger = build_trigger_preview(rule, flat, evaluation)
        self.assertTrue(trigger.is_exact_price)
        self.assertEqual(trigger.estimated_price, 500.0)

    def test_rsi_has_no_price_estimate(self):
        plan = parse_strategy_query(RSI_QUERY)
        rule = plan.rules[0]
        flat = {"technical_rsi_14": 42.1}
        history = TargetHistory()
        evaluation = evaluate_rule(rule, "API", flat, history, trigger_on_cross=False)
        trigger = build_trigger_preview(rule, flat, evaluation)
        self.assertIsNone(trigger.estimated_price)
        self.assertIn("RSI", trigger.strategy_text)

    def test_percent_of_holding_quantity_preview_not_final(self):
        plan = parse_strategy_query(SELL_52W_QUERY)
        rule = plan.rules[0]
        quantity = build_quantity_preview(
            rule,
            plan_side="SELL",
            flat={"ltp": 343.0},
            current_holding=222,
        )
        self.assertEqual(quantity.estimated_quantity, 222)
        self.assertFalse(quantity.is_final)
        self.assertIn("recalculated", (quantity.note or "").lower())

    def test_holding_retrieval_failure_shows_unavailable(self):
        plan = parse_strategy_query(SELL_52W_QUERY)
        rule = plan.rules[0]
        quantity = build_quantity_preview(
            rule,
            plan_side="SELL",
            flat={"ltp": 343.0},
            current_holding=None,
            holding_retrieval_failed=True,
        )
        self.assertEqual(quantity.estimated_quantity_display, "Unavailable")
        self.assertTrue(any(item.code == "HOLDING_UNAVAILABLE" for item in quantity.warnings))

    def test_missing_52_week_range_still_has_strategy_text(self):
        plan = parse_strategy_query(SELL_52W_QUERY)
        rule = plan.rules[0]
        flat = {"position_in_52_week_range_percent": 81.8, "ltp": 343.0}
        history = TargetHistory()
        evaluation = evaluate_rule(rule, "API", flat, history, trigger_on_cross=False)
        trigger = build_trigger_preview(rule, flat, evaluation)
        self.assertIn("52-week range position", trigger.strategy_text)
        self.assertIsNone(trigger.estimated_price)
        self.assertEqual(trigger.estimated_price_display, "Unavailable")

    def test_build_rule_preview_includes_confirmation(self):
        plan = parse_strategy_query(SELL_52W_QUERY)
        rule = plan.rules[0]
        flat = {
            "position_in_52_week_range_percent": 81.8,
            "fifty_two_week_low": 250.0,
            "fifty_two_week_high": 400.0,
            "ltp": 343.0,
        }
        history = TargetHistory()
        evaluation = evaluate_rule(rule, "API", flat, history, trigger_on_cross=False)
        preview = build_rule_preview(
            rule=rule,
            symbol="API",
            plan_side="SELL",
            flat=flat,
            evaluation=evaluation,
            history=history,
            status_label="Waiting",
            live_ltp=343.0,
            reference_ltp=None,
            current_holding=54,
        )
        self.assertIsNotNone(preview.confirmation)
        assert preview.confirmation is not None
        self.assertIn("scan", preview.confirmation.display.lower())
        self.assertEqual(preview.quantity.estimated_quantity, 54)


if __name__ == "__main__":
    unittest.main()
