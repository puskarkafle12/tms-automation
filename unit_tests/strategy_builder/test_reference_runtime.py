import unittest

from utils.strategy_builder.history_service import TargetHistory
from utils.strategy_builder.reference_store import ReferenceEvaluationError, ReferenceRow, ReferenceStore
from utils.strategy_builder.rule_evaluator import evaluate_rule
from utils.strategy_builder.strategy_models import RuleBlock
from utils.strategy_builder.strategy_parser import parse_strategy_query


QUERY = """STRATEGY_VERSION 1
SIDE BUY
RULE "Pullback" FOR SYMBOL "API" {
    WHEN ltp <= REFERENCE(field=ltp) * 0.90
    ORDER QUANTITY 10
}"""


class ReferenceRuntimeTest(unittest.TestCase):
    def _store(self, ref_ltp: float) -> ReferenceStore:
        return ReferenceStore.from_rows(
            [
                ReferenceRow(
                    rule_name="Pullback",
                    symbol="API",
                    field_key="ltp",
                    field_type="decimal",
                    numeric_value=ref_ltp,
                )
            ]
        )

    def test_live_ltp_changes_but_reference_stays_fixed(self):
        plan = parse_strategy_query(QUERY)
        rule = RuleBlock.model_validate(plan.rules[0].model_dump())
        store = self._store(500.0)
        history = TargetHistory()

        matched_low = evaluate_rule(rule, "API", {"ltp": 440.0}, history, reference_store=store)
        self.assertTrue(matched_low.matched)

        not_matched_high = evaluate_rule(rule, "API", {"ltp": 460.0}, history, reference_store=store)
        self.assertFalse(not_matched_high.matched)

    def test_missing_reference_raises(self):
        plan = parse_strategy_query(QUERY)
        rule = RuleBlock.model_validate(plan.rules[0].model_dump())
        with self.assertRaises(ReferenceEvaluationError) as ctx:
            evaluate_rule(rule, "API", {"ltp": 440.0}, TargetHistory(), reference_store=None)
        self.assertEqual(ctx.exception.code, "REFERENCE_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
