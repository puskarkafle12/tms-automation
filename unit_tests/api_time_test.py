import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from utils.api_time import format_api_timestamp, seconds_until_market_open
from utils.market_status import MARKET_OPEN, NEPAL_TZ


class ApiTimeTest(unittest.TestCase):
    def test_naive_db_timestamp_treated_as_utc(self):
        naive = datetime(2026, 6, 20, 1, 44, 49)
        payload = format_api_timestamp(naive)
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["utc"], "2026-06-20T01:44:49Z")
        self.assertIn("NPT", payload["display"])
        self.assertTrue(payload["display"].endswith("NPT"))
        npt = datetime.fromisoformat(payload["npt"])
        self.assertEqual(npt.hour, 7)
        self.assertEqual(npt.minute, 29)

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


if __name__ == "__main__":
    unittest.main()
