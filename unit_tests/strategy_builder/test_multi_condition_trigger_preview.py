import unittest

from utils.strategy_builder.history_service import TargetHistory
from utils.strategy_builder.preview_builder import build_trigger_preview
from utils.strategy_builder.reference_store import ReferenceRow, ReferenceStore
from utils.strategy_builder.rule_evaluator import evaluate_rule, update_history_from_snapshot
from utils.strategy_builder.strategy_parser import parse_strategy_query


def _preview_trigger(
    query: str,
    *,
    symbol: str,
    flat: dict,
    reference_ltp: float | None = None,
    rule_name: str | None = None,
):
    plan = parse_strategy_query(query)
    rule = plan.rules[0]
    resolved_rule_name = rule_name or rule.name
    history = TargetHistory()
    update_history_from_snapshot(history, flat)
    store = None
    if reference_ltp is not None:
        store = ReferenceStore.from_rows(
            [
                ReferenceRow(
                    rule_name=resolved_rule_name,
                    symbol=symbol,
                    field_key="ltp",
                    field_type="decimal",
                    numeric_value=float(reference_ltp),
                )
            ]
        )
    evaluation = evaluate_rule(
        rule,
        symbol,
        flat,
        history,
        trigger_on_cross=False,
        reference_store=store,
    )
    return build_trigger_preview(rule, flat, evaluation), evaluation


class MultiConditionTriggerPreviewTest(unittest.TestCase):
    def test_or_reference_dual_targets(self):
        query = """STRATEGY_VERSION 1
SIDE SELL
RULE "Profit Or Stop" FOR SYMBOL "HIDCL" {
    WHEN ltp >= REFERENCE(field=ltp) * 1.10
        OR ltp <= REFERENCE(field=ltp) * 0.95
    ORDER PERCENT_OF_HOLDING 100
    EXECUTE ONCE PER SYMBOL
}"""
        trigger, _ = _preview_trigger(
            query,
            symbol="HIDCL",
            flat={"ltp": 246.0},
            reference_ltp=246.0,
        )
        self.assertTrue(trigger.estimated_price_available)
        self.assertAlmostEqual(trigger.estimated_price or 0, 270.6, places=1)
        self.assertIn("/", trigger.estimated_price_display or "")
        prices = sorted(item.estimated_price for item in trigger.conditions or [] if item.estimated_price)
        self.assertEqual(prices, [233.7, 270.6])

    def test_nested_or_with_require_volume_gate(self):
        query = """STRATEGY_VERSION 1
SIDE SELL
RULE "Or With Require" FOR SYMBOL "HIDCL" {
    WHEN ltp >= REFERENCE(field=ltp) * 1.10
        OR ltp <= REFERENCE(field=ltp) * 0.95
    REQUIRE volume > 1000
    ORDER PERCENT_OF_HOLDING 100
    EXECUTE ONCE PER SYMBOL
}"""
        trigger, evaluation = _preview_trigger(
            query,
            symbol="HIDCL",
            flat={"ltp": 246.0, "volume": 5000},
            reference_ltp=246.0,
        )
        self.assertTrue(trigger.estimated_price_available)
        self.assertIn("/", trigger.estimated_price_display or "")
        self.assertGreaterEqual(len(evaluation.conditions), 3)

    def test_and_with_two_literal_ltp_levels(self):
        query = """STRATEGY_VERSION 1
SIDE BUY
RULE "Band Buy" FOR SYMBOL "API" {
    WHEN ltp >= 480 AND ltp <= 520
    ORDER QUANTITY 10
    EXECUTE ONCE
}"""
        trigger, _ = _preview_trigger(
            query,
            symbol="API",
            flat={"ltp": 500.0},
        )
        self.assertTrue(trigger.estimated_price_available)
        prices = [item.estimated_price for item in trigger.conditions or [] if item.estimated_price is not None]
        self.assertEqual(prices, [480.0, 520.0])
        self.assertIn("/", trigger.estimated_price_display or "")

    def test_single_reference_profit_target(self):
        query = """STRATEGY_VERSION 1
SIDE SELL
RULE "Ten Percent Gain" FOR SYMBOL "HDL" {
    WHEN ltp >= REFERENCE(field=ltp) * 1.10
    ORDER PERCENT_OF_HOLDING 100
    EXECUTE ONCE PER SYMBOL
}"""
        trigger, _ = _preview_trigger(
            query,
            symbol="HDL",
            flat={"ltp": 1000.0},
            reference_ltp=1000.0,
        )
        self.assertAlmostEqual(trigger.estimated_price or 0, 1100.0, places=2)
        self.assertTrue(trigger.is_exact_price)

    def test_or_mixed_price_and_non_price_keeps_price_estimate(self):
        query = """STRATEGY_VERSION 1
SIDE BUY
RULE "Mixed OR" FOR SYMBOL "API" {
    WHEN ltp <= 450 OR technical_rsi_14 <= 30
    ORDER QUANTITY 10
    EXECUTE ONCE
}"""
        trigger, _ = _preview_trigger(
            query,
            symbol="API",
            flat={"ltp": 500.0, "technical_rsi_14": 42.0},
        )
        self.assertTrue(trigger.estimated_price_available)
        self.assertEqual(trigger.estimated_price, 450.0)
        rsi_condition = (trigger.conditions or [])[1]
        self.assertIsNone(rsi_condition.estimated_price)

    def test_eligibility_reference_with_non_price_signal(self):
        query = """STRATEGY_VERSION 1
SIDE BUY
RULE "Pullback RSI" FOR SYMBOL "NABIL" {
    ELIGIBILITY ltp <= REFERENCE(field=ltp) * 0.99
    SIGNAL technical_rsi_14 BETWEEN 20 AND 60
    ORDER QUANTITY 10
    EXECUTE ONCE PER SYMBOL
}"""
        trigger, _ = _preview_trigger(
            query,
            symbol="NABIL",
            flat={"ltp": 490.0, "technical_rsi_14": 42.0, "volume": 1000},
            reference_ltp=500.0,
        )
        self.assertAlmostEqual(trigger.estimated_price or 0, 495.0, places=2)

    def test_three_way_or_reference_targets(self):
        query = """STRATEGY_VERSION 1
SIDE SELL
RULE "Triple Exit" FOR SYMBOL "API" {
    WHEN ltp >= REFERENCE(field=ltp) * 1.10
        OR ltp <= REFERENCE(field=ltp) * 0.95
        OR ltp >= REFERENCE(field=ltp) * 1.20
    ORDER PERCENT_OF_HOLDING 100
    EXECUTE ONCE PER SYMBOL
}"""
        trigger, _ = _preview_trigger(
            query,
            symbol="API",
            flat={"ltp": 100.0},
            reference_ltp=100.0,
        )
        prices = sorted(item.estimated_price for item in trigger.conditions or [] if item.estimated_price)
        self.assertEqual(len(prices), 3)
        self.assertAlmostEqual(prices[0], 95.0, places=2)
        self.assertAlmostEqual(prices[1], 110.0, places=2)
        self.assertAlmostEqual(prices[2], 120.0, places=2)
        self.assertEqual(len((trigger.estimated_price_display or "").split("/")), 3)


if __name__ == "__main__":
    unittest.main()
