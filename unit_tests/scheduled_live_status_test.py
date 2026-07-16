import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from utils.log_sender import (
    is_transient_monitor_log_line,
    store_or_update_logs,
    strip_transient_monitor_log_lines,
)


class TestTransientMonitorLogs(unittest.TestCase):
    def test_is_transient_monitor_log_line(self):
        self.assertTrue(is_transient_monitor_log_line("Price fetch failed"))
        self.assertTrue(is_transient_monitor_log_line("  Price fetch failed after 1 retries"))
        self.assertFalse(is_transient_monitor_log_line("TRACKING: Monitoring: NOT_ELIGIBLE"))

    def test_strip_transient_monitor_log_lines(self):
        logs = "Price fetch failed\nTRACKING: Monitoring: armed\nPrice fetch failed"
        cleaned = strip_transient_monitor_log_lines(logs)
        self.assertEqual(cleaned, "TRACKING: Monitoring: armed")

    def test_strip_transient_monitor_log_lines_all_transient(self):
        self.assertIsNone(strip_transient_monitor_log_lines("Price fetch failed"))


class TestPausedMonitorLogTimestamp(unittest.IsolatedAsyncioTestCase):
    async def test_paused_status_does_not_replace_last_real_scan_time(self):
        original = datetime(2026, 7, 14, 7, 15, tzinfo=timezone.utc)
        log = SimpleNamespace(
            scanning_count=4,
            current_price=199,
            order_placed=False,
            timestamp=original,
            logs=None,
        )
        db = MagicMock()
        db.query.return_value.filter_by.return_value.first.return_value = log

        await store_or_update_logs(
            db,
            "client1",
            "CZBIL",
            4,
            None,
            False,
            "Waiting for market",
            touch_timestamp=False,
        )

        self.assertEqual(log.timestamp, original)


class TestScheduledLiveStatus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from main import _compute_scheduled_live_status, _last_monitor_log_line

        cls.compute = staticmethod(_compute_scheduled_live_status)
        cls.last_line = staticmethod(_last_monitor_log_line)

    def test_active_scanning_hides_tracking_detail(self):
        result = self.compute(
            monitoring_active=True,
            monitor_phase="active",
            scanning_count=12,
            last_monitor_message="TRACKING: Monitoring: NOT_ELIGIBLE",
            current_price=245.0,
        )
        self.assertTrue(result["is_scanning"])
        self.assertIsNone(result["display_error"])
        self.assertEqual(result["live_status"], "scanning")

    def test_stuck_price_fetch_shows_error(self):
        result = self.compute(
            monitoring_active=True,
            monitor_phase="active",
            scanning_count=3,
            last_monitor_message="Price fetch failed",
            current_price=0,
        )
        self.assertFalse(result["is_scanning"])
        self.assertEqual(result["display_error"], "Price fetch failed")

    def test_last_monitor_log_line_skips_transient_when_price_valid(self):
        class ScanLog:
            logs = "Price fetch failed\nTRACKING: Monitoring: armed"

        self.assertEqual(
            self.last_line(ScanLog(), current_price=100.0),
            "TRACKING: Monitoring: armed",
        )


if __name__ == "__main__":
    unittest.main()
