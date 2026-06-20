import unittest

from utils.strategy_builder.strategy_models import OrderSizing, RuleBlock, StrategyPlanAST
from utils.strategy_builder.strategy_validator import validate_strategy_plan


def _plan(*rules: RuleBlock, side: str = "BUY") -> StrategyPlanAST:
    return StrategyPlanAST(version=1, side=side, rules=list(rules))


class StrategyDelegationValidatorTest(unittest.TestCase):
    def test_use_strategy_requires_known_name(self):
        plan = _plan(
            RuleBlock(
                rule_id="r1",
                name="Bad",
                symbols=["NABIL"],
                use_strategy="Not A Strategy",
                order=OrderSizing(mode="quantity", value=10),
            )
        )
        result = validate_strategy_plan(plan, strategy_type="Custom Query Buy")
        self.assertFalse(result.valid)
        self.assertTrue(any(item.code == "UNKNOWN_STRATEGY" for item in result.errors))

    def test_fixed_price_buy_requires_target_price(self):
        plan = _plan(
            RuleBlock(
                rule_id="r1",
                name="Fixed",
                symbols=["NABIL"],
                use_strategy="Fixed Price Buy",
                order=OrderSizing(mode="quantity", value=10),
            )
        )
        result = validate_strategy_plan(plan, strategy_type="Custom Query Buy")
        self.assertFalse(result.valid)
        self.assertTrue(any(item.code == "MISSING_STRATEGY_PARAM" for item in result.errors))

    def test_valid_fixed_price_buy_rule(self):
        plan = _plan(
            RuleBlock(
                rule_id="r1",
                name="Fixed",
                symbols=["NABIL"],
                use_strategy="Fixed Price Buy",
                strategy_params={"TARGET_PRICE": 532},
                order=OrderSizing(mode="quantity", value=10),
            )
        )
        result = validate_strategy_plan(plan, strategy_type="Custom Query Buy")
        self.assertTrue(result.valid)

    def test_side_mismatch_for_sell_strategy_on_buy_plan(self):
        plan = _plan(
            RuleBlock(
                rule_id="r1",
                name="Bad",
                symbols=["NABIL"],
                use_strategy="Capital Protection Sell",
                strategy_params={"STOP_LOSS_PRICE": 100},
                order=OrderSizing(mode="quantity", value=10),
            ),
            side="BUY",
        )
        result = validate_strategy_plan(plan, strategy_type="Custom Query Buy")
        self.assertFalse(result.valid)
        self.assertTrue(any(item.code == "STRATEGY_SIDE_MISMATCH" for item in result.errors))

    def test_rule_based_strategy_not_delegatable(self):
        plan = _plan(
            RuleBlock(
                rule_id="r1",
                name="Bad",
                symbols=["NABIL"],
                use_strategy="Custom Query Buy",
                order=OrderSizing(mode="quantity", value=10),
            )
        )
        result = validate_strategy_plan(plan, strategy_type="Custom Query Buy")
        self.assertFalse(result.valid)
        self.assertTrue(any(item.code in {"UNKNOWN_STRATEGY", "STRATEGY_NOT_DELEGATABLE"} for item in result.errors))


if __name__ == "__main__":
    unittest.main()
