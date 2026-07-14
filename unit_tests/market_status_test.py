from datetime import datetime
import unittest

from utils.market_status import (
    NEPAL_TZ,
    get_market_hours_status,
    is_market_polling_window,
    nepal_date_utc_bounds,
    parse_current_market_session_response,
    parse_session_check_response,
)


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

    def test_sunday_is_not_a_trading_day(self):
        status = get_market_hours_status(datetime(2026, 6, 21, 11, 0, tzinfo=NEPAL_TZ))

        self.assertFalse(status["is_trading_day"])
        self.assertFalse(status["market_hours_open"])
        self.assertTrue(is_market_polling_window(datetime(2026, 6, 21, 11, 0, tzinfo=NEPAL_TZ)))

    def test_saturday_is_not_in_market_polling_window(self):
        self.assertFalse(is_market_polling_window(datetime(2026, 6, 20, 11, 0, tzinfo=NEPAL_TZ)))

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

    def test_dna_session_parser_does_not_decide_market_state(self):
        parsed = parse_session_check_response({
            "status": "success",
            "message": "Logged In Successfully",
            "data": {"dnaStatus": "LOGGED_IN", "marketOpen": "false"},
        })

        self.assertTrue(parsed["session_active"])
        self.assertEqual(parsed["dna_status"], "LOGGED_IN")
        self.assertIsNone(parsed["market_live_from_api"])

    def test_dna_market_status_is_ignored(self):
        parsed = parse_session_check_response({
            "status": "success",
            "message": "Logged In Successfully",
            "data": {"dnaStatus": "LOGGED_IN", "marketStatus": "CLOSED"},
        })

        self.assertTrue(parsed["session_active"])
        self.assertIsNone(parsed["market_live_from_api"])

    def test_current_market_session_parser_recognizes_continuous(self):
        parsed = parse_current_market_session_response({
            "currentSessions": [{"sessionName": "Continuous"}],
            "activeStatus": True,
        })

        self.assertTrue(parsed["verified"])
        self.assertEqual(parsed["phase"], "open")
        self.assertTrue(parsed["market_open"])

    def test_current_market_session_parser_recognizes_pre_open(self):
        parsed = parse_current_market_session_response({
            "currentSessions": [{"sessionName": "SpecialPreOpen"}],
            "activeStatus": True,
        })

        self.assertEqual(parsed["phase"], "pre_open")
        self.assertTrue(parsed["is_pre_open"])

    def test_current_market_session_parser_treats_empty_verified_list_as_closed(self):
        parsed = parse_current_market_session_response({
            "currentSessions": [],
            "activeStatus": False,
        })

        self.assertTrue(parsed["verified"])
        self.assertEqual(parsed["phase"], "closed")
        self.assertFalse(parsed["market_open"])

    def test_current_market_session_parser_requires_top_level_active_status(self):
        parsed = parse_current_market_session_response({
            "currentSessions": [{"sessionName": "Continuous"}],
            "activeStatus": False,
        })

        self.assertEqual(parsed["phase"], "closed")
        self.assertFalse(parsed["market_open"])


if __name__ == "__main__":
    unittest.main()
