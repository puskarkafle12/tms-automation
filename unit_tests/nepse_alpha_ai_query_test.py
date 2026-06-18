import unittest
from unittest.mock import AsyncMock, patch

from utils.external_data_sources.nepse_alpha.ai_query import (
    MAX_AI_SYSTEM_PROMPT_CHARS,
    ScreenerAiError,
    build_ai_system_prompt,
    build_retry_user_message,
    execute_ai_screener_with_retries,
    parse_ai_screener_response,
)


class TestNepseAlphaAiQuery(unittest.TestCase):
    def test_system_prompt_includes_live_field_keys(self):
        prompt = build_ai_system_prompt()
        self.assertIn("fundamental_pe_ttm", prompt)
        self.assertIn("technical_rsi_14", prompt)
        self.assertIn("STATUS: OK", prompt)
        self.assertLessEqual(
            len(prompt),
            MAX_AI_SYSTEM_PROMPT_CHARS,
            "AI system prompt is too large for the configured model context window",
        )

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

    def test_retry_message_includes_failure_and_query(self):
        msg = build_retry_user_message(
            "low PE stocks",
            failure_type="parse_error",
            failure_detail="Unknown field market_cap",
            previous_query="WHERE market_cap > 100",
            attempt_number=2,
        )
        self.assertIn("PREVIOUS ATTEMPT FAILED", msg)
        self.assertIn("market_cap", msg)
        self.assertIn("low PE stocks", msg)

    def test_execute_retries_on_zero_rows(self):
        ok_query = """STATUS: OK

Summary:
- test

Query:
```
WHERE fundamental_pe_ttm <= 30
ORDER BY alpha_annualized DESC
LIMIT 25
```"""
        ok_payload = {
            "ai_status": "ok",
            "ai_summary": "- test",
            "generated_query": "WHERE fundamental_pe_ttm <= 30\nORDER BY alpha_annualized DESC\nLIMIT 25",
            "parsed_query": {
                "filters": [{"field": "fundamental_pe_ttm", "operator": "lte", "value": 30}],
                "rank_by": "alpha_annualized",
                "rank_direction": "desc",
                "limit": 25,
            },
            "ai_raw_response": ok_query,
        }

        runner = AsyncMock(side_effect=[
            {"results": [], "stats": {"matched": 0, "loaded": 10}},
            {"results": [{"symbol": "ABC"}], "stats": {"matched": 1, "returned": 1}},
        ])

        with patch(
            "utils.external_data_sources.nepse_alpha.ai_query.generate_and_validate_screener_query",
            side_effect=[ok_payload, ok_payload],
        ):
            import asyncio
            result = asyncio.run(execute_ai_screener_with_retries("low PE", runner, max_retries=3))

        self.assertEqual(result["ai_retry_count"], 1)
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(runner.await_count, 2)


if __name__ == "__main__":
    unittest.main()
