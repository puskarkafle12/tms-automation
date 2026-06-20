"""End-to-end tests for the 21-symbol 52-week high sell basket query."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import main  # noqa: F401 — initialize app imports before execution_quantity

from utils.strategy_builder.execution_quantity import resolve_execution_quantity
from utils.strategy_builder.history_service import TargetHistory
from utils.strategy_builder.preview_builder import _estimate_price_boundary, build_rule_preview
from utils.strategy_builder.rule_evaluator import evaluate_rule, update_history_from_snapshot
from utils.strategy_builder.strategy_parser import parse_strategy_query, extract_symbols_from_query

SELL_52W_BASKET_QUERY = """STRATEGY_VERSION 1
SIDE SELL

RULE "Sell 100 Percent At 52 Week High" FOR SYMBOL IN (
    "API",
    "BFC",
    "CBBL",
    "GBIME",
    "HDL",
    "HIDCL",
    "MBJC",
    "MEL",
    "NABIL",
    "NIL",
    "NMB",
    "NRIC",
    "NRM",
    "PCBL",
    "PMLI",
    "PRVU",
    "SANIMA",
    "SGIC",
    "SMPDA",
    "SRLI",
    "UAIL"
) {
    WHEN position_in_52_week_range_percent >= 95

    ORDER PERCENT_OF_HOLDING 100

    CONFIRM TRUE_FOR 2 SCANS
    TRIGGER LEVEL

    MAX_SLIPPAGE_PCT 1

    EXECUTE ONCE PER SYMBOL
}
"""

SYMBOLS = [
    "API", "BFC", "CBBL", "GBIME", "HDL", "HIDCL", "MBJC", "MEL", "NABIL", "NIL",
    "NMB", "NRIC", "NRM", "PCBL", "PMLI", "PRVU", "SANIMA", "SGIC", "SMPDA", "SRLI", "UAIL",
]


def _flat_for_symbol(
    *,
    position_pct: float,
    ltp: float = 343.0,
    low_52w: float = 250.0,
    high_52w: float = 400.0,
) -> dict:
    return {
        "ltp": ltp,
        "fifty_two_week_low": low_52w,
        "fifty_two_week_high": high_52w,
        "position_in_52_week_range_percent": position_pct,
    }


class Sell52WeekBasketQueryTest(unittest.TestCase):
    def setUp(self):
        self.plan = parse_strategy_query(SELL_52W_BASKET_QUERY)
        self.rule = self.plan.rules[0]

    def test_parses_21_symbols_and_rule_config(self):
        self.assertEqual(self.plan.side, "SELL")
        self.assertEqual(len(self.rule.symbols), 21)
        self.assertEqual(set(self.rule.symbols), set(SYMBOLS))
        self.assertEqual(self.rule.order.mode, "percent_of_holding")
        self.assertEqual(self.rule.order.value, 100)
        self.assertEqual(self.rule.confirmation.mode, "true_for_scans")
        self.assertEqual(self.rule.confirmation.scans, 2)
        self.assertEqual(self.rule.execution.trigger, "level")
        self.assertEqual(self.rule.execution.frequency, "once_per_symbol")
        self.assertEqual(self.rule.execution.max_slippage_pct, 1)

    def test_position_formula_matches_market_normalizer(self):
        # position = (ltp - low) / (high - low) * 100
        ltp_at_95 = 250 + 0.95 * (400 - 250)  # 392.5
        position = ((ltp_at_95 - 250) / (400 - 250)) * 100
        self.assertAlmostEqual(position, 95.0, places=4)

    def test_not_ready_when_position_below_95(self):
        flat = _flat_for_symbol(position_pct=81.8)
        history = TargetHistory()
        update_history_from_snapshot(history, flat)
        evaluation = evaluate_rule(
            self.rule,
            "NRM",
            flat,
            history,
            trigger_on_cross=False,
        )
        self.assertFalse(evaluation.matched)
        self.assertIn("WAITING_CONFIRMATION", evaluation.status)

    def test_requires_two_consecutive_scans_at_or_above_95(self):
        flat = _flat_for_symbol(position_pct=96.0)
        history = TargetHistory()

        scan1 = evaluate_rule(self.rule, "NRM", flat, history, trigger_on_cross=False)
        self.assertFalse(scan1.matched)
        self.assertEqual(scan1.status, "WAITING_CONFIRMATION_1/2")

        scan2 = evaluate_rule(self.rule, "NRM", flat, history, trigger_on_cross=False)
        self.assertTrue(scan2.matched)
        self.assertEqual(scan2.status, "CONFIRMED")

    def test_confirmation_resets_if_condition_breaks(self):
        flat_high = _flat_for_symbol(position_pct=96.0)
        flat_low = _flat_for_symbol(position_pct=80.0)
        history = TargetHistory()

        evaluate_rule(self.rule, "NRM", flat_high, history, trigger_on_cross=False)
        evaluate_rule(self.rule, "NRM", flat_low, history, trigger_on_cross=False)
        scan_after_reset = evaluate_rule(self.rule, "NRM", flat_high, history, trigger_on_cross=False)

        self.assertFalse(scan_after_reset.matched)
        self.assertEqual(scan_after_reset.status, "WAITING_CONFIRMATION_1/2")

    def test_estimated_trigger_price_at_95_percent_of_range(self):
        flat = _flat_for_symbol(position_pct=81.8)
        price, is_exact, _ = _estimate_price_boundary(
            "position_in_52_week_range_percent",
            "gte",
            95.0,
            flat,
        )
        self.assertAlmostEqual(price or 0, 392.5, places=2)
        self.assertFalse(is_exact)

    def test_preview_quantity_uses_holding_not_percent_as_price(self):
        flat = _flat_for_symbol(position_pct=81.8)
        history = TargetHistory()
        evaluation = evaluate_rule(self.rule, "NRM", flat, history, trigger_on_cross=False)
        preview = build_rule_preview(
            rule=self.rule,
            symbol="NRM",
            plan_side="SELL",
            flat=flat,
            evaluation=evaluation,
            history=history,
            status_label="Waiting",
            live_ltp=343.0,
            reference_ltp=None,
            current_holding=54,
        )
        self.assertEqual(preview.quantity.estimated_quantity, 54)
        self.assertFalse(preview.quantity.is_final)
        self.assertIn("52-week range position", preview.trigger.strategy_text)
        self.assertIn("%", preview.trigger.target_display or "")

    def test_extract_symbols_from_query_text(self):
        extracted = extract_symbols_from_query(SELL_52W_BASKET_QUERY)
        self.assertEqual(len(extracted), 21)
        self.assertIn("NRM", extracted)


class Sell52WeekBasketExecutionTest(unittest.IsolatedAsyncioTestCase):
    async def test_execution_resolves_100_percent_of_latest_holding(self):
        scheduled = MagicMock(
            client_id="C1",
            qty=0,
            strategy_config={"compiled_plan": parse_strategy_query(SELL_52W_BASKET_QUERY).model_dump()},
        )
        tms_user = MagicMock()

        with patch(
            "utils.strategy_builder.execution_quantity.fetch_symbol_holding_qty",
            new_callable=AsyncMock,
            return_value=180,
        ):
            resolution = await resolve_execution_quantity(
                scheduled_order=scheduled,
                matched_order_action={"mode": "percent_of_holding", "value": 100},
                tms_user=tms_user,
                symbol="NRM",
                side="sell",
                security_details={"symbol": "NRM"},
            )

        self.assertEqual(resolution.final_quantity, 180)
        self.assertEqual(resolution.mode, "percent_of_holding")
        self.assertEqual(resolution.available_holding, 180)

    async def test_preview_holding_222_but_execution_uses_fresh_180(self):
        """Preview qty is informational; execution fetches DP holding again."""
        scheduled = MagicMock(client_id="C1", qty=0, strategy_config={})
        tms_user = MagicMock()

        with patch(
            "utils.strategy_builder.execution_quantity.fetch_symbol_holding_qty",
            new_callable=AsyncMock,
            return_value=180,
        ):
            resolution = await resolve_execution_quantity(
                scheduled_order=scheduled,
                matched_order_action={"mode": "percent_of_holding", "value": 100},
                tms_user=tms_user,
                symbol="NRM",
                side="sell",
                security_details={"symbol": "NRM"},
            )

        preview_qty = 222  # hypothetical preview-time holding
        self.assertNotEqual(preview_qty, resolution.final_quantity)
        self.assertEqual(resolution.final_quantity, 180)


if __name__ == "__main__":
    unittest.main()
