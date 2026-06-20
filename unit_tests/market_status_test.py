from datetime import datetime
import unittest

from utils.market_status import NEPAL_TZ, get_market_hours_status, nepal_date_utc_bounds


class TestMarketStatus(unittest.TestCase):
    def test_pre_open_is_reported_but_not_market_open(self):
        status = get_market_hours_status(datetime(2026, 6, 15, 10, 30, tzinfo=NEPAL_TZ))

        self.assertTrue(status["is_trading_day"])
        self.assertTrue(status["is_pre_open"])
        self.assertFalse(status["is_continuous"])
        self.assertFalse(status["market_hours_open"])

    def test_regular_market_open_starts_at_eleven(self):
        status = get_market_hours_status(datetime(2026, 6, 15, 11, 0, tzinfo=NEPAL_TZ))

        self.assertTrue(status["is_trading_day"])
        self.assertFalse(status["is_pre_open"])
        self.assertTrue(status["is_continuous"])
        self.assertTrue(status["market_hours_open"])

    def test_market_is_closed_after_three_pm(self):
        status = get_market_hours_status(datetime(2026, 6, 15, 15, 1, tzinfo=NEPAL_TZ))

        self.assertTrue(status["is_trading_day"])
        self.assertFalse(status["is_pre_open"])
        self.assertFalse(status["is_continuous"])
        self.assertFalse(status["market_hours_open"])

    def test_saturday_is_not_a_trading_day(self):
        status = get_market_hours_status(datetime(2026, 6, 20, 11, 0, tzinfo=NEPAL_TZ))

        self.assertFalse(status["is_trading_day"])
        self.assertFalse(status["is_pre_open"])
        self.assertFalse(status["is_continuous"])
        self.assertFalse(status["market_hours_open"])

    def test_format_nepal_datetime_matches_api_timestamp_shape(self):
        from utils.market_status import format_nepal_datetime

        payload = format_nepal_datetime(datetime(2026, 6, 15, 11, 30, tzinfo=NEPAL_TZ))
        self.assertIn("npt", payload)
        self.assertIn("utc", payload)
        self.assertEqual(payload["date"], "2026-06-15")
        self.assertEqual(payload["timezone"], "Asia/Kathmandu")

    def test_nepal_calendar_day_converts_to_utc_bounds(self):
        start_utc, end_utc = nepal_date_utc_bounds(datetime(2026, 6, 15).date())

        self.assertEqual(start_utc, datetime(2026, 6, 14, 18, 15))
        self.assertEqual(end_utc, datetime(2026, 6, 15, 18, 15))


if __name__ == "__main__":
    unittest.main()
