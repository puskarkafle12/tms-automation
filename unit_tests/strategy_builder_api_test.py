import unittest

from utils.strategy_builder.constants import DEFAULT_RULE_ORDER_QUANTITY
from utils.strategy_builder.strategy_llm_prompt import build_strategy_query_llm_prompt, supported_catalog_fields
from utils.strategy_builder.strategy_parser import StrategyQueryError, parse_strategy_query


class StrategyBuilderApiHelpersTest(unittest.TestCase):
    def test_llm_prompt_includes_use_strategy_catalog(self):
        buy_prompt = build_strategy_query_llm_prompt(side="buy")
        sell_prompt = build_strategy_query_llm_prompt(side="sell")
        for token in (
            "USE STRATEGY",
            "USE STRATEGY (named portal strategies)",
            "NOT delegatable",
            "Custom Query Buy",
            "Custom Query Sell",
            "Technical Buy",
            "Technical Sell",
            "TARGET_PRICE",
            "STOP_LOSS_PRICE",
            "REFERENCE(field=ltp)",
            "Example 12 — REFERENCE schedule baseline",
            "Example 13 — USE STRATEGY multi-symbol buy basket",
            "Example 14 — USE STRATEGY sell capital protection",
            "Combine mode",
            "Parameter glossary",
            "Capital Protection Sell",
            "Quality Pullback Recovery Buy",
            "Fixed Price Buy",
        ):
            self.assertIn(token, buy_prompt, f"missing from buy prompt: {token}")
        self.assertIn("Profit Ladder Sell", sell_prompt)
        self.assertIn("Example 15 — USE STRATEGY profit ladder", sell_prompt)

    def test_llm_prompt_includes_side_and_symbol(self):
        prompt = build_strategy_query_llm_prompt(side="buy", form_symbol="CZBIL")
        self.assertIn("SIDE BUY", prompt)
        self.assertIn("CZBIL", prompt)
        self.assertIn("FOR SYMBOL", prompt)

    def test_llm_prompt_includes_latest_grammar_and_fields(self):
        prompt = build_strategy_query_llm_prompt(side="sell", form_symbol="CZBIL")
        for token in (
            "POSITION_EXIT",
            "ELIGIBILITY",
            "SIGNAL",
            "REQUIRE",
            "CONFIRM TRUE_FOR",
            "TRIGGER LEVEL",
            "RISK_PERCENT",
            "MAX_LOSS_AMOUNT",
            "ALL_AVAILABLE",
            "profit_percent",
            "HARD RULES",
            "FORBIDDEN",
            "market_depth_available",
            "DEPTH_IMBALANCE",
            "technical_adx",
            "CONSECUTIVE_RISES(field=ltp",
            "ORDER PERCENT_OF_HOLDING",
            "SCHEDULING PREFLIGHT",
            "schedule preflight",
            "This query is not supported",
            "BETWEEN",
            "ltp * 1.05",
            f"runtime default is {DEFAULT_RULE_ORDER_QUANTITY} kitta",
            "live field/function registries",
            "position_in_52_week_range_percent",
            "NEPSE ALPHA TECHNICALS",
            "TMS LIVE QUOTE",
        ):
            self.assertIn(token, prompt, f"missing {token}")

    def test_llm_prompt_documents_depth_execution_modes(self):
        prompt = build_strategy_query_llm_prompt(side="sell")
        for token in (
            "ORDER PRICE TOP_BUY",
            "ORDER PARTIAL_TOP_BUY",
            "TOP_BUY_QTY",
            "DEPTH_QUANTITY(side=",
            "Example 11 — sell to top buyer with partial fill",
            "top_buy_quantity",
        ):
            self.assertIn(token, prompt, f"missing depth execution guidance: {token}")
        self.assertIn("Do NOT output a query containing forbidden fields", prompt)

    def test_llm_prompt_lists_runtime_functions(self):
        prompt = build_strategy_query_llm_prompt(side="buy")
        for name in ("STDDEV", "SLOPE", "TREND", "UNIVERSE_PERCENTILE", "SECTOR_PERCENTILE"):
            self.assertIn(name, prompt)

    def test_llm_prompt_field_registry_matches_supported_catalog(self):
        prompt = build_strategy_query_llm_prompt(side="buy")
        for field in supported_catalog_fields():
            key = field.get("key")
            if key:
                self.assertIn(str(key), prompt, f"supported field registry key missing from prompt: {key}")
        for blocked in ("market_depth_available", "best_bid", "best_ask", "technical_adx"):
            self.assertNotIn(f"- {blocked}:", prompt)

    def test_format_query_parse_failure_shape(self):
        with self.assertRaises(StrategyQueryError):
            parse_strategy_query("SELECT * FROM users")

    def test_format_query_success_shape(self):
        plan = parse_strategy_query(
            'STRATEGY_VERSION 1\nSIDE BUY\nRULE "A" FOR SYMBOL "CZBIL" {\n'
            "WHEN technical_rsi_14 > 30\nORDER QUANTITY 100\n}"
        )
        self.assertEqual(plan.side, "BUY")
        self.assertEqual(plan.rules[0].symbols, ["CZBIL"])


if __name__ == "__main__":
    unittest.main()
