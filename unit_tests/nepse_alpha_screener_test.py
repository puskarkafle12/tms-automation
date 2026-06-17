import unittest

from utils.external_data_sources.nepse_alpha.screener import (
    flatten_nepse_alpha_for_screener,
    get_field_catalog,
    rank_screener_records,
    record_matches_filters,
)
from unit_tests.nepse_alpha_test import SAMPLE_SIGNALS_HTML
from utils.external_data_sources.nepse_alpha.client import parse_nepse_alpha_signals_html


class TestNepseAlphaScreener(unittest.TestCase):
    def setUp(self):
        payload = parse_nepse_alpha_signals_html(SAMPLE_SIGNALS_HTML, "ACLBSL")
        self.record = flatten_nepse_alpha_for_screener(payload)

    def test_flatten_maps_core_fields(self):
        self.assertEqual(self.record["symbol"], "ACLBSL")
        self.assertAlmostEqual(self.record["beta_3_month"], 1.05)
        self.assertAlmostEqual(self.record["ltp"], 950.0)
        self.assertAlmostEqual(self.record["fundamental_pe_ttm"], 27.51)
        self.assertAlmostEqual(self.record["fundamental_debt_to_equity"], 8.36)
        self.assertAlmostEqual(self.record["technical_rsi_14"], 46.39)
        self.assertEqual(self.record["technical_macd"], "Bullish")
        self.assertEqual(self.record["technical_sma_10"], "below")

    def test_field_catalog_includes_operators(self):
        catalog = get_field_catalog()
        self.assertTrue(any(item["key"] == "alpha_annualized" for item in catalog))
        pe = next(item for item in catalog if item["key"] == "fundamental_pe_ttm")
        self.assertIn("gte", pe["operators"])

    def test_numeric_filter_match(self):
        self.assertTrue(record_matches_filters(self.record, [{"field": "beta_3_month", "operator": "gte", "value": 1.0}]))
        self.assertFalse(record_matches_filters(self.record, [{"field": "beta_3_month", "operator": "gt", "value": 2.0}]))

    def test_text_filter_match(self):
        self.assertTrue(record_matches_filters(self.record, [{"field": "technical_macd", "operator": "eq", "value": "Bullish"}]))
        self.assertTrue(record_matches_filters(self.record, [{"field": "technical_sma_10", "operator": "eq", "value": "below"}]))

    def test_between_filter(self):
        self.assertTrue(
            record_matches_filters(
                self.record,
                [{"field": "technical_rsi_14", "operator": "between", "value": [40, 50]}],
            )
        )

    def test_ranking_orders_numeric_field(self):
        records = [
            {"symbol": "A", "alpha_annualized": 10},
            {"symbol": "B", "alpha_annualized": 50},
            {"symbol": "C", "alpha_annualized": 25},
        ]
        ranked = rank_screener_records(records, rank_by="alpha_annualized", direction="desc", limit=2)
        self.assertEqual([row["symbol"] for row in ranked], ["B", "C"])
        self.assertEqual(ranked[0]["rank"], 1)


if __name__ == "__main__":
    unittest.main()
