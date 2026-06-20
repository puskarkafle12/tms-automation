import unittest

from utils.strategy_builder.constants import DEFAULT_RULE_ORDER_QUANTITY
from utils.strategy_builder.strategy_llm_prompt import build_strategy_query_llm_prompt, supported_catalog_fields
from utils.strategy_builder.strategy_parser import StrategyQueryError, parse_strategy_query
from utils.strategy_builder.strategy_validator import validate_strategy_plan


STRICT_QUERY_SYMBOLS = [
    "NABIL", "EBL", "SCB", "GBIME", "SANIMA", "NMB", "PRVU", "HBL", "PCBL", "CZBIL",
    "NIMB", "SBL", "NBL", "NIFRA", "NTC", "HIDCL", "CHCL", "AKJCL", "UNL", "HDL",
    "NLIC", "LICN", "SICL", "NICL", "IGI", "SGIC", "PRIN", "RBCL", "ALICL", "NLG",
    "SJLIC", "CLI", "ILI", "NLICL", "SHL", "CGH", "BHL", "BNT", "MFIL", "GUFL",
    "JFL", "GMFIL", "ICFC", "PROFL", "MPFL", "CFCL", "GFCL", "JBLB", "SWBBL", "SLBBL",
    "SKBBL", "CBBL", "MLBBL", "DDBL", "FMDBL", "SMATA", "NUBL", "RSDC", "VLBS", "NFS",
    "FOWAD", "SAPDBL", "SMB", "NICA", "BOKL", "KBL", "SRBL", "MNBBL", "LBBL", "SHINE",
    "CORBL", "SINDU", "MLBL", "NRN", "AHPC", "API", "UPPER", "NHPC", "RHPL", "RADHI",
    "MEN", "HURJA", "JOSHI", "AKPL", "BPCL", "HPPL", "LEC", "NGPL", "KPCL", "SPDL",
    "UMHL", "MKJC", "MHCL", "TPC", "PPL", "RURU", "BARUN", "UMRH", "DOLTI", "RFPL",
    "SHEL",
]


def _strict_query_cases():
    buy_templates = [
        'WHEN technical_rsi_14 BETWEEN 30 AND 45 AND technical_macd = "Bullish"\nORDER QUANTITY 10\nEXECUTE ONCE',
        'ELIGIBILITY volume > 0\nSIGNAL ltp >= open\nORDER AMOUNT 20000\nCONFIRM IMMEDIATE\nEXECUTE ONCE PER SYMBOL',
        'WHEN position_in_52_week_range_percent < 35 AND technical_sma_20 = "above"\nORDER QUANTITY FROM_FORM\nTRIGGER LEVEL\nEXECUTE ONCE',
        'WHEN CONSECUTIVE_RISES(field=ltp, count=2, min_total_change_pct=1)\nORDER QUANTITY 25\nEXECUTE ONCE',
        'ELIGIBILITY market_depth_available = TRUE\nSIGNAL top_sell_quantity >= 10 AND spread_percent <= 1\nORDER PARTIAL_TOP_SELL 25 PRICE TOP_SELL\nEXECUTE ONCE',
        'WHEN DEPTH_IMBALANCE(levels=2, operator="gte", threshold=0.2)\nORDER TOP_SELL_QTY PRICE TOP_SELL\nEXECUTE ONCE',
    ]
    sell_templates = [
        'WHEN profit_percent >= 5 AND technical_rsi_14 >= 70\nORDER PERCENT_OF_HOLDING 50\nEXECUTE ONCE',
        'WHEN ltp <= effective_stop_price\nORDER ALL_AVAILABLE\nCONFIRM TRUE_FOR 2 SCANS\nEXECUTE ONCE',
        'ELIGIBILITY profit_percent > 0\nSIGNAL CONSECUTIVE_DROPS(field=ltp, count=2, min_total_change_pct=1)\nORDER SELL_UP_TO 10\nEXECUTE ONCE',
        'WHEN drawdown_from_peak_percent < 0\nORDER PERCENT_OF_HOLDING 100\nTRIGGER LEVEL\nEXECUTE ONCE PER SYMBOL',
        'ELIGIBILITY market_depth_available = TRUE\nSIGNAL top_buy_quantity >= 10 AND best_bid > 0\nORDER TOP_BUY_QTY PRICE TOP_BUY\nEXECUTE ONCE',
        'WHEN DEPTH_QUANTITY(side="BUY", levels=3, operator="gte", threshold=100)\nORDER PARTIAL_TOP_BUY 25 PRICE TOP_BUY\nEXECUTE ONCE',
    ]
    cases = []
    for idx, symbol in enumerate(STRICT_QUERY_SYMBOLS[:50]):
        cases.append(("BUY", symbol, buy_templates[idx % len(buy_templates)]))
    for idx, symbol in enumerate(STRICT_QUERY_SYMBOLS[50:100]):
        cases.append(("SELL", symbol, sell_templates[idx % len(sell_templates)]))
    return cases


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
            "STRICT OUTPUT CONTRACT",
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
            "live field/function/strategy registries",
            "position_in_52_week_range_percent",
            "must schedule without a 52-week warning",
            "SELL queries must stay within the user's sellable DP holdings",
            "NEPSE ALPHA TECHNICALS",
            "TMS LIVE QUOTE",
        ):
            self.assertIn(token, prompt, f"missing {token}")

    def test_llm_prompt_has_strict_output_contract(self):
        prompt = build_strategy_query_llm_prompt(side="buy", form_symbol="CZBIL")
        for token in (
            "Output exactly one Strategy Query Language document, or exactly one refusal sentence.",
            "Valid query output must start with STRATEGY_VERSION 1",
            "Do not output markdown fences",
            "Do not output placeholders",
            "Use only exact uppercase quoted script symbols",
            "Function arguments must be named",
            'operator="gte", not operator=gte',
            "Use positive numeric literals only",
            "This query is not supported — <name> is not available.",
        ):
            self.assertIn(token, prompt, f"missing strict output contract token: {token}")

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
        self.assertIn("Depth functions must use named args", prompt)
        self.assertIn('operator="gte". Unquoted operator=gte is parsed as a field and is invalid.', prompt)
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
        for supported in ("market_depth_available", "best_bid", "best_ask", "top_buy_quantity", "top_sell_quantity"):
            self.assertIn(f"- {supported}:", prompt)
        for blocked in ("technical_adx", "adx"):
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

    def test_generated_strict_buy_sell_queries_parse_and_validate(self):
        cases = _strict_query_cases()
        self.assertEqual(len(cases), 100)
        known_symbols = set(STRICT_QUERY_SYMBOLS)
        holdings = {symbol: 100 for symbol in STRICT_QUERY_SYMBOLS}
        for idx, (side, symbol, body) in enumerate(cases, start=1):
            query = f'STRATEGY_VERSION 1\nSIDE {side}\nRULE "{symbol} Strict {side} {idx}" FOR SYMBOL "{symbol}" {{\n{body}\n}}\n'
            plan = parse_strategy_query(query)
            validation = validate_strategy_plan(
                plan,
                strategy_type=f"Custom Query {side.title()}",
                known_symbols=known_symbols,
                holdings=holdings,
                holdings_checked=side == "SELL",
            )
            self.assertTrue(validation.valid, f"query {idx} failed validation: {validation.errors}\n{query}")
            self.assertEqual(plan.side, side)
            self.assertEqual(plan.rules[0].symbols, [symbol])


if __name__ == "__main__":
    unittest.main()
