import unittest

from utils.strategy_builder.strategy_parser import format_strategy_query, parse_strategy_query


FIXED_PRICE_QUERY = """STRATEGY_VERSION 1
SIDE BUY

RULE "NABIL Fixed" FOR SYMBOL "NABIL" {
    USE STRATEGY "Fixed Price Buy"
    TARGET_PRICE 532
    ORDER QUANTITY 100
    EXECUTE ONCE PER SYMBOL
}"""

COMBINED_QUERY = """STRATEGY_VERSION 1
SIDE BUY

RULE "EBL Quality" FOR SYMBOL "EBL" {
    USE STRATEGY "Quality Pullback Recovery Buy"
    MIN_BUY_SCORE 65
    ELIGIBILITY technical_rsi_14 BETWEEN 30 AND 50
    ORDER QUANTITY 50
    EXECUTE ONCE PER SYMBOL
}"""

CAPITAL_PROTECTION_QUERY = """STRATEGY_VERSION 1
SIDE SELL

RULE "NABIL Protect" FOR SYMBOL "NABIL" {
    USE STRATEGY "Capital Protection Sell"
    STOP_LOSS_PRICE 480
    TRAILING_DROP_PCT 3
    ORDER PERCENT_OF_HOLDING 100
    EXECUTE ONCE PER SYMBOL
}"""


class StrategyDelegationParserTest(unittest.TestCase):
    def test_parse_use_strategy_rule(self):
        plan = parse_strategy_query(FIXED_PRICE_QUERY)
        rule = plan.rules[0]
        self.assertEqual(rule.use_strategy, "Fixed Price Buy")
        self.assertEqual(rule.strategy_params["TARGET_PRICE"], 532.0)
        self.assertEqual(rule.symbols, ["NABIL"])

    def test_parse_combined_eligibility_and_strategy(self):
        plan = parse_strategy_query(COMBINED_QUERY)
        rule = plan.rules[0]
        self.assertEqual(rule.use_strategy, "Quality Pullback Recovery Buy")
        self.assertEqual(rule.strategy_params["MIN_BUY_SCORE"], 65.0)
        self.assertIsNotNone(rule.eligibility)

    def test_format_round_trip_fixed_price(self):
        plan = parse_strategy_query(FIXED_PRICE_QUERY)
        formatted = format_strategy_query(plan)
        reparsed = parse_strategy_query(formatted)
        self.assertEqual(reparsed.rules[0].use_strategy, "Fixed Price Buy")
        self.assertEqual(reparsed.rules[0].strategy_params["TARGET_PRICE"], 532.0)

    def test_parse_alias_strategy_name(self):
        query = """STRATEGY_VERSION 1
SIDE BUY
RULE "A" FOR SYMBOL "NABIL" {
    USE STRATEGY "Dip Buy"
    TARGET_PRICE 100
    ORDER QUANTITY 10
}"""
        plan = parse_strategy_query(query)
        self.assertEqual(plan.rules[0].use_strategy, "Dip Buy")

    def test_parse_emergency_confirmed_boolean(self):
        query = """STRATEGY_VERSION 1
SIDE SELL
RULE "A" FOR SYMBOL "NABIL" {
    USE STRATEGY "Emergency Exit by Top Buyer"
    EMERGENCY_CONFIRMED TRUE
    ORDER QUANTITY 100
}"""
        plan = parse_strategy_query(query)
        self.assertTrue(plan.rules[0].strategy_params["EMERGENCY_CONFIRMED"])

    def test_parse_capital_protection_params(self):
        plan = parse_strategy_query(CAPITAL_PROTECTION_QUERY)
        params = plan.rules[0].strategy_params
        self.assertEqual(params["STOP_LOSS_PRICE"], 480.0)
        self.assertEqual(params["TRAILING_DROP_PCT"], 3.0)


if __name__ == "__main__":
    unittest.main()
