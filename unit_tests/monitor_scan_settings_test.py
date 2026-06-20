import unittest
from types import SimpleNamespace
from unittest.mock import patch

from utils.monitor_scan_settings import (
    MAX_SCAN_INTERVAL_SECONDS,
    MIN_SCAN_INTERVAL_SECONDS,
    advance_nepse_alpha_scan_due_at,
    advance_tms_scan_due_at,
    ensure_scan_phase_offset_in_config,
    filter_due_order_ids,
    initial_tms_scan_due_at,
    normalize_monitor_settings,
    order_requires_nepse_alpha,
    resolve_max_data_age_seconds,
    resolve_scan_interval_seconds,
    resolve_scan_phase_offset_seconds,
)
from utils.strategy_builder.strategy_parser import parse_strategy_query


CZBIL_RSI_QUERY = """
STRATEGY_VERSION 1
SIDE BUY
RULE "CZBIL Rule" FOR SYMBOL "CZBIL" {
    WHEN technical_rsi_14 < 70
    ORDER QUANTITY 100
    EXECUTE ONCE
}
"""

LTP_ONLY_QUERY = """
STRATEGY_VERSION 1
SIDE BUY
RULE "LTP" FOR SYMBOL "CZBIL" {
    WHEN ltp <= 200
    ORDER QUANTITY 10
    EXECUTE ONCE
}
"""


def _order(*, query: str, strategy_type: str = "Custom Query Buy", order_id: int = 42):
    compiled = parse_strategy_query(query).model_dump()
    return SimpleNamespace(
        order_id=order_id,
        order_type="buy",
        strategy_type=strategy_type,
        strategy_config={"compiled_plan": compiled},
    )


class MonitorScanSettingsTest(unittest.TestCase):
    def test_defaults_to_portal_interval(self):
        with patch("utils.monitor_scan_settings.tms_config.monitor_interval", 8):
            self.assertEqual(resolve_scan_interval_seconds(None), 8)

    def test_clamps_custom_interval(self):
        with patch("utils.monitor_scan_settings.tms_config.monitor_interval", 5):
            self.assertEqual(resolve_scan_interval_seconds({"scan_interval_seconds": 1}), MIN_SCAN_INTERVAL_SECONDS)
            self.assertEqual(
                resolve_scan_interval_seconds({"scan_interval_seconds": 999999}),
                MAX_SCAN_INTERVAL_SECONDS,
            )
            self.assertEqual(resolve_scan_interval_seconds({"scan_interval_seconds": 12}), 12)

    def test_max_data_age_optional(self):
        self.assertIsNone(resolve_max_data_age_seconds({}))
        self.assertEqual(resolve_max_data_age_seconds({"max_data_age_seconds": 45}), 45)

    def test_normalize_monitor_settings(self):
        normalized = normalize_monitor_settings({"scan_interval_seconds": 10, "execution_mode": "paper"})
        self.assertEqual(normalized["scan_interval_seconds"], 10)
        self.assertEqual(normalized["execution_mode"], "paper")

    def test_order_requires_nepse_alpha_for_rsi_plan(self):
        self.assertTrue(order_requires_nepse_alpha(_order(query=CZBIL_RSI_QUERY)))

    def test_order_does_not_require_nepse_alpha_for_ltp_plan(self):
        self.assertFalse(order_requires_nepse_alpha(_order(query=LTP_ONLY_QUERY)))

    def test_order_does_not_require_nepse_alpha_for_fixed_price(self):
        order = SimpleNamespace(
            order_id=1,
            order_type="buy",
            strategy_type="Fixed Price Buy",
            strategy_config={},
        )
        self.assertFalse(order_requires_nepse_alpha(order))

    def test_stable_scan_phase_offset_from_order_id(self):
        self.assertEqual(resolve_scan_phase_offset_seconds(17, 20), 17)
        self.assertEqual(resolve_scan_phase_offset_seconds(17, 20, {"scan_phase_offset_seconds": 3}), 3)

    def test_stagger_disabled_uses_zero_offset(self):
        self.assertEqual(resolve_scan_phase_offset_seconds(17, 20, stagger_enabled=False), 0)

    def test_ensure_scan_phase_offset_persists_in_config(self):
        config, offset = ensure_scan_phase_offset_in_config({}, 23, 20)
        self.assertEqual(offset, 3)
        self.assertEqual(config["scan_phase_offset_seconds"], 3)

    def test_initial_tms_scan_due_spreads_by_offset(self):
        now = 1000.0
        with patch("utils.monitor_scan_settings.random.uniform", return_value=7.5):
            due_at = initial_tms_scan_due_at(now, 7, 20)
        self.assertEqual(due_at, now + 7.5)

    def test_initial_tms_scan_due_uses_now_when_stagger_disabled(self):
        now = 1000.0
        due_at = initial_tms_scan_due_at(now, 7, 20, stagger_enabled=False)
        self.assertEqual(due_at, now)

    def test_advance_tms_scan_due_uses_random_next_window(self):
        with patch("utils.monitor_scan_settings.random.uniform", return_value=3.0):
            self.assertEqual(advance_tms_scan_due_at(505.0, 20), 523.0)

    def test_advance_tms_scan_due_adds_interval_when_stagger_disabled(self):
        self.assertEqual(advance_tms_scan_due_at(500.0, 20, stagger_enabled=False), 520.0)

    def test_advance_nepse_alpha_scan_due_uses_random_next_window(self):
        with patch("utils.monitor_scan_settings.random.uniform", return_value=11.0):
            self.assertEqual(advance_nepse_alpha_scan_due_at(125.0, 60), 191.0)

    def test_filter_due_order_ids(self):
        now = 100.0
        next_scan = {1: 90.0, 2: 110.0, 3: 100.0}
        self.assertEqual(filter_due_order_ids({1, 2, 3}, next_scan, now=now), {1, 3})


if __name__ == "__main__":
    unittest.main()
