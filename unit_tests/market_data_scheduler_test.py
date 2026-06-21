import unittest
from datetime import datetime, timedelta

from utils.market_data.nepse_alpha_bulk import (
    MEROLAGANI_REFRESH_INTERVAL_SECONDS,
    NEPSE_ALPHA_REFRESH_INTERVAL_SECONDS,
)
from utils.market_data.scheduler import (
    CHECK_INTERVAL_SECONDS,
    _seconds_until_next_refresh,
    _should_refresh,
)


class MarketDataSchedulerTest(unittest.TestCase):
    def test_should_refresh_when_never_run(self):
        self.assertTrue(_should_refresh(None, MEROLAGANI_REFRESH_INTERVAL_SECONDS))

    def test_should_refresh_after_interval(self):
        last = datetime.utcnow() - timedelta(seconds=MEROLAGANI_REFRESH_INTERVAL_SECONDS + 1)
        self.assertTrue(_should_refresh(last, MEROLAGANI_REFRESH_INTERVAL_SECONDS))

    def test_should_not_refresh_before_interval(self):
        last = datetime.utcnow() - timedelta(seconds=MEROLAGANI_REFRESH_INTERVAL_SECONDS - 30)
        self.assertFalse(_should_refresh(last, MEROLAGANI_REFRESH_INTERVAL_SECONDS))

    def test_seconds_until_next_refresh(self):
        last = datetime.utcnow() - timedelta(seconds=NEPSE_ALPHA_REFRESH_INTERVAL_SECONDS - 90)
        remaining = _seconds_until_next_refresh(last, NEPSE_ALPHA_REFRESH_INTERVAL_SECONDS)
        self.assertGreaterEqual(remaining, 80)
        self.assertLessEqual(remaining, 95)

    def test_check_interval_is_one_minute(self):
        self.assertEqual(CHECK_INTERVAL_SECONDS, 60)


if __name__ == "__main__":
    unittest.main()
