import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from utils.strategy_builder.schedule_preflight import run_schedule_preflight
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

BLUE_CHIP_52W_QUERY = """STRATEGY_VERSION 1
SIDE BUY

RULE "Blue Chip Near 52 Week Low" FOR SYMBOL IN (
    "NABIL",
    "EBL",
    "SCB",
    "GBIME",
    "SANIMA",
    "NMB",
    "PRVU",
    "HBL",
    "NIFRA",
    "NTC",
    "PCBL",
    "CZBIL",
    "LICN",
    "NLIC",
    "SICL",
    "HIDCL",
    "CHCL",
    "NIMB",
    "SBL"
) {
    WHEN position_in_52_week_range_percent <= 20
    AND technical_rsi_14 <= 50

    ORDER QUANTITY FROM_FORM

    CONFIRM TRUE_FOR 2 SCANS
    TRIGGER LEVEL

    EXECUTE ONCE PER SYMBOL
}
"""


class SchedulePreflightTest(unittest.IsolatedAsyncioTestCase):
    def _mock_db(self, *, logged_in: bool = True, user_exists: bool = True):
        db = MagicMock()
        session_row = MagicMock() if logged_in else None
        user_row = MagicMock() if user_exists else None

        def query_side_effect(model):
            query = MagicMock()
            name = getattr(model, "__name__", str(model))
            if name == "LoggedInUsers":
                query.filter.return_value.first.return_value = session_row
            elif name == "User":
                query.filter.return_value.first.return_value = user_row
            return query

        db.query.side_effect = query_side_effect
        return db

    async def test_requires_logged_in_client(self):
        result = await run_schedule_preflight(
            query_text=QUERY,
            compiled_plan=None,
            strategy_type="Technical Buy",
            client_id=None,
            script_name="CZBIL",
            db=self._mock_db(),
        )
        self.assertFalse(result["ready"])
        self.assertEqual(result["status"], "monitor_unavailable")
        self.assertIn("logged-in TMS client", result["message"])

    async def test_rejects_unsupported_field(self):
        unsupported_query = (
            'STRATEGY_VERSION 1\nSIDE BUY\nRULE "ADX Rule" FOR SYMBOL "CZBIL" {\n'
            "WHEN technical_adx > 25\n"
            "ORDER QUANTITY 10\n"
            "EXECUTE ONCE\n"
            "}"
        )
        result = await run_schedule_preflight(
            query_text=unsupported_query,
            compiled_plan=None,
            strategy_type="Technical Buy",
            client_id="C1",
            script_name="CZBIL",
            db=self._mock_db(),
        )
        self.assertFalse(result["ready"])
        self.assertEqual(result["status"], "unsupported_feature")

    @patch("utils.tms_client_resolver.get_tms_user_for_client", new_callable=AsyncMock)
    @patch("utils.strategy_builder.schedule_preflight.get_script_details")
    async def test_ready_when_nepse_alpha_and_tms_available(self, mock_details, mock_get_tms):
        mock_details.return_value = ScriptDetails(available=True, rsi_14=50.0)
        tms_instance = MagicMock()
        tms_instance.broker_no = "58"
        tms_instance.get_security_id = AsyncMock(return_value={"id": 1})
        tms_instance.get_stock_details_async = AsyncMock(return_value={"ltp": 100})
        mock_get_tms.return_value = tms_instance

        result = await run_schedule_preflight(
            query_text=QUERY,
            compiled_plan=None,
            strategy_type="Technical Buy",
            client_id="C1",
            script_name="CZBIL",
            db=self._mock_db(),
        )
        self.assertTrue(result["ready"])
        self.assertEqual(result["status"], "ready")
        self.assertIsNotNone(result["compiled_plan"])

    @patch("utils.tms_client_resolver.get_tms_user_for_client", new_callable=AsyncMock)
    @patch("utils.strategy_builder.schedule_preflight.get_script_details")
    async def test_blocks_when_nepse_alpha_unavailable(self, mock_details, mock_get_tms):
        mock_details.return_value = ScriptDetails(available=False, rsi_14=None)
        mock_get_tms.return_value = MagicMock()

        result = await run_schedule_preflight(
            query_text=QUERY,
            compiled_plan=None,
            strategy_type="Technical Buy",
            client_id="C1",
            script_name="CZBIL",
            db=self._mock_db(),
        )
        self.assertFalse(result["ready"])
        self.assertEqual(result["status"], "missing_data")
        self.assertIn("Nepse Alpha", result["message"])

    @patch("utils.tms_client_resolver.get_tms_user_for_client", new_callable=AsyncMock)
    @patch("utils.strategy_builder.schedule_preflight.get_script_details")
    @patch("utils.strategy_builder.schedule_preflight.is_testing", return_value=False)
    async def test_blocks_when_tms_ltp_quote_missing(self, _mock_testing, mock_details, mock_get_tms):
        mock_details.return_value = ScriptDetails(available=True, rsi_14=50.0)
        tms_instance = MagicMock()
        tms_instance.broker_no = "58"
        tms_instance.get_security_id = AsyncMock(return_value={"id": 1})
        tms_instance.get_stock_details_async = AsyncMock(return_value={"ltp": 0})
        mock_get_tms.return_value = tms_instance

        ltp_query = (
            'STRATEGY_VERSION 1\nSIDE BUY\nRULE "LTP" FOR SYMBOL "CZBIL" {\n'
            "WHEN ltp <= 200\nORDER QUANTITY 10\nEXECUTE ONCE\n}"
        )
        result = await run_schedule_preflight(
            query_text=ltp_query,
            compiled_plan=None,
            strategy_type="Technical Buy",
            client_id="C1",
            script_name="CZBIL",
            db=self._mock_db(),
        )
        self.assertFalse(result["ready"])
        self.assertEqual(result["status"], "missing_data")
        self.assertIn("Live TMS quote", result["message"])

    @patch("utils.tms_client_resolver.get_tms_user_for_client", new_callable=AsyncMock)
    @patch("utils.strategy_builder.schedule_preflight.get_script_details")
    async def test_blocks_universe_percentile_for_scheduled_monitoring(self, mock_details, mock_get_tms):
        mock_details.return_value = ScriptDetails(available=True, rsi_14=50.0)
        mock_get_tms.return_value = MagicMock()
        query = (
            'STRATEGY_VERSION 1\nSIDE BUY\nRULE "Rank" FOR SYMBOL "CZBIL" {\n'
            "WHEN UNIVERSE_PERCENTILE(field=volume, operator=gte, threshold=80)\n"
            "ORDER QUANTITY 10\nEXECUTE ONCE\n}"
        )
        result = await run_schedule_preflight(
            query_text=query,
            compiled_plan=None,
            strategy_type="Technical Buy",
            client_id="C1",
            script_name="CZBIL",
            db=self._mock_db(),
        )
        self.assertFalse(result["ready"])
        self.assertEqual(result["status"], "unsupported_feature")
        self.assertIn("not supported", result["message"].lower())

    @patch("utils.tms_client_resolver.get_tms_user_for_client", new_callable=AsyncMock)
    @patch("utils.strategy_builder.schedule_preflight.get_script_details")
    async def test_blocks_when_scheduled_symbol_not_in_query(self, mock_details, mock_get_tms):
        mock_details.return_value = ScriptDetails(available=True, rsi_14=50.0)
        tms_instance = MagicMock()
        tms_instance.broker_no = "58"
        tms_instance.get_security_id = AsyncMock(return_value={"id": 1})
        tms_instance.get_stock_details_async = AsyncMock(return_value={"ltp": 200})
        mock_get_tms.return_value = tms_instance
        query = (
            'STRATEGY_VERSION 1\nSIDE BUY\nRULE "NABIL" FOR SYMBOL "NABIL" {\n'
            "WHEN technical_rsi_14 < 70\nORDER QUANTITY 10\nEXECUTE ONCE\n}"
        )
        result = await run_schedule_preflight(
            query_text=query,
            compiled_plan=None,
            strategy_type="Technical Buy",
            client_id="C1",
            script_name="CZBIL",
            db=self._mock_db(),
        )
        self.assertFalse(result["ready"])
        self.assertEqual(result["status"], "invalid_query")
        self.assertIn("CZBIL", result["message"])

    @patch("utils.tms_client_resolver.get_tms_user_for_client", new_callable=AsyncMock)
    @patch("utils.strategy_builder.schedule_preflight.get_script_details")
    async def test_preflight_checks_only_scheduled_symbol_not_whole_basket(self, mock_details, mock_get_tms):
        mock_details.return_value = ScriptDetails(available=True, rsi_14=50.0)
        tms_instance = MagicMock()
        tms_instance.broker_no = "58"
        tms_instance.get_security_id = AsyncMock(return_value={"id": 1})
        tms_instance.get_stock_details_async = AsyncMock(return_value={"ltp": 200})
        mock_get_tms.return_value = tms_instance
        query = (
            'STRATEGY_VERSION 1\nSIDE BUY\n'
            'RULE "Basket" FOR SYMBOL IN ("CZBIL", "CBBL", "NABIL") {\n'
            "WHEN technical_rsi_14 < 70 AND ltp <= 500\n"
            "ORDER QUANTITY 10\nEXECUTE ONCE PER SYMBOL\n}"
        )
        result = await run_schedule_preflight(
            query_text=query,
            compiled_plan=None,
            strategy_type="Technical Buy",
            client_id="C1",
            script_name="CZBIL",
            db=self._mock_db(),
        )
        self.assertTrue(result["ready"], result.get("message"))
        mock_details.assert_called_once_with("CZBIL", force_refresh=False)
        tms_instance.get_security_id.assert_called_once_with("CZBIL")

    @patch("utils.tms_client_resolver.get_tms_user_for_client", new_callable=AsyncMock)
    @patch("utils.strategy_builder.schedule_preflight.get_script_details")
    async def test_derived_stat_field_not_listed_as_nepse_alpha(self, mock_details, mock_get_tms):
        mock_details.return_value = ScriptDetails(
            available=False,
            fetch_error="timeout",
            fifty_two_week_high=500.0,
            fifty_two_week_low=300.0,
            reference_ltp=400.0,
        )
        tms_instance = MagicMock()
        tms_instance.broker_no = "58"
        tms_instance.get_security_id = AsyncMock(return_value={"id": 1})
        tms_instance.get_stock_details_async = AsyncMock(return_value={"ltp": 400})
        mock_get_tms.return_value = tms_instance
        query = (
            'STRATEGY_VERSION 1\nSIDE BUY\nRULE "52W" FOR SYMBOL "NABIL" {\n'
            "WHEN position_in_52_week_range_percent < 30\n"
            "ORDER QUANTITY 10\nEXECUTE ONCE\n}"
        )
        result = await run_schedule_preflight(
            query_text=query,
            compiled_plan=None,
            strategy_type="Technical Buy",
            client_id="C1",
            script_name="NABIL",
            db=self._mock_db(),
        )
        self.assertTrue(result["ready"], result.get("message"))
        nepse_messages = " ".join(item["message"] for item in result.get("errors", []))
        self.assertNotIn("position_in_52_week_range_percent", nepse_messages)
        self.assertNotIn("Nepse Alpha fields: position_in_52_week_range_percent", nepse_messages)

    @patch("utils.tms_client_resolver.get_tms_user_for_client", new_callable=AsyncMock)
    @patch("utils.strategy_builder.schedule_preflight.get_script_details")
    async def test_chcl_52_week_basket_schedules_without_warning_when_data_exists(self, mock_details, mock_get_tms):
        mock_details.return_value = ScriptDetails(
            available=True,
            rsi_14=45.0,
            fifty_two_week_high=500.0,
            fifty_two_week_low=300.0,
            reference_ltp=330.0,
        )
        tms_instance = MagicMock()
        tms_instance.broker_no = "58"
        tms_instance.get_security_id = AsyncMock(return_value={"id": 1})
        tms_instance.get_stock_details_async = AsyncMock(return_value={"ltp": 330})
        mock_get_tms.return_value = tms_instance

        result = await run_schedule_preflight(
            query_text=BLUE_CHIP_52W_QUERY,
            compiled_plan=None,
            strategy_type="Technical Buy",
            client_id="C1",
            script_name="CHCL",
            db=self._mock_db(),
        )

        self.assertTrue(result["ready"], result.get("message"))
        self.assertEqual(result["status"], "ready")
        warning_codes = {item["code"] for item in result.get("warnings", [])}
        self.assertNotIn("DERIVED_52WEEK_FIELD_MISSING", warning_codes)
        self.assertNotIn("NEPSE_ALPHA_52WEEK_MISSING", warning_codes)
        mock_details.assert_any_call("CHCL", force_refresh=False)
        tms_instance.get_security_id.assert_called_once_with("CHCL")

    @patch("utils.tms_client_resolver.get_tms_user_for_client", new_callable=AsyncMock)
    @patch("utils.strategy_builder.schedule_preflight.get_script_details")
    async def test_missing_52_week_prereq_blocks_schedule(self, mock_details, mock_get_tms):
        mock_details.return_value = ScriptDetails(
            available=True,
            rsi_14=45.0,
            fifty_two_week_high=None,
            fifty_two_week_low=None,
            reference_ltp=330.0,
        )
        tms_instance = MagicMock()
        tms_instance.broker_no = "58"
        tms_instance.get_security_id = AsyncMock(return_value={"id": 1})
        tms_instance.get_stock_details_async = AsyncMock(return_value={"ltp": 330})
        mock_get_tms.return_value = tms_instance

        result = await run_schedule_preflight(
            query_text=BLUE_CHIP_52W_QUERY,
            compiled_plan=None,
            strategy_type="Technical Buy",
            client_id="C1",
            script_name="CHCL",
            db=self._mock_db(),
        )

        self.assertFalse(result["ready"], result.get("message"))
        error_codes = {item["code"] for item in result.get("errors", [])}
        self.assertIn("NEPSE_ALPHA_52WEEK_MISSING", error_codes)


if __name__ == "__main__":
    unittest.main()
