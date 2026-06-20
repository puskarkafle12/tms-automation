import unittest

from utils.strategy_builder.reference_dependencies import collect_reference_fields_from_plan, plan_uses_reference
from utils.strategy_builder.strategy_parser import parse_strategy_query


REFERENCE_PULLBACK = """STRATEGY_VERSION 1
SIDE BUY
RULE "Pullback" FOR SYMBOL "API" {
    WHEN ltp <= REFERENCE(field=ltp) * 0.90
    ORDER QUANTITY 10
    EXECUTE ONCE PER SYMBOL
}"""


class ReferenceParserTest(unittest.TestCase):
    def test_parses_reference_with_arithmetic(self):
        plan = parse_strategy_query(REFERENCE_PULLBACK)
        self.assertTrue(plan_uses_reference(plan))
        per_rule = collect_reference_fields_from_plan(plan)
        self.assertEqual(per_rule["Pullback"], {"ltp"})
        when = plan.rules[0].when.model_dump()
        self.assertEqual(when["type"], "comparison")
        self.assertEqual(when["left"]["name"], "ltp")
        self.assertEqual(when["right"]["type"], "arithmetic")

    def test_parses_reference_availability_check(self):
        plan = parse_strategy_query(
            'STRATEGY_VERSION 1\nSIDE BUY\nRULE "A" FOR SYMBOL "API" {\n'
            "WHEN REFERENCE(field=ltp) IS AVAILABLE AND ltp > 0\nORDER QUANTITY 10\n}"
        )
        check = plan.rules[0].when.model_dump()
        self.assertEqual(check["type"], "group")
        availability = check["children"][0]
        self.assertEqual(availability["type"], "availability_check")
        self.assertEqual(availability["expression"]["name"], "REFERENCE")

    def test_positional_reference_argument_still_resolves_field(self):
        plan = parse_strategy_query(
            'STRATEGY_VERSION 1\nSIDE BUY\nRULE "A" FOR SYMBOL "API" {\n'
            "WHEN ltp <= REFERENCE(ltp)\nORDER QUANTITY 10\n}"
        )
        per_rule = collect_reference_fields_from_plan(plan)
        self.assertIn("ltp", per_rule["A"])


if __name__ == "__main__":
    unittest.main()
