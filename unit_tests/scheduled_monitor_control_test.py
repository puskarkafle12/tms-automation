import unittest
from unittest.mock import patch

import config.tms_config as tms_config
from utils import scheduled_monitor_control as control


class TestScheduledMonitorControl(unittest.TestCase):
    def test_should_auto_run_requires_market_and_login(self):
        with patch.object(control, "is_market_polling_window", return_value=True), patch.object(
            control, "has_logged_in_tms_users", return_value=True
        ):
            self.assertTrue(control.should_auto_run_scheduler())

        with patch.object(control, "is_market_polling_window", return_value=False), patch.object(
            control, "has_logged_in_tms_users", return_value=True
        ), patch.object(control, "is_testing", return_value=False):
            self.assertFalse(control.should_auto_run_scheduler())

        with patch.object(control, "is_market_polling_window", return_value=True), patch.object(
            control, "has_logged_in_tms_users", return_value=False
        ):
            self.assertFalse(control.should_auto_run_scheduler())

    def test_display_status_waiting_when_market_closed(self):
        tms_config.is_running = False
        with patch.object(control, "is_market_polling_window", return_value=False), patch.object(
            control, "has_logged_in_tms_users", return_value=True
        ), patch.object(control, "is_testing", return_value=False):
            status = control.get_scheduler_display_status()
        self.assertEqual(status["scheduled_phase"], "waiting_hours")
        self.assertFalse(status["scheduled_orders_active"])
        self.assertIn("waiting for market", status["scheduled_status_message"].lower())

    def test_testing_mode_auto_runs_outside_market_hours(self):
        with patch.object(control, "is_market_polling_window", return_value=False), patch.object(
            control, "has_logged_in_tms_users", return_value=True
        ), patch.object(control, "is_testing", return_value=True):
            self.assertTrue(control.should_auto_run_scheduler())
        tms_config.is_running = False
        with patch.object(control, "is_market_polling_window", return_value=False), patch.object(
            control, "has_logged_in_tms_users", return_value=True
        ), patch.object(control, "is_testing", return_value=True):
            status = control.get_scheduler_display_status()
        self.assertEqual(status["scheduled_phase"], "armed")
        self.assertIn("test mode", status["scheduled_status_message"].lower())

    def test_display_status_waiting_when_not_logged_in(self):
        tms_config.is_running = False
        with patch.object(control, "is_market_polling_window", return_value=True), patch.object(
            control, "has_logged_in_tms_users", return_value=False
        ):
            status = control.get_scheduler_display_status()
        self.assertEqual(status["scheduled_phase"], "waiting_session")
        self.assertIn("log in", status["scheduled_status_message"].lower())
