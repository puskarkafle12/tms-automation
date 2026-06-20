import unittest

from utils.strategy_builder.plan_helpers import extract_planned_quantity_from_compiled_plan
from utils.strategy_builder.strategy_parser import parse_strategy_query


class PlanHelpersTest(unittest.TestCase):
    def test_extract_planned_quantity_from_order_quantity_rule(self):
        plan = parse_strategy_query(
            'STRATEGY_VERSION 1\nSIDE BUY\nRULE "CZBIL Rule" FOR SYMBOL "CZBIL" {\n'
            "WHEN technical_rsi_14 < 70\nORDER QUANTITY 100\n}"
        )
        qty = extract_planned_quantity_from_compiled_plan(plan.model_dump(), "CZBIL")
        self.assertEqual(qty, 100)

    def test_extract_planned_quantity_respects_symbol_filter(self):
        plan = parse_strategy_query(
            'STRATEGY_VERSION 1\nSIDE BUY\n'
            'RULE "A" FOR SYMBOL "AAA" { WHEN ltp > 0 ORDER QUANTITY 10 }\n'
            'RULE "B" FOR SYMBOL "BBB" { WHEN ltp > 0 ORDER QUANTITY 20 }'
        )
        self.assertEqual(extract_planned_quantity_from_compiled_plan(plan.model_dump(), "BBB"), 20)
        self.assertEqual(extract_planned_quantity_from_compiled_plan(plan.model_dump(), "AAA"), 10)

    def test_extract_planned_quantity_ignores_amount_mode(self):
        plan = parse_strategy_query(
            'STRATEGY_VERSION 1\nSIDE BUY\nRULE "A" FOR SYMBOL "CZBIL" {\n'
            "WHEN technical_rsi_14 < 70\nORDER AMOUNT 50000\n}"
        )
        self.assertIsNone(extract_planned_quantity_from_compiled_plan(plan.model_dump(), "CZBIL"))

    def test_extract_planned_quantity_defaults_to_ten_when_missing(self):
        plan = parse_strategy_query(
            'STRATEGY_VERSION 1\nSIDE BUY\nRULE "A" FOR SYMBOL "CZBIL" {\n'
            "WHEN technical_rsi_14 < 70\n}"
        )
        self.assertEqual(extract_planned_quantity_from_compiled_plan(plan.model_dump(), "CZBIL"), 10)


if __name__ == "__main__":
    unittest.main()
