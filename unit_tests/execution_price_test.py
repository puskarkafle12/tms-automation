import unittest

from utils.strategies.execution_price import resolve_sell_limit_price, sell_price_exceeds_slippage
from utils.strategies.types import MarketSnapshot, OrderBookLevel
from utils.tms import TmsUser


class TestExecutionPrice(unittest.TestCase):
    def test_sell_limit_clamps_above_ltp(self):
        snapshot = MarketSnapshot(
            symbol="AKJCL",
            ltp=385.0,
            top_buy_orders=[OrderBookLevel(price=396.9, quantity=100)],
        )
        price, source = resolve_sell_limit_price(snapshot, 385.0, max_slippage_percent=1.0, reference_price=385.0)
        self.assertEqual(source, "Top Buy")
        self.assertLessEqual(price, 385.0)

    def test_sell_limit_uses_top_buy_when_below_ltp(self):
        snapshot = MarketSnapshot(
            symbol="AKJCL",
            ltp=400.0,
            top_buy_orders=[OrderBookLevel(price=396.9, quantity=100)],
        )
        price, source = resolve_sell_limit_price(snapshot, 400.0, max_slippage_percent=1.0)
        self.assertEqual(source, "Top Buy")
        self.assertEqual(price, 396.9)

    def test_slippage_guard_detects_excess(self):
        self.assertTrue(
            sell_price_exceeds_slippage(
                requested_price=385.0,
                execution_price=396.9,
                max_slippage_percent=1.0,
            )
        )
        self.assertFalse(
            sell_price_exceeds_slippage(
                requested_price=385.0,
                execution_price=388.0,
                max_slippage_percent=1.0,
            )
        )


class TestOrderBookNormalization(unittest.TestCase):
    def test_normalize_nested_order_book_row(self):
        row = {
            "buyOrSell": 2,
            "orderBook": {
                "buyOrSell": 2,
                "activeStatus": "OPEN",
                "orderBookExtensions": [
                    {
                        "orderQuantity": 222,
                        "orderPrice": 385.0,
                        "remainingOrderQuantity": 222,
                        "totalTradedQuantity": 0,
                    }
                ],
                "security": {"symbol": "AKJCL"},
            },
            "exchangeOrderId": "2026061801001234",
        }
        normalized = TmsUser._normalize_order_book_row(row)
        self.assertEqual(normalized["symbol"], "AKJCL")
        self.assertEqual(normalized["orderQuantity"], 222)
        self.assertEqual(normalized["orderPrice"], 385.0)
        self.assertEqual(normalized["exchangeOrderId"], "2026061801001234")


if __name__ == "__main__":
    unittest.main()
