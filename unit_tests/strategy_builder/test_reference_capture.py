import unittest
from unittest.mock import AsyncMock, patch

from utils.strategy_builder.reference_capture import ReferenceCaptureError, capture_references_for_plan
from utils.strategy_builder.strategy_parser import parse_strategy_query


QUERY = """STRATEGY_VERSION 1
SIDE BUY
RULE "Pullback" FOR SYMBOL "API" {
    WHEN ltp <= REFERENCE(field=ltp) * 0.90
    ORDER QUANTITY 10
}"""


class ReferenceCaptureTest(unittest.IsolatedAsyncioTestCase):
    async def test_capture_only_referenced_fields(self):
        plan = parse_strategy_query(QUERY)
        tms_user = AsyncMock()
        flat = {"ltp": 500.0, "volume": 100000.0}
        with patch(
            "utils.strategy_builder.reference_capture._fetch_symbol_flat",
            new=AsyncMock(return_value=flat),
        ):
            rows = await capture_references_for_plan(tms_user, symbol="API", plan=plan)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].field_key, "ltp")
        self.assertEqual(rows[0].numeric_value, 500.0)
        self.assertEqual(rows[0].symbol, "API")

    async def test_missing_value_raises(self):
        plan = parse_strategy_query(QUERY)
        tms_user = AsyncMock()
        with patch(
            "utils.strategy_builder.reference_capture._fetch_symbol_flat",
            new=AsyncMock(return_value={"volume": 100}),
        ):
            with self.assertRaises(ReferenceCaptureError) as ctx:
                await capture_references_for_plan(tms_user, symbol="API", plan=plan)
        self.assertEqual(ctx.exception.code, "REFERENCE_VALUE_REQUIRED")


if __name__ == "__main__":
    unittest.main()
