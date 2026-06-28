from __future__ import annotations

import unittest

from main import _build_trade_cost_basis


class DPHoldingsCostBasisTest(unittest.TestCase):
    def test_fifo_average_keeps_remaining_quantity_only(self):
        rows = [
            {"symbol": "GBIME", "buyOrSell": 1, "tradePrice": 100, "tradedQuantity": 100, "tradeTime": "2026-06-01 09:15:00"},
            {"symbol": "GBIME", "buyOrSell": 1, "tradePrice": 120, "tradedQuantity": 100, "tradeTime": "2026-06-02 09:15:00"},
            {"symbol": "GBIME", "buyOrSell": 2, "tradePrice": 130, "tradedQuantity": 50, "tradeTime": "2026-06-03 09:15:00"},
        ]

        basis = _build_trade_cost_basis(rows)

        self.assertIn("GBIME", basis)
        self.assertEqual(basis["GBIME"]["quantity"], 150)
        self.assertAlmostEqual(basis["GBIME"]["average_buy_price"], 113.3333333333, places=6)

    def test_sell_then_rebuy_uses_execution_order(self):
        rows = [
            {"symbol": "GBIME", "buyOrSell": 2, "tradePrice": 130, "tradedQuantity": 50, "tradeTime": "2026-06-03 09:15:00"},
            {"symbol": "GBIME", "buyOrSell": 1, "tradePrice": 100, "tradedQuantity": 100, "tradeTime": "2026-06-01 09:15:00"},
            {"symbol": "GBIME", "buyOrSell": 1, "tradePrice": 120, "tradedQuantity": 100, "tradeTime": "2026-06-02 09:15:00"},
        ]

        basis = _build_trade_cost_basis(rows)

        self.assertIn("GBIME", basis)
        self.assertEqual(basis["GBIME"]["quantity"], 150)
        self.assertAlmostEqual(basis["GBIME"]["average_buy_price"], 113.3333333333, places=6)


if __name__ == "__main__":
    unittest.main()
