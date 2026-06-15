from datetime import datetime
import unittest

from utils.market_status import NEPAL_TZ, get_market_hours_status


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


if __name__ == "__main__":
    unittest.main()
