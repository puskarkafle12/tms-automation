import unittest

from utils.strategies.handlers import HANDLERS
from utils.strategies.strategy_query_catalog import (
    DELEGATABLE_STRATEGIES,
    build_order_context_from_rule,
    get_delegatable_strategies,
    is_delegatable_strategy,
    map_strategy_params_to_order_fields,
    normalize_query_param_name,
    resolve_strategy_name,
    validate_strategy_params,
)


class StrategyQueryCatalogTest(unittest.TestCase):
    def test_all_delegatable_strategies_have_catalog_entries(self):
        self.assertEqual(len(DELEGATABLE_STRATEGIES), 14)
        buy = get_delegatable_strategies("buy")
        sell = get_delegatable_strategies("sell")
        self.assertEqual(len(buy), 7)
        self.assertEqual(len(sell), 7)

    def test_rule_based_strategies_are_not_delegatable(self):
        self.assertFalse(is_delegatable_strategy("Custom Query Buy", "buy"))
        self.assertFalse(is_delegatable_strategy("Technical Sell", "sell"))

    def test_alias_resolution(self):
        self.assertEqual(resolve_strategy_name("Dip Buy", "buy"), "Smart Pullback Buy")
        self.assertEqual(resolve_strategy_name("Emergency Exit", "sell"), "Emergency Exit by Top Buyer")

    def test_param_alias_normalization(self):
        self.assertEqual(normalize_query_param_name("price"), "TARGET_PRICE")
        self.assertEqual(normalize_query_param_name("STOP_LOSS"), "STOP_LOSS_PRICE")

    def test_fixed_price_buy_requires_target_price(self):
        issues = validate_strategy_params("Fixed Price Buy", {}, side="buy")
        self.assertTrue(any(item.code == "MISSING_STRATEGY_PARAM" for item in issues))

        mapped, map_issues = map_strategy_params_to_order_fields(
            "Fixed Price Buy",
            {"TARGET_PRICE": 532},
            side="buy",
        )
        self.assertEqual(map_issues, [])
        self.assertEqual(mapped["target_price"], 532.0)

    def test_capital_protection_requires_stop_or_average(self):
        issues = validate_strategy_params("Capital Protection Sell", {}, side="sell")
        self.assertTrue(any(item.code == "MISSING_STRATEGY_PARAM" for item in issues))

    def test_profit_ladder_maps_partial_legs(self):
        mapped, issues = map_strategy_params_to_order_fields(
            "Profit Ladder Sell",
            {
                "FIRST_TARGET": 720,
                "FIRST_PERCENT": 50,
                "SECOND_TARGET": 780,
                "SECOND_PERCENT": 50,
            },
            side="sell",
        )
        self.assertEqual(issues, [])
        self.assertEqual(len(mapped["partial_legs"]), 2)
        self.assertEqual(mapped["partial_legs"][0]["targetPrice"], 720.0)

    def test_build_order_context_from_rule_dict(self):
        rule = {
            "use_strategy": "Fixed Price Buy",
            "strategy_params": {"TARGET_PRICE": 500},
        }
        ctx, issues = build_order_context_from_rule(
            rule,
            plan_side="BUY",
            symbol="NABIL",
            qty=100,
        )
        self.assertEqual(issues, [])
        self.assertIsNotNone(ctx)
        assert ctx is not None
        self.assertEqual(ctx.canonical_strategy, "Fixed Price Buy")
        self.assertEqual(ctx.target_price, 500.0)
        self.assertEqual(ctx.symbol, "NABIL")

    def test_handlers_cover_catalog_except_time_based(self):
        for name in DELEGATABLE_STRATEGIES:
            if name in {"Time-Based Buy", "Time-Based Exit"}:
                continue
            self.assertIn(name, HANDLERS)


if __name__ == "__main__":
    unittest.main()
