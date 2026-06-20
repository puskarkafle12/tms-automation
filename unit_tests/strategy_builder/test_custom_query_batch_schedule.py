import unittest
from unittest.mock import AsyncMock, patch

from utils.strategy_builder.custom_query_batch_schedule import (
    CustomQueryBatchError,
    _normalize_symbols,
    run_custom_query_batch,
)


class CustomQueryBatchScheduleTest(unittest.IsolatedAsyncioTestCase):
    def test_normalize_symbols_enforces_limit(self):
        symbols = [f"S{i}" for i in range(21)]
        with self.assertRaises(CustomQueryBatchError):
            _normalize_symbols(symbols)

    async def test_run_batch_collects_parallel_results(self):
        payload = {
            "client_id": "C1",
            "symbols": ["NABIL", "NTC"],
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


if __name__ == "__main__":
    unittest.main()
