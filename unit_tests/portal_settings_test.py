import unittest
from unittest.mock import MagicMock, patch

from config.portal_settings import (
    DEFAULTS,
    load_portal_settings,
    normalize_portal_settings,
    save_portal_settings,
)


class PortalSettingsTest(unittest.TestCase):
    def test_normalize_clamps_scan_interval(self):
        normalized = normalize_portal_settings({"monitor_interval_seconds": 1})
        self.assertEqual(normalized["monitor_interval_seconds"], 3)
        normalized = normalize_portal_settings({"monitor_interval_seconds": 999999})
        self.assertEqual(normalized["monitor_interval_seconds"], 86400)

    def test_normalize_scan_orchestration_defaults(self):
        normalized = normalize_portal_settings({})
        self.assertTrue(normalized["enable_scan_staggering"])
        self.assertEqual(normalized["nepse_alpha_interval_seconds"], 1800)
        self.assertEqual(normalized["monitor_tick_seconds"], 5)
        self.assertEqual(normalized["max_price_fetch_concurrency"], 5)

    def test_normalize_clamps_orchestration_values(self):
        normalized = normalize_portal_settings(
            {
                "nepse_alpha_interval_seconds": 10,
                "monitor_tick_seconds": 9,
                "max_price_fetch_concurrency": 99,
                "enable_scan_staggering": "false",
            }
        )
        self.assertEqual(normalized["nepse_alpha_interval_seconds"], 60)
        self.assertEqual(normalized["monitor_tick_seconds"], 9)
        self.assertEqual(normalized["max_price_fetch_concurrency"], 20)
        self.assertFalse(normalized["enable_scan_staggering"])

    def test_normalize_clamps_monitor_tick_high_values(self):
        normalized = normalize_portal_settings({"monitor_tick_seconds": 7200})
        self.assertEqual(normalized["monitor_tick_seconds"], 3600)

    def test_save_updates_tms_config(self):
        with patch("config.portal_settings.SETTINGS_FILE") as settings_file:
            settings_file.write_text = MagicMock()
            with patch("config.portal_settings.tms_config") as tms_config:
                saved = save_portal_settings({"monitor_interval_seconds": 12})
                self.assertEqual(saved["monitor_interval_seconds"], 12)
                self.assertEqual(tms_config.monitor_interval, 12)

    def test_load_defaults_when_missing_file(self):
        with patch("config.portal_settings.SETTINGS_FILE") as settings_file:
            settings_file.exists.return_value = False
            with patch("config.portal_settings.tms_config") as tms_config:
                loaded = load_portal_settings()
                self.assertEqual(loaded["monitor_interval_seconds"], DEFAULTS["monitor_interval_seconds"])
                self.assertEqual(tms_config.monitor_interval, DEFAULTS["monitor_interval_seconds"])


if __name__ == "__main__":
    unittest.main()
