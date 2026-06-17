import unittest

from utils.external_data_sources.nepse_alpha.ai_query import (
    ScreenerAiError,
    build_ai_system_prompt,
    parse_ai_screener_response,
)


class TestNepseAlphaAiQuery(unittest.TestCase):
    def test_system_prompt_includes_live_field_keys(self):
        prompt = build_ai_system_prompt()
        self.assertIn("fundamental_pe_ttm", prompt)
        self.assertIn("technical_rsi_14", prompt)
        self.assertIn("STATUS: OK", prompt)

    def test_parse_ok_response(self):
        raw = """STATUS: OK

Summary:
- Oversold RSI
- Low PE

Query:
```
WHERE technical_rsi_14 BETWEEN 30 AND 45
  AND fundamental_pe_ttm <= 30
ORDER BY alpha_annualized DESC
LIMIT 25
```"""
        parsed = parse_ai_screener_response(raw)
        self.assertEqual(parsed["status"], "ok")
        self.assertIn("technical_rsi_14", parsed["query"])
        self.assertIn("Oversold RSI", parsed["summary"])

    def test_parse_error_response(self):
        with self.assertRaises(ScreenerAiError) as ctx:
            parse_ai_screener_response("STATUS: ERROR\n\nReason:\n- market_cap is unsupported")
        self.assertEqual(ctx.exception.status, "error")

    def test_parse_ok_without_query_raises(self):
        with self.assertRaises(ScreenerAiError):
            parse_ai_screener_response("STATUS: OK\n\nSummary:\n- nothing")


if __name__ == "__main__":
    unittest.main()
