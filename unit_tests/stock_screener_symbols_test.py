import unittest

from utils.stock_screener_symbols import (
    screener_universe_label,
    symbols_from_holdings,
    union_holdings_maps,
)


class StockScreenerSymbolsTest(unittest.TestCase):
    def test_symbols_from_holdings_filters_zero_qty(self):
        holdings = {"NABIL": 100, "NICA": 0, "UPPER": 5}
        self.assertEqual(symbols_from_holdings(holdings), ["NABIL", "UPPER"])

    def test_union_holdings_maps_sums_quantities(self):
        maps = [
            {"NABIL": 100, "NICA": 0},
            {"NABIL": 50, "UPPER": 10},
        ]
        self.assertEqual(union_holdings_maps(maps), ["NABIL", "UPPER"])

    def test_screener_universe_label(self):
        self.assertEqual(
            screener_universe_label("nepse", symbol_count=120),
            "NEPSE (120 symbols)",
        )
        self.assertEqual(
            screener_universe_label("combined_holdings", symbol_count=8),
            "Combined holdings (8 symbols)",
        )
        self.assertEqual(
            screener_universe_label("client_holdings", client_id="demo1", symbol_count=3),
            "demo1 holdings (3 symbols)",
        )


if __name__ == "__main__":
    unittest.main()
