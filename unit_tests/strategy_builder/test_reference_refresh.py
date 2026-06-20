import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from utils.strategy_builder.reference_refresh import ReferenceRefreshError, refresh_field_references
from utils.strategy_builder.strategy_parser import parse_strategy_query


class ReferenceRefreshTest(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_updates_values_and_config_cache(self):
        db = MagicMock()
        order = MagicMock()
        order.client_id = "client-1"
        order.strategy_config = {
            "uses_field_references": True,
            "compiled_plan": parse_strategy_query(
                'STRATEGY_VERSION 1\nSIDE BUY\nRULE "Drop Buy" FOR SYMBOL "API" {\n'
                "WHEN ltp <= REFERENCE(field=ltp) * 0.90\nORDER QUANTITY 10\n}"
            ).model_dump(),
        }
        existing = MagicMock()
        existing.id = 1
        existing.rule_name = "Drop Buy"
        existing.symbol = "API"
        existing.field_key = "ltp"
        existing.numeric_value = 500.0
        existing.text_value = None
        existing.boolean_value = None
        existing.field_type = "decimal"
        existing.source = "tms_quote"
        existing.captured_at = datetime.now(timezone.utc)
        existing.refresh_count = 0

        db.query.return_value.filter.return_value.first.return_value = order
        db.query.return_value.filter.return_value.all.side_effect = [
            [existing],
            [existing],
            [existing],
        ]

        tms_user = AsyncMock()
        with patch(
            "utils.tms_client_resolver.get_tms_user_for_client",
            new=AsyncMock(return_value=tms_user),
        ), patch(
            "utils.strategy_builder.reference_capture._fetch_symbol_flat",
            new=AsyncMock(return_value={"ltp": 480.0}),
        ), patch(
            "utils.strategy_builder.reference_refresh.load_reference_store"
        ) as load_store:
            load_store.return_value.summary.return_value = {"API": {"ltp": {"numeric_value": 480.0}}}
            result = await refresh_field_references(db, 42, scope="all", refreshed_by="client-1")

        self.assertEqual(result["refreshed_count"], 1)
        self.assertEqual(existing.numeric_value, 480.0)
        self.assertEqual(order.strategy_config["field_reference_rows"][0]["numeric_value"], 480.0)
        db.add.assert_called()

    async def test_missing_order_raises(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        with self.assertRaises(ReferenceRefreshError):
            await refresh_field_references(db, 999)


if __name__ == "__main__":
    unittest.main()
