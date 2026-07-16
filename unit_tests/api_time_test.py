import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from utils.api_time import format_api_timestamp, is_continuous_market_timestamp, seconds_until_market_open
from utils.market_status import MARKET_OPEN, NEPAL_TZ


class ApiTimeTest(unittest.TestCase):
    def test_naive_db_timestamp_treated_as_utc(self):
        naive = datetime(2026, 6, 20, 1, 44, 49)
        payload = format_api_timestamp(naive)
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["utc"], "2026-06-20T01:44:49Z")
        self.assertEqual(payload["display"], "Jun 20, 2026, 07:29:49 AM")
        npt = datetime.fromisoformat(payload["npt"])
        self.assertEqual(npt.hour, 7)
        self.assertEqual(npt.minute, 29)

    def test_last_scan_timestamp_must_be_inside_continuous_market_hours(self):
        during_market_utc = datetime(2026, 7, 14, 7, 15)  # 1:00 PM Nepal time
        after_market_utc = datetime(2026, 7, 14, 14, 4, 34)  # 7:49:34 PM Nepal time

        self.assertTrue(is_continuous_market_timestamp(during_market_utc))
        self.assertFalse(is_continuous_market_timestamp(after_market_utc))

    def test_seconds_until_market_open_before_open(self):
        before_open = datetime.combine(
            datetime(2026, 6, 19).date(),
            datetime.strptime("10:30", "%H:%M").time(),
            tzinfo=NEPAL_TZ,
        )
        wait = seconds_until_market_open(before_open)
        self.assertAlmostEqual(wait, 30 * 60, delta=1)

    def test_seconds_until_market_open_during_session(self):
        during = datetime.combine(
            datetime(2026, 6, 19).date(),
            MARKET_OPEN,
            tzinfo=NEPAL_TZ,
        ).replace(hour=12)
        self.assertEqual(seconds_until_market_open(during), 0.0)

    def test_sunday_waits_until_monday_open(self):
        sunday = datetime(2026, 6, 21, 12, 0, tzinfo=NEPAL_TZ)
        monday_open = datetime(2026, 6, 22, 11, 0, tzinfo=NEPAL_TZ)

        self.assertEqual(seconds_until_market_open(sunday), (monday_open - sunday).total_seconds())


if __name__ == "__main__":
    unittest.main()
