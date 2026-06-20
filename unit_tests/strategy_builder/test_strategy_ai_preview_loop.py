import unittest
from unittest.mock import AsyncMock, patch

from utils.strategy_builder.ai_query import StrategyQueryAiError, execute_strategy_query_ai_with_retries


SAMPLE_PAYLOAD = {
    "ai_status": "ok",
    "ai_summary": "- Sell at 52-week high",
    "generated_query": "STRATEGY_VERSION 1\nSIDE SELL\n",
    "compiled_plan": {"version": 1, "side": "SELL", "rules": []},
    "validation": {"valid": True},
    "ai_raw_response": "STATUS: OK",
}


class StrategyAiPreviewLoopTest(unittest.IsolatedAsyncioTestCase):
    @patch("utils.strategy_builder.strategy_ai_preview.build_strategy_preview_validation", new_callable=AsyncMock)
    @patch("utils.strategy_builder.ai_query.generate_and_validate_strategy_query")
    async def test_retries_when_preflight_fails_then_succeeds(self, mock_generate, mock_preview):
        mock_generate.side_effect = [
            dict(SAMPLE_PAYLOAD),
            dict(SAMPLE_PAYLOAD),
        ]
        mock_preview.side_effect = [
            {
                "valid": True,
                "errors": [],
                "warnings": [],
                "suggestions": [],
                "preview": [],
                "schedule_preflight": {
                    "ready": False,
                    "status": "blocked",
                    "message": "Missing 52-week data",
                    "errors": [{"message": "Missing 52-week data"}],
                },
            },
            {
                "valid": True,
                "errors": [],
                "warnings": [{"code": "NOTE", "message": "Preview only symbol"}],
                "suggestions": [],
                "preview": [{"symbol": "NRM"}],
                "schedule_preflight": {"ready": True, "status": "ready"},
            },
        ]

        db = object()
        result = await execute_strategy_query_ai_with_retries(
            "Sell NRM at 52 week high",
            side="sell",
            db=db,
            client_id="C1",
            max_retries=3,
        )

        self.assertTrue(result["valid"])
        self.assertEqual(result["ai_retry_count"], 1)
        self.assertEqual(mock_generate.call_count, 2)
        self.assertEqual(len(result["preview"]), 1)
        self.assertTrue(result["schedule_preflight"]["ready"])

    @patch("utils.strategy_builder.strategy_ai_preview.build_strategy_preview_validation", new_callable=AsyncMock)
    @patch("utils.strategy_builder.ai_query.generate_and_validate_strategy_query")
    async def test_raises_after_max_retries(self, mock_generate, mock_preview):
        mock_generate.return_value = dict(SAMPLE_PAYLOAD)
        mock_preview.return_value = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "suggestions": [],
            "preview": [],
            "schedule_preflight": {
                "ready": False,
                "message": "Always blocked",
                "errors": [{"message": "Always blocked"}],
            },
        }

        with self.assertRaises(StrategyQueryAiError) as ctx:
            await execute_strategy_query_ai_with_retries(
                "broken query",
                side="sell",
                db=object(),
                max_retries=2,
            )
        self.assertIn("preflight", str(ctx.exception).lower())
        self.assertEqual(mock_generate.call_count, 2)


if __name__ == "__main__":
    unittest.main()
