import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from schemas.schemas import OrderCreateRequest
from utils.strategy_builder.schedule_preview_capture import (
    _snapshot_missing_trigger,
    apply_schedule_preview_snapshot,
    snapshot_from_preview_row,
    snapshots_from_preview_rows,
)


SELL_QUERY = """STRATEGY_VERSION 1
SIDE SELL
RULE "Sell" FOR SYMBOL "NRM" {
    WHEN position_in_52_week_range_percent >= 95
    ORDER PERCENT_OF_HOLDING 100
    EXECUTE ONCE PER SYMBOL
}
"""

COMPILED_PLAN = {
    "version": 1,
    "side": "SELL",
    "rules": [
        {
            "rule_id": "sell-nrm",
            "name": "Sell",
            "symbols": ["NRM"],
            "when": {
                "type": "comparison",
                "left": {"type": "field", "name": "position_in_52_week_range_percent"},
                "operator": "gte",
                "right": {"type": "literal", "value": 95},
            },
            "order": {"mode": "percent_of_holding", "value": 100},
            "confirmation": {"mode": "true_for_scans", "scans": 2},
            "execution": {"trigger": "level", "frequency": "once_per_symbol"},
        }
    ],
}


class SchedulePreviewCaptureTest(unittest.IsolatedAsyncioTestCase):
    def test_snapshot_from_preview_row_maps_trigger_and_quantity(self):
        snapshot = snapshot_from_preview_row(
            {
                "preview_ltp": 332.0,
                "reference_ltp": None,
                "reason": "Current value is 81.80%; required is 95.00%.",
                "trigger": {
                    "strategy_text": "52-week range position ≥ 95.00%",
                    "estimated_price": 392.5,
                    "estimated_price_display": "Rs. 392.50 (est.)",
                    "is_exact_price": False,
                    "current_display": "81.80%",
                    "target_display": "95.00%",
                },
                "quantity": {
                    "description": "Sell 100% of current holding",
                    "estimated_quantity": 54,
                    "estimated_quantity_display": "54",
                },
                "confirmation": {"display": "0 / 2 scans"},
                "execution_price": {"description": "Current LTP"},
            }
        )
        self.assertAlmostEqual(snapshot["estimated_trigger_price"], 392.5)
        self.assertEqual(snapshot["estimated_quantity"], 54)
        self.assertIn("52-week range position", snapshot["trigger_strategy_text"])
        self.assertEqual(snapshot["estimated_quantity_display"], "54")
        self.assertEqual(snapshot["confirmation_display"], "0 / 2 scans")
        self.assertIn("captured_at", snapshot)

    @patch("utils.strategy_builder.preview_service._preview_symbol", new_callable=AsyncMock)
    async def test_apply_schedule_preview_snapshot_persists_trigger_price(self, mock_preview):
        mock_preview.return_value = {
            "preview_ltp": 332.0,
            "trigger": {
                "strategy_text": "52-week range position ≥ 95.00%",
                "estimated_price": 392.5,
                "estimated_price_display": "Rs. 392.50 (est.)",
                "is_exact_price": False,
                "current_display": "81.80%",
                "target_display": "95.00%",
            },
            "quantity": {
                "description": "Sell 100% of current holding",
                "estimated_quantity": 54,
                "estimated_quantity_display": "54",
            },
            "confirmation": {"display": "0 / 2 scans"},
            "execution_price": {"description": "Current LTP"},
            "reason": "Current value is 81.80%; required is 95.00%.",
        }
        order_data = OrderCreateRequest(
            client_id="C1",
            script_name="NRM",
            order_type="sell",
            price=0,
            qty=0,
            status="Waiting",
            strategy_type="Custom Query Sell",
            strategy_config={
                "query_text": SELL_QUERY,
                "compiled_plan": COMPILED_PLAN,
            },
        )
        order = MagicMock()
        order.strategy_config = dict(order_data.strategy_config or {})
        order.trigger_price = None
        order.qty = 0
        order.remaining_quantity = 0

        db = MagicMock()
        await apply_schedule_preview_snapshot(order, order_data, db)

        self.assertAlmostEqual(order.trigger_price, 392.5)
        self.assertEqual(order.qty, 54)
        self.assertEqual(order.remaining_quantity, 54)
        snapshot = order.strategy_config["schedule_preview_snapshot"]
        self.assertAlmostEqual(snapshot["estimated_trigger_price"], 392.5)
        self.assertEqual(snapshot["estimated_quantity"], 54)
        self.assertEqual(snapshot["trigger_strategy_text"], "52-week range position ≥ 95.00%")

    def test_snapshot_missing_trigger_detects_unavailable(self):
        self.assertTrue(_snapshot_missing_trigger({"estimated_trigger_price_display": "Unavailable"}))
        self.assertFalse(_snapshot_missing_trigger({"estimated_trigger_price": 392.5}))

    def test_snapshot_missing_trigger_accepts_signal_based(self):
        self.assertFalse(_snapshot_missing_trigger({
            "trigger_kind": "non_price_condition",
            "estimated_trigger_price": None,
            "estimated_trigger_price_display": "SMA 20 crossed above",
        }))

    def test_snapshot_from_preview_row_maps_signal_based_trigger(self):
        snapshot = snapshot_from_preview_row({
            "trigger": {
                "kind": "non_price_condition",
                "strategy_text": "SMA 20 crossed above",
                "estimated_price": None,
                "estimated_price_display": None,
            },
            "quantity": {"estimated_quantity": 100, "estimated_quantity_display": "100"},
        })
        self.assertEqual(snapshot["trigger_kind"], "non_price_condition")
        self.assertEqual(snapshot["estimated_trigger_price_display"], "SMA 20 crossed above")
        self.assertFalse(_snapshot_missing_trigger(snapshot))

    def test_snapshot_keeps_each_condition_and_logic_for_order_details(self):
        snapshot = snapshot_from_preview_row({
            "trigger": {
                "kind": "non_price_condition",
                "strategy_text": "SMA trend and bullish MACD",
                "logic": "AND",
                "conditions": [
                    {"strategy_text": "SMA 20 is above", "matched": True, "current_display": "above", "target_display": "above"},
                    {"strategy_text": "MACD is bullish", "matched": False, "current_display": "Bearish", "target_display": "Bullish"},
                ],
            }
        })
        self.assertEqual(snapshot["condition_logic"], "AND")
        self.assertEqual(len(snapshot["conditions"]), 2)
        self.assertTrue(snapshot["conditions"][0]["matched"])
        self.assertFalse(snapshot["conditions"][1]["matched"])

    def test_snapshots_from_preview_rows_indexes_by_symbol(self):
        snapshots = snapshots_from_preview_rows([
            {
                "symbol": "NRM",
                "trigger": {"estimated_price": 392.5, "estimated_price_display": "Rs. 392.50 (est.)"},
                "quantity": {"estimated_quantity": 20, "estimated_quantity_display": "20"},
            },
            {
                "symbol": "API",
                "trigger": {"estimated_price": 358.38, "estimated_price_display": "Rs. 358.38 (est.)"},
                "quantity": {"estimated_quantity": 54, "estimated_quantity_display": "54"},
            },
        ])
        self.assertAlmostEqual(snapshots["NRM"]["estimated_trigger_price"], 392.5)
        self.assertEqual(snapshots["API"]["estimated_quantity"], 54)

    async def test_apply_uses_precomputed_snapshot_without_live_preview(self):
        order_data = OrderCreateRequest(
            client_id="C1",
            script_name="NRM",
            order_type="sell",
            price=0,
            qty=0,
            status="Waiting",
            strategy_type="Custom Query Sell",
            strategy_config={
                "compiled_plan": COMPILED_PLAN,
                "schedule_preview_snapshots_by_symbol": {
                    "NRM": {
                        "estimated_trigger_price": 392.5,
                        "estimated_trigger_price_display": "Rs. 392.50 (est.)",
                        "estimated_quantity": 20,
                        "estimated_quantity_display": "20",
                    },
                },
            },
        )
        order = MagicMock()
        order.strategy_config = dict(order_data.strategy_config or {})
        order.trigger_price = None
        order.qty = 0
        order.remaining_quantity = 0

        with patch("utils.strategy_builder.preview_service._preview_symbol", new_callable=AsyncMock) as mock_preview:
            await apply_schedule_preview_snapshot(order, order_data, MagicMock())
            mock_preview.assert_not_called()

        self.assertAlmostEqual(order.trigger_price, 392.5)
        self.assertEqual(order.qty, 20)

    @patch("utils.strategy_builder.preview_service._preview_symbol", new_callable=AsyncMock)
    async def test_capture_retries_until_trigger_available(self, mock_preview):
        from utils.strategy_builder.schedule_preview_capture import capture_schedule_preview_snapshot

        mock_preview.side_effect = [
            {
                "preview_ltp": 332.0,
                "trigger": {
                    "estimated_price": None,
                    "estimated_price_display": "Unavailable",
                },
                "quantity": {"estimated_quantity": 54, "estimated_quantity_display": "54"},
            },
            {
                "preview_ltp": 332.0,
                "trigger": {
                    "estimated_price": 392.5,
                    "estimated_price_display": "Rs. 392.50 (est.)",
                },
                "quantity": {"estimated_quantity": 54, "estimated_quantity_display": "54"},
            },
        ]
        order_data = OrderCreateRequest(
            client_id="C1",
            script_name="NRM",
            order_type="sell",
            price=0,
            qty=0,
            status="pending",
            strategy_type="Custom Query Sell",
            strategy_config={"compiled_plan": COMPILED_PLAN},
        )
        snapshot = await capture_schedule_preview_snapshot(order_data, MagicMock(), max_attempts=2)
        self.assertAlmostEqual(snapshot["estimated_trigger_price"], 392.5)
        self.assertEqual(mock_preview.call_count, 2)

    @patch("utils.strategy_builder.preview_service._preview_symbol", new_callable=AsyncMock)
    async def test_capture_skips_non_custom_query(self, mock_preview):
        from utils.strategy_builder.schedule_preview_capture import capture_schedule_preview_snapshot

        order_data = OrderCreateRequest(
            client_id="C1",
            script_name="NRM",
            order_type="sell",
            price=500,
            qty=10,
            status="pending",
            strategy_type="Fixed Price Sell",
        )
        result = await capture_schedule_preview_snapshot(order_data, MagicMock())
        self.assertIsNone(result)
        mock_preview.assert_not_called()


if __name__ == "__main__":
    unittest.main()
