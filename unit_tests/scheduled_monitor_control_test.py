import unittest
from unittest.mock import patch

from utils import scheduled_monitor_control as control


class TestScheduledMonitorControl(unittest.TestCase):
    def test_should_auto_run_requires_market_and_login(self):
        with patch.object(control, "get_market_hours_status", return_value={"market_hours_open": True}), patch.object(
            control, "has_logged_in_tms_users", return_value=True
        ):
            self.assertTrue(control.should_auto_run_scheduler())

        with patch.object(control, "get_market_hours_status", return_value={"market_hours_open": False}), patch.object(
            control, "has_logged_in_tms_users", return_value=True
        ):
            self.assertFalse(control.should_auto_run_scheduler())

        with patch.object(control, "get_market_hours_status", return_value={"market_hours_open": True}), patch.object(
            control, "has_logged_in_tms_users", return_value=False
        ):
            self.assertFalse(control.should_auto_run_scheduler())
