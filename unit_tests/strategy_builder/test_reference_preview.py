import unittest
from unittest.mock import AsyncMock, patch

from utils.strategy_builder.preview_service import build_rule_previews
from utils.strategy_builder.reference_store import ReferenceRow, ReferenceStore
from utils.strategy_builder.strategy_parser import parse_strategy_query


MULTI_SYMBOL_QUERY = """STRATEGY_VERSION 1
SIDE BUY
RULE "Pullback" FOR SYMBOL IN ("NABIL", "NTC") {
    ELIGIBILITY ltp <= REFERENCE(field=ltp) * 0.90
    WHEN technical_rsi_14 < 70
    ORDER QUANTITY 10
}"""


class PreviewReferenceCaptureTest(unittest.IsolatedAsyncioTestCase):
    async def test_preview_auto_captures_live_references_per_symbol(self):
        plan = parse_strategy_query(MULTI_SYMBOL_QUERY)
        store = ReferenceStore.from_rows(
            [
                ReferenceRow(
                    rule_name="Pullback",
                    symbol="NABIL",
                    field_key="ltp",
                    field_type="decimal",
                    numeric_value=500.0,
                ),
                ReferenceRow(
                    rule_name="Pullback",
                    symbol="NTC",
                    field_key="ltp",
                    field_type="decimal",
                    numeric_value=400.0,
                ),
            ]
        )
        with patch(
            "utils.tms_client_resolver.get_tms_user_for_client",
            new=AsyncMock(return_value=object()),
        ), patch(
            "utils.strategy_builder.reference_capture.capture_references_for_preview_plan",
            new=AsyncMock(return_value=store),
        ), patch(
            "utils.strategy_builder.preview_service._preview_symbol",
            new=AsyncMock(
                side_effect=[
                    {"symbol": "NABIL", "matched": False, "status": "NOT_ELIGIBLE"},
                    {"symbol": "NTC", "matched": False, "status": "NOT_ELIGIBLE"},
                ]
            ),
        ) as preview_symbol:
            rows = await build_rule_previews(plan, client_id="C1", db=object())
        self.assertEqual(len(rows), 2)
        self.assertEqual(preview_symbol.await_count, 2)
        passed_store = preview_symbol.await_args_list[0].kwargs["reference_store"]
        self.assertIsNotNone(passed_store.get_row("Pullback", "NABIL", "ltp"))


if __name__ == "__main__":
    unittest.main()
