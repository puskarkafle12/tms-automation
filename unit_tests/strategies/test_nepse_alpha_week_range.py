import unittest

from utils.strategies.helpers import parse_nepse_stat_number, safe_number
from utils.external_data_sources.nepse_alpha.stats_parsing import extract_price_stat_from_stats
from utils.strategies.normalize import (
    extract_week_range_from_stats,
    normalize_nepse_alpha_payload,
    script_details_missing_week_range,
)


class NepseAlphaWeekRangeTest(unittest.TestCase):
    def test_npr_spaced_price_not_parsed_as_fraction(self):
        self.assertAlmostEqual(parse_nepse_stat_number("NPR. 422"), 422.0)
        self.assertAlmostEqual(parse_nepse_stat_number("NPR. 288.2"), 288.2)
        self.assertAlmostEqual(safe_number("NPR. 422"), 0.422)

    def test_extract_all_time_low_fuzzy_key(self):
        stats = {"all_time_low_price": "NPR. 288.2"}
        self.assertAlmostEqual(extract_price_stat_from_stats(stats, "all_time_low"), 288.2)

    def test_pcbl_compact_npr_format(self):
        stats = {"52_weeks_high_low": "NPR.1,033.28/NPR.635.00"}
        high, low = extract_week_range_from_stats(stats)
        self.assertAlmostEqual(high, 1033.28)
        self.assertAlmostEqual(low, 635.00)

    def test_fuzzy_week_key_match(self):
        stats = {"52_weeks_high_low_alt": "NPR. 500/NPR. 300"}
        high, low = extract_week_range_from_stats(stats)
        self.assertAlmostEqual(high, 500.0)
        self.assertAlmostEqual(low, 300.0)

    def test_pcbl_payload_normalizes_all_time_and_week_range(self):
        payload = {
            "symbol": "PCBL",
            "statistical_performance": {
                "52_weeks_high_low": "NPR.1,033.28/NPR.635.00",
                "ltp": "NPR. 670",
                "all_time_high": "NPR. 1372",
                "all_time_low": "NPR. 288.2",
            },
            "fundamental_signals": [],
            "technical_signals": [],
        }
        details = normalize_nepse_alpha_payload(payload)
        self.assertFalse(script_details_missing_week_range(details))
        self.assertAlmostEqual(details.fifty_two_week_high, 1033.28)
        self.assertAlmostEqual(details.fifty_two_week_low, 635.00)
        self.assertAlmostEqual(details.all_time_high, 1372.0)
        self.assertAlmostEqual(details.all_time_low, 288.2)
        self.assertAlmostEqual(details.reference_ltp, 670.0)


if __name__ == "__main__":
    unittest.main()
