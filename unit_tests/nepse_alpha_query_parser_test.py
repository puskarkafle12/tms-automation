import unittest

from utils.external_data_sources.nepse_alpha.query_parser import ScreenerQueryError, parse_screener_query


class TestScreenerQueryParser(unittest.TestCase):
    def test_parses_where_order_limit(self):
        parsed = parse_screener_query("""
            WHERE technical_rsi_14 BETWEEN 30 AND 45
              AND fundamental_pe_ttm <= 30
              AND technical_macd = 'Bullish'
            ORDER BY alpha_annualized DESC
            LIMIT 25
        """)
        self.assertEqual(len(parsed["filters"]), 3)
        self.assertEqual(parsed["filters"][0]["field"], "technical_rsi_14")
        self.assertEqual(parsed["filters"][0]["operator"], "between")
        self.assertEqual(parsed["rank_by"], "alpha_annualized")
        self.assertEqual(parsed["rank_direction"], "desc")
        self.assertEqual(parsed["limit"], 25)

    def test_parses_comparison_operators(self):
        parsed = parse_screener_query("WHERE beta_3_month >= 1.2 AND ltp > 100")
        self.assertEqual(parsed["filters"][0]["operator"], "gte")
        self.assertEqual(parsed["filters"][1]["operator"], "gt")

    def test_parses_in_list(self):
        parsed = parse_screener_query("WHERE technical_macd IN ('Bullish', 'Neutral')")
        self.assertEqual(parsed["filters"][0]["operator"], "in")
        self.assertEqual(parsed["filters"][0]["value"], ["Bullish", "Neutral"])

    def test_rejects_unknown_field(self):
        with self.assertRaises(ScreenerQueryError):
            parse_screener_query("WHERE unknown_field >= 1")


if __name__ == "__main__":
    unittest.main()
