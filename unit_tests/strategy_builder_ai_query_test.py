import unittest

from utils.strategy_builder.ai_query import (
    StrategyQueryAiError,
    parse_ai_strategy_response,
)


SAMPLE_OK = """STATUS: OK
Summary:
- Buy CZBIL when RSI is above 30
Query:
```
STRATEGY_VERSION 1
SIDE BUY
RULE "CZBIL RSI Buy" FOR SYMBOL "CZBIL" {
    WHEN technical_rsi_14 > 30
    ORDER QUANTITY 100
    EXECUTE ONCE
}
```
"""


class StrategyBuilderAiQueryTest(unittest.TestCase):
    def test_parse_ok_response(self):
        parsed = parse_ai_strategy_response(SAMPLE_OK)
        self.assertEqual(parsed["status"], "ok")
        self.assertIn("STRATEGY_VERSION 1", parsed["query"])
        self.assertIn("technical_rsi_14 > 30", parsed["query"])

    def test_parse_error_response(self):
        with self.assertRaises(StrategyQueryAiError):
            parse_ai_strategy_response("STATUS: ERROR\nReason:\n- Unknown field foo")

    def test_parse_raw_strategy_block_without_status(self):
        raw = """STRATEGY_VERSION 1
SIDE BUY
RULE "A" FOR SYMBOL "CZBIL" {
    WHEN technical_rsi_14 > 30
    ORDER QUANTITY 100
}"""
        parsed = parse_ai_strategy_response(raw)
        self.assertIn("CZBIL", parsed["query"])


if __name__ == "__main__":
    unittest.main()
