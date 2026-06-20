import unittest
from unittest.mock import AsyncMock, patch

from utils.strategy_builder.custom_query_batch_schedule import (
    _normalize_symbols,
    run_custom_query_batch,
)


class CustomQueryBatchScheduleTest(unittest.IsolatedAsyncioTestCase):
    def test_normalize_symbols_has_no_query_order_limit(self):
        symbols = [f"S{i}" for i in range(50)]
        self.assertEqual(len(_normalize_symbols(symbols)), 50)

    async def test_run_batch_collects_parallel_results(self):
        payload = {
            "client_id": "C1",
            "symbols": ["NABIL", "NTC"],
            "skip_preflight": True,
            "order_fields": {"strategy_type": "Custom Query Buy", "order_type": "buy", "qty": 10},
        }
        with patch(
            "utils.strategy_builder.custom_query_batch_schedule._schedule_one_symbol",
            new=AsyncMock(
                side_effect=[
                    {"symbol": "NABIL", "order_id": 1},
                    {"symbol": "NTC", "error": "Cannot schedule"},
                ]
            ),
        ):
            result = await run_custom_query_batch(payload)
        self.assertEqual(len(result["scheduled"]), 1)
        self.assertEqual(len(result["failed"]), 1)

    async def test_run_batch_reuses_ready_preview_preflight(self):
        payload = {
            "client_id": "C1",
            "symbols": ["NABIL", "NTC"],
            "skip_preflight": True,
            "order_fields": {"strategy_type": "Custom Query Buy", "order_type": "buy", "qty": 10},
        }
        with patch(
            "utils.strategy_builder.custom_query_batch_schedule._preflight_batch",
            new=AsyncMock(return_value={"ready": False, "failed": [{"symbol": "NABIL", "message": "Should not run"}]}),
        ) as preflight_mock, patch(
            "utils.strategy_builder.custom_query_batch_schedule._schedule_one_symbol",
            new=AsyncMock(
                side_effect=[
                    {"symbol": "NABIL", "order_id": 1},
                    {"symbol": "NTC", "order_id": 2},
                ]
            ),
        ):
            result = await run_custom_query_batch(payload)
        preflight_mock.assert_not_called()
        self.assertEqual([row["symbol"] for row in result["scheduled"]], ["NABIL", "NTC"])

    async def test_run_batch_retries_transient_server_disconnect(self):
        payload = {
            "client_id": "C1",
            "symbols": ["NRIC"],
            "skip_preflight": True,
            "order_fields": {"strategy_type": "Custom Query Sell", "order_type": "sell", "qty": 10},
        }
        with patch(
            "utils.strategy_builder.custom_query_batch_schedule._schedule_one_symbol",
            new=AsyncMock(
                side_effect=[
                    {"symbol": "NRIC", "error": "Server disconnected", "message": "Server disconnected"},
                    {"symbol": "NRIC", "order_id": 7},
                ]
            ),
        ) as schedule_mock, patch(
            "utils.strategy_builder.custom_query_batch_schedule.asyncio.sleep",
            new=AsyncMock(),
        ):
            result = await run_custom_query_batch(payload)

        self.assertEqual(len(result["failed"]), 0)
        self.assertEqual(result["scheduled"][0]["symbol"], "NRIC")
        self.assertEqual(schedule_mock.await_count, 2)

    async def test_run_batch_stamps_schedule_batch_metadata(self):
        payload = {
            "client_id": "C1",
            "symbols": ["NABIL"],
            "skip_preflight": True,
            "order_fields": {
                "strategy_type": "Custom Query Buy",
                "order_type": "buy",
                "qty": 10,
                "strategy_config": {
                    "query_text": 'RULE "Buy Blue Chip" FOR SYMBOL IN ("NABIL") { WHEN ltp <= 100 }',
                    "compiled_plan": {"rules": [{"name": "Buy Blue Chip"}]},
                },
            },
        }
        captured_payloads: list[dict] = []

        async def _capture(symbol, batch_payload, **kwargs):
            captured_payloads.append(dict(batch_payload))
            return {"symbol": symbol, "order_id": 1}

        with patch(
            "utils.strategy_builder.custom_query_batch_schedule._schedule_one_symbol",
            new=AsyncMock(side_effect=_capture),
        ):
            result = await run_custom_query_batch(payload)

        self.assertTrue(result["schedule_batch_id"])
        self.assertEqual(result["schedule_batch_label"], "Buy Blue Chip")
        self.assertEqual(len(captured_payloads), 1)
        self.assertEqual(captured_payloads[0]["schedule_batch_id"], result["schedule_batch_id"])
        self.assertEqual(captured_payloads[0]["schedule_batch_symbol_count"], 1)


if __name__ == "__main__":
    unittest.main()
