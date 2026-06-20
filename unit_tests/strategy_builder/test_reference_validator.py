import unittest

from utils.strategy_builder.reference_validator import validate_reference_expressions
from utils.strategy_builder.strategy_parser import parse_strategy_query


class ReferenceValidatorTest(unittest.TestCase):
    def test_rejects_unknown_reference_source(self):
        plan = parse_strategy_query(
            'STRATEGY_VERSION 1\nSIDE BUY\nRULE "A" FOR SYMBOL "API" {\n'
            "WHEN ltp <= REFERENCE(field=trigger_price)\nORDER QUANTITY 10\n}"
        )
        errors = validate_reference_expressions(plan)
        self.assertTrue(any(item.code == "REFERENCE_FIELD_UNKNOWN" for item in errors))

    def test_rejects_position_field_reference(self):
        plan = parse_strategy_query(
            'STRATEGY_VERSION 1\nSIDE SELL\nRULE "A" FOR SYMBOL "API" {\n'
            "WHEN ltp <= REFERENCE(field=entry_price)\nORDER QUANTITY 10\n}"
        )
        errors = validate_reference_expressions(plan)
        self.assertTrue(any(item.code == "REFERENCE_FIELD_NOT_ALLOWED" for item in errors))

    def test_rejects_temporal_on_reference(self):
        plan = parse_strategy_query(
            'STRATEGY_VERSION 1\nSIDE BUY\nRULE "A" FOR SYMBOL "API" {\n'
            "WHEN PREVIOUS(field=REFERENCE(field=ltp), count=1) > 0\nORDER QUANTITY 10\n}"
        )
        errors = validate_reference_expressions(plan)
        self.assertTrue(any(item.code == "REFERENCE_TEMPORAL_USE_INVALID" for item in errors))


if __name__ == "__main__":
    unittest.main()
