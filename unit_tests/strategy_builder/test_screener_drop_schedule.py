import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from utils.strategy_builder.screener_drop_schedule import (
    build_default_screener_drop_query,
    commit_screener_drop_batch,
    map_expiration_action,
    preview_screener_drop_batch,
    recalculate_trigger_from_reference,
    resolve_query_for_symbol,
)


QUERY = """STRATEGY_VERSION 1
SIDE BUY
RULE "Drop Buy" FOR SYMBOL "API" {
    WHEN technical_rsi_14 < 70
    ORDER QUANTITY 10
    EXECUTE ONCE PER SYMBOL
}"""


class ScreenerDropScheduleTest(unittest.TestCase):
    def test_map_expiration_action_from_frontend_label(self):
        self.assertEqual(map_expiration_action("Cancel strategy"), "CANCEL")
        self.assertEqual(map_expiration_action("Buy at protected LTP"), "BUY_AT_PROTECTED_LTP")

    def test_recalculate_trigger_from_reference(self):
        self.assertEqual(recalculate_trigger_from_reference(500, 10), 450.0)

    def test_resolve_query_for_symbol_builds_default_when_missing(self):
        query = resolve_query_for_symbol("", "NABIL", 10)
        self.assertIn("NABIL", query)
        self.assertIn("ORDER QUANTITY 10", query)

    def test_build_default_screener_drop_query(self):
        query = build_default_screener_drop_query("API", 25)
        self.assertIn('"API"', query)
        self.assertIn("ORDER QUANTITY 25", query)


class AsyncScreenerDropScheduleTest(unittest.IsolatedAsyncioTestCase):
    async def test_preview_batch_returns_rows(self):
        db = MagicMock()
        tms_user = AsyncMock()
        tms_user.get_security_id.return_value = {"id": "1"}
        tms_user.get_stock_details_async.return_value = {"ltp": 500, "lastTradedTime": "2026-06-19T10:00:00"}

        with patch(
            "utils.tms_client_resolver.get_tms_user_for_client",
            new=AsyncMock(return_value=tms_user),
        ):
            result = await preview_screener_drop_batch(
                db,
                client_id="client-1",
                query_text=QUERY,
                symbols=["API"],
                drop_percent=10,
                expiry_time=datetime.utcnow() + timedelta(hours=2),
                expiry_action="CANCEL",
            )

        self.assertTrue(result["ready"])
        self.assertEqual(len(result["rows"]), 1)
        self.assertEqual(result["rows"][0]["trigger_price"], 450.0)

    async def test_commit_batch_creates_orders(self):
        db = MagicMock()
        user = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = user
        db.add = MagicMock()
        db.flush = MagicMock()
        db.commit = MagicMock()
        db.rollback = MagicMock()

        tms_user = AsyncMock()
        tms_user.get_security_id.return_value = {"id": "1"}
        tms_user.get_stock_details_async.return_value = {"ltp": 500, "lastTradedTime": "2026-06-19T10:00:00"}

        order = MagicMock(order_id=42, reference_ltp=500, trigger_price=450, qty=10, expiry_time=datetime.utcnow())

        with patch(
            "utils.tms_client_resolver.get_tms_user_for_client",
            new=AsyncMock(return_value=tms_user),
        ), patch(
            "utils.strategy_builder.screener_drop_schedule.run_schedule_preflight",
            new=AsyncMock(return_value={"ready": True}),
        ), patch(
            "utils.strategy_builder.screener_drop_schedule.ScheduledOrder",
            return_value=order,
        ):
            result = await commit_screener_drop_batch(
                db,
                client_id="client-1",
                query_text=QUERY,
                symbols=["API"],
                drop_percent=10,
                expiry_time=datetime.utcnow() + timedelta(hours=2),
                expiry_action="CANCEL",
            )

        self.assertEqual(len(result["scheduled"]), 1)
        self.assertEqual(result["scheduled"][0]["symbol"], "API")
        db.commit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
