import unittest
from unittest.mock import AsyncMock, patch

from utils.strategy_builder.preview_service import build_rule_previews
from utils.strategy_builder.strategy_parser import parse_strategy_query
from utils.strategies.types import ScriptDetails


QUERY = (
    'STRATEGY_VERSION 1\nSIDE BUY\nRULE "CZBIL Rule" FOR SYMBOL "CZBIL" {\n'
    "WHEN technical_rsi_14 < 70\n"
    "ORDER QUANTITY 100\n"
    "MAX_SLIPPAGE_PCT 1\n"
    "EXECUTE ONCE\n"
    "}"
)


class PreviewPlanTest(unittest.IsolatedAsyncioTestCase):
    @patch("utils.strategy_builder.preview_service.get_script_details")
    @patch("utils.strategy_builder.preview_service._fetch_preview_quote", new_callable=AsyncMock)
    async def test_preview_does_not_return_missing_data_on_valid_quote(self, mock_quote, mock_details):
        mock_quote.return_value = None
        mock_details.return_value = ScriptDetails(
            available=True,
            rsi_14=50.0,
            fifty_two_week_high=420.0,
        )
        plan = parse_strategy_query(QUERY)
        previews = await build_rule_previews(plan)
        self.assertEqual(len(previews), 1)
        row = previews[0]
        self.assertNotEqual(row["status"], "MISSING_DATA")
        self.assertTrue(row["matched"])
        self.assertEqual(row["symbol"], "CZBIL")

    @patch("utils.strategy_builder.preview_service.get_script_details")
    @patch("utils.strategy_builder.preview_service._fetch_preview_quote", new_callable=AsyncMock)
    async def test_preview_forces_fresh_nepse_alpha_details(self, mock_quote, mock_details):
        mock_quote.return_value = {
            "ltp": 448.0,
            "topBuy": [{"price": 447.0, "quantity": 1000}],
            "topSell": [{"price": 449.0, "quantity": 900}],
        }
        mock_details.return_value = ScriptDetails(
            available=True,
            rsi_14=45.0,
            fifty_two_week_high=530.29,
            fifty_two_week_low=429.63,
        )
        plan = parse_strategy_query(
            'STRATEGY_VERSION 1\nSIDE BUY\nRULE "Near 52W Low" FOR SYMBOL "CHCL" {\n'
            "WHEN position_in_52_week_range_percent <= 20 AND technical_rsi_14 <= 50\n"
            "ORDER QUANTITY FROM_FORM\n"
            "EXECUTE ONCE PER SYMBOL\n"
            "}"
        )
        previews = await build_rule_previews(plan, client_id="C1", db=object())
        self.assertEqual(len(previews), 1)
        self.assertEqual(previews[0]["symbol"], "CHCL")
        self.assertTrue(previews[0]["matched"])
        mock_details.assert_called_once_with("CHCL", force_refresh=False)

    @patch("utils.strategy_builder.preview_service.get_script_details")
    @patch("utils.strategy_builder.preview_service._fetch_preview_quote", new_callable=AsyncMock)
    async def test_preview_not_matched_when_rsi_missing(self, mock_quote, mock_details):
        mock_quote.return_value = None
        mock_details.return_value = ScriptDetails(available=False, rsi_14=None, fifty_two_week_high=420.0)
        plan = parse_strategy_query(QUERY)
        previews = await build_rule_previews(plan)
        self.assertEqual(previews[0]["status"], "NOT_MATCHED")
        self.assertFalse(previews[0]["matched"])
        self.assertFalse(previews[0]["nepse_alpha_available"])
        self.assertIn("Nepse Alpha", previews[0].get("message", ""))

    @patch("utils.strategy_builder.preview_service.get_script_details")
    @patch("utils.strategy_builder.preview_service._fetch_preview_quote", new_callable=AsyncMock)
    async def test_preview_not_matched_when_rsi_above_threshold(self, mock_quote, mock_details):
        mock_quote.return_value = None
        mock_details.return_value = ScriptDetails(available=True, rsi_14=80.0, fifty_two_week_high=420.0)
        plan = parse_strategy_query(QUERY)
        previews = await build_rule_previews(plan)
        self.assertFalse(previews[0]["matched"])
        self.assertNotEqual(previews[0]["status"], "MISSING_DATA")


if __name__ == "__main__":
    unittest.main()
