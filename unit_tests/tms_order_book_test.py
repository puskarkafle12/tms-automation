import importlib.util
import unittest
from unittest.mock import AsyncMock


@unittest.skipIf(importlib.util.find_spec("aiohttp") is None, "aiohttp is not installed")
class TestTmsOrderBookNormalization(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from utils.tms import TmsUser

        self.TmsUser = TmsUser

    def test_normalize_order_book_row_flattens_nested_fields(self):
        row = {
            "buyOrSell": 2,
            "orderBook": {
                "buyOrSell": 2,
                "activeStatus": "COMPLETED",
                "orderBookExtensions": [
                    {
                        "orderQuantity": 222,
                        "orderPrice": 385.0,
                        "totalTradedQuantity": 222,
                        "remainingOrderQuantity": 0,
                    }
                ],
            },
            "security": {"symbol": "AKJCL"},
            "orderTime": "2026-06-18 11:00:55",
            "displayActiveStatus": "COMPLETED",
            "exchangeOrderId": "2026061804002464",
        }

        normalized = self.TmsUser._normalize_order_book_row(row)

        self.assertEqual(normalized["symbol"], "AKJCL")
        self.assertEqual(normalized["buyOrSell"], 2)
        self.assertEqual(normalized["orderQuantity"], 222)
        self.assertEqual(normalized["orderPrice"], 385.0)
        self.assertEqual(normalized["activeStatus"], "COMPLETED")
        self.assertEqual(normalized["displayActiveStatus"], "COMPLETED")
        self.assertEqual(normalized["totalTradedQuantity"], 222)
        self.assertEqual(normalized["exchangeOrderId"], "2026061804002464")

    async def test_get_normalized_daily_order_book_sorts_newest_first(self):
        user = self.TmsUser(broker_no="35", username="client1", password="enc-pass")
        user.get_order_history = AsyncMock(
            return_value=[
                {
                    "symbol": "AAA",
                    "orderTime": "2026-06-17 10:00:00",
                    "buyOrSell": 1,
                    "activeStatus": "COMPLETED",
                },
                {
                    "symbol": "BBB",
                    "orderTime": "2026-06-18 11:00:55",
                    "buyOrSell": 2,
                    "activeStatus": "CANCELLED",
                },
            ]
        )

        rows = await user.get_normalized_daily_order_book()

        self.assertEqual([row["symbol"] for row in rows], ["BBB", "AAA"])
        self.assertEqual(rows[0]["activeStatus"], "CANCELLED")
