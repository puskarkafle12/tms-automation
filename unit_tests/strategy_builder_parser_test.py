import unittest

from utils.strategy_builder.strategy_parser import (
    StrategyQueryError,
    extract_symbols_from_query,
    format_expression,
    format_strategy_query,
    parse_strategy_query,
)
from utils.strategy_builder.strategy_validator import validate_strategy_plan


SAMPLE_SELL_QUERY = """
STRATEGY_VERSION 1
SIDE SELL

RULE "CZBIL Confirmed Drop" FOR SYMBOL "CZBIL" {
    WHEN technical_rsi_14 < 70
         AND CONSECUTIVE_DROPS(ltp, count=2)

    ORDER PERCENT_OF_HOLDING 100
    MAX_SLIPPAGE_PCT 1
    EXECUTE ONCE
}
"""


class StrategyBuilderParserTest(unittest.TestCase):
    def test_parse_single_stock_sell_query(self):
        plan = parse_strategy_query(SAMPLE_SELL_QUERY)
        self.assertEqual(plan.side, "SELL")
        self.assertEqual(plan.rules[0].symbols, ["CZBIL"])
        self.assertEqual(plan.rules[0].order.mode, "percent_of_holding")
        self.assertEqual(plan.rules[0].order.value, 100.0)
        self.assertEqual(plan.rules[0].execution.frequency, "once")

    def test_reject_sql_injection_outside_strings(self):
        with self.assertRaises(StrategyQueryError):
            parse_strategy_query('STRATEGY_VERSION 1\nSIDE BUY\nSELECT * FROM users')

    def test_validate_form_symbol_warning(self):
        plan = parse_strategy_query(SAMPLE_SELL_QUERY)
        result = validate_strategy_plan(plan, strategy_type="Custom Query Sell", form_symbol="AKJCL")
        self.assertTrue(any(item.code == "FORM_SYMBOL_NOT_TARGETED" for item in result.warnings))

    def test_extract_symbols_from_multi_stock_query(self):
        query = """
STRATEGY_VERSION 1
SIDE BUY
RULE "Multi" FOR SYMBOL IN ("ACLBSL", "CZBIL") {
    WHEN technical_rsi_14 > 30
    ORDER QUANTITY 100
}
"""
        self.assertEqual(extract_symbols_from_query(query), ["ACLBSL", "CZBIL"])

    def test_format_expression_renders_reference_arithmetic(self):
        node = {
            "type": "comparison",
            "operator": "lte",
            "left": {"type": "field", "name": "ltp"},
            "right": {
                "type": "arithmetic",
                "operator": "*",
                "left": {
                    "type": "function",
                    "name": "REFERENCE",
                    "arguments": {"field": {"type": "field", "name": "ltp"}},
                },
                "right": {"type": "literal", "value": 0.9},
            },
        }
        rendered = format_expression(node)
        self.assertEqual(rendered, "ltp <= REFERENCE(field=ltp) * 0.9")

    def test_format_query_renders_comparison_operators(self):
        plan = parse_strategy_query(
            'STRATEGY_VERSION 1\nSIDE BUY\nRULE "A" FOR SYMBOL "CZBIL" {\n'
            "WHEN technical_rsi_14 > 30\nORDER QUANTITY 100\n}"
        )
        formatted = format_strategy_query(plan)
        self.assertIn("technical_rsi_14 > 30", formatted)
        self.assertNotIn("FieldNode", formatted)

    def test_rule_without_order_defaults_quantity_to_ten(self):
        plan = parse_strategy_query(
            'STRATEGY_VERSION 1\nSIDE BUY\nRULE "A" FOR SYMBOL "CZBIL" {\n'
            "WHEN technical_rsi_14 < 70\n}"
        )
        self.assertEqual(plan.rules[0].order.mode, "quantity")
        self.assertEqual(plan.rules[0].order.value, 10.0)

    def test_parse_multi_stock_query_with_arithmetic_and_require(self):
        query = """
STRATEGY_VERSION 1
SIDE BUY
RULE "NEPSE Technical Buy Between 200 And 300" FOR SYMBOL IN ("NABIL", "NMB") {
ELIGIBILITY technical_rsi_14 BETWEEN 30 AND 45 AND technical_macd = "Bullish"
SIGNAL ltp BETWEEN 200 AND 300
REQUIRE volume > 0 AND ltp <= ltp * 1.05
ORDER QUANTITY 10
CONFIRM TRUE_FOR 2 SCANS
TRIGGER LEVEL
EXECUTE ONCE PER SYMBOL
}
"""
        plan = parse_strategy_query(query)
        rule = plan.rules[0]
        self.assertEqual(len(rule.symbols), 2)
        self.assertEqual(rule.execution.frequency, "once_per_symbol")
        self.assertIsNotNone(rule.require)
        assert rule.require is not None
        self.assertEqual(rule.require.type, "group")


if __name__ == "__main__":
    unittest.main()
