import unittest

from utils.strategy_builder.reference_dependencies import plan_uses_reference
from utils.strategy_builder.strategy_parser import parse_strategy_query
from utils.strategy_builder.strategy_validator import validate_strategy_plan


class ReferenceRegressionTest(unittest.TestCase):
    def test_literal_trigger_query_has_no_reference_nodes(self):
        plan = parse_strategy_query(
            'STRATEGY_VERSION 1\nSIDE BUY\nRULE "A" FOR SYMBOL "API" {\n'
            "WHEN ltp <= 500\nORDER QUANTITY 10\n}"
        )
        self.assertFalse(plan_uses_reference(plan))
        result = validate_strategy_plan(plan, strategy_type="Custom Query Buy", form_symbol="API")
        self.assertFalse(any(item.code == "UNKNOWN_FIELD" and "trigger_price" in item.message for item in result.errors))

    def test_unknown_trigger_price_field_rejected(self):
        plan = parse_strategy_query(
            'STRATEGY_VERSION 1\nSIDE BUY\nRULE "A" FOR SYMBOL "API" {\n'
            "WHEN ltp <= trigger_price\nORDER QUANTITY 10\n}"
        )
        result = validate_strategy_plan(plan, strategy_type="Custom Query Buy", form_symbol="API")
        self.assertTrue(any(item.code == "UNKNOWN_FIELD" for item in result.errors))

    def test_reference_query_validates_without_server_error_codes(self):
        plan = parse_strategy_query(
            'STRATEGY_VERSION 1\nSIDE BUY\nRULE "A" FOR SYMBOL "API" {\n'
            "WHEN ltp <= REFERENCE(field=ltp) * 0.90\nORDER QUANTITY 10\n}"
        )
        result = validate_strategy_plan(plan, strategy_type="Custom Query Buy", form_symbol="API")
        self.assertFalse(any(item.code.startswith("INTERNAL") for item in result.errors))


if __name__ == "__main__":
    unittest.main()
