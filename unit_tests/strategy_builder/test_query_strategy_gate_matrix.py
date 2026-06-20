"""Schedule gate + realtime execution matrix for rule-based strategy queries."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from unit_tests.strategies.rule_based_scan_simulator import (
    default_details,
    default_snapshot,
    first_execute_index,
    simulate_scans,
)
from unit_tests.strategy_builder.query_strategy_scenarios import (
    REALTIME_MARKET_SCENARIOS,
    SCHEDULE_BLOCK_SCENARIOS,
    SCHEDULE_PASS_SCENARIOS,
)
from utils.strategy_builder.schedule_preflight import run_schedule_preflight
from utils.strategies.types import ScriptDetails


def _mock_db(*, logged_in: bool = True, user_exists: bool = True):
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


def _mock_tms(*, ltp: float = 200.0, holdings: dict | None = None):
    tms_instance = MagicMock()
    tms_instance.broker_no = "58"
    tms_instance.get_security_id = AsyncMock(return_value={"id": 1})
    tms_instance.get_stock_details_async = AsyncMock(return_value={"ltp": ltp})
    if holdings is not None:
        tms_instance.get_user_stock_details = AsyncMock(
            return_value=[
                {"scrip": symbol, "currentBalance": qty}
                for symbol, qty in holdings.items()
            ]
        )
    return tms_instance


def _nepse_available(**kwargs):
    return ScriptDetails(available=True, rsi_14=50.0, **kwargs)


class QueryStrategyScheduleGateMatrixTest(unittest.IsolatedAsyncioTestCase):
    """Every blocked scenario must fail preflight before an order can be scheduled."""

    async def test_block_scenarios_reject_scheduling(self):
        for scenario in SCHEDULE_BLOCK_SCENARIOS:
            with self.subTest(scenario_id=scenario.scenario_id, category=scenario.category):
                early_block = scenario.expected_status in {
                    "parse_error",
                    "unsupported_feature",
                } or scenario.scenario_id in {
                    "side_mismatch_sell_query_on_buy_strategy",
                    "form_symbol_not_in_plan",
                    "unknown_function",
                }

                if early_block:
                    result = await run_schedule_preflight(
                        query_text=scenario.query,
                        compiled_plan=None,
                        strategy_type=scenario.strategy_type,
                        client_id="C1" if scenario.scenario_id != "parse_empty" else None,
                        script_name=scenario.script_name,
                        db=_mock_db(),
                        holdings=scenario.holdings,
                    )
                else:
                    with patch(
                        "utils.tms_client_resolver.get_tms_user_for_client",
                        new_callable=AsyncMock,
                    ) as mock_get_tms, patch(
                        "utils.strategy_builder.schedule_preflight.get_script_details"
                    ) as mock_details:
                        mock_get_tms.return_value = _mock_tms(holdings=scenario.holdings or {"CZBIL": 0})
                        mock_details.return_value = _nepse_available()
                        result = await run_schedule_preflight(
                            query_text=scenario.query,
                            compiled_plan=None,
                            strategy_type=scenario.strategy_type,
                            client_id="C1",
                            script_name=scenario.script_name,
                            db=_mock_db(),
                            holdings=scenario.holdings,
                        )

                self.assertEqual(
                    scenario.should_block,
                    not result["ready"],
                    f"{scenario.scenario_id}: {scenario.description}",
                )
                if scenario.should_block:
                    self.assertEqual(
                        result["status"],
                        scenario.expected_status,
                        f"{scenario.scenario_id}: got {result.get('message')}",
                    )

    @patch("utils.tms_client_resolver.get_tms_user_for_client", new_callable=AsyncMock)
    @patch("utils.strategy_builder.schedule_preflight.get_script_details")
    async def test_pass_scenarios_allow_scheduling(self, mock_details, mock_get_tms):
        mock_details.return_value = _nepse_available()
        mock_get_tms.return_value = _mock_tms(ltp=200.0)

        for scenario in SCHEDULE_PASS_SCENARIOS:
            with self.subTest(scenario_id=scenario.scenario_id):
                result = await run_schedule_preflight(
                    query_text=scenario.query,
                    compiled_plan=None,
                    strategy_type=scenario.strategy_type,
                    client_id="C1",
                    script_name=scenario.script_name,
                    db=_mock_db(),
                    holdings=scenario.holdings,
                )
                self.assertTrue(result["ready"], result.get("message"))
                self.assertEqual(result["status"], scenario.expected_status)

    @patch("utils.tms_client_resolver.get_tms_user_for_client", new_callable=AsyncMock)
    @patch("utils.strategy_builder.schedule_preflight.get_script_details")
    async def test_nepse_alpha_down_blocks_rsi_query(self, mock_details, mock_get_tms):
        mock_details.return_value = ScriptDetails(available=False, rsi_14=None)
        mock_get_tms.return_value = _mock_tms()

        scenario = SCHEDULE_PASS_SCENARIOS[0]  # rsi_buy_ready
        result = await run_schedule_preflight(
            query_text=scenario.query,
            compiled_plan=None,
            strategy_type=scenario.strategy_type,
            client_id="C1",
            script_name=scenario.script_name,
            db=_mock_db(),
        )
        self.assertFalse(result["ready"])
        self.assertEqual(result["status"], "missing_data")
        self.assertIn("Nepse Alpha", result["message"])

    @patch("utils.strategy_builder.schedule_preflight.is_testing", return_value=False)
    @patch("utils.tms_client_resolver.get_tms_user_for_client", new_callable=AsyncMock)
    @patch("utils.strategy_builder.schedule_preflight.get_script_details")
    async def test_tms_quote_missing_blocks_ltp_query(self, mock_details, mock_get_tms, _mock_testing):
        mock_details.return_value = _nepse_available()
        tms = _mock_tms()
        tms.get_stock_details_async = AsyncMock(return_value={"ltp": 0})
        mock_get_tms.return_value = tms

        scenario = SCHEDULE_PASS_SCENARIOS[1]  # ltp_only_buy
        result = await run_schedule_preflight(
            query_text=scenario.query,
            compiled_plan=None,
            strategy_type=scenario.strategy_type,
            client_id="C1",
            script_name=scenario.script_name,
            db=_mock_db(),
        )
        self.assertFalse(result["ready"])
        self.assertEqual(result["status"], "missing_data")
        self.assertIn("Live TMS quote", result["message"])

    @patch("utils.tms_client_resolver.get_tms_user_for_client", new_callable=AsyncMock)
    @patch("utils.strategy_builder.schedule_preflight.get_script_details")
    async def test_client_not_logged_in_blocks_monitoring(self, mock_details, mock_get_tms):
        mock_details.return_value = _nepse_available()
        mock_get_tms.return_value = _mock_tms()

        result = await run_schedule_preflight(
            query_text=SCHEDULE_PASS_SCENARIOS[0].query,
            compiled_plan=None,
            strategy_type="Technical Buy",
            client_id="C1",
            script_name="CZBIL",
            db=_mock_db(logged_in=False),
        )
        self.assertFalse(result["ready"])
        self.assertEqual(result["status"], "monitor_unavailable")


class QueryStrategyRealtimeMatrixTest(unittest.TestCase):
    """Market scan scenarios after a query passed validation gates."""

    def test_realtime_market_scenarios(self):
        for scenario in REALTIME_MARKET_SCENARIOS:
            with self.subTest(scenario_id=scenario.scenario_id, category=scenario.category):
                kwargs = {
                    "execution_mode": scenario.execution_mode,
                    "strategy_type": scenario.strategy_type,
                    "side": scenario.side,
                    "symbol": scenario.symbol,
                    "qty": scenario.qty,
                    "holding_qty": scenario.holding_qty,
                }
                if scenario.scenario_id == "rsi_not_met_keeps_tracking":
                    kwargs["details"] = default_details(rsi_14=80.0)
                elif scenario.scenario_id == "on_cross_waits_for_transition":
                    kwargs["details_builder"] = lambda _ltp, idx: default_details(
                        rsi_14=80.0 if idx == 0 else 65.0,
                    )
                elif scenario.scenario_id == "require_macd_bullish":
                    kwargs["details"] = default_details(rsi_14=50.0, macd_signal="Bullish")

                decisions = simulate_scans(scenario.query, price_series=scenario.price_series, **kwargs)

                if scenario.expected_action == "EXECUTE":
                    idx = scenario.execute_at_scan
                    if idx is None:
                        idx = first_execute_index(decisions)
                    self.assertIsNotNone(idx, scenario.description)
                    assert idx is not None
                    self.assertEqual(decisions[idx].action, "EXECUTE", scenario.description)
                    if scenario.expected_qty is not None:
                        self.assertEqual(decisions[idx].qty, scenario.expected_qty)
                    if scenario.scenario_id == "execute_once_blocks_repeat":
                        later = [d.action for d in decisions[idx + 1 :]]
                        self.assertFalse(any(action == "EXECUTE" for action in later))
                elif scenario.expected_action == "TRACK":
                    self.assertTrue(
                        all(d.action in {"TRACK", "NO_TRADE", "WATCH"} for d in decisions),
                        [d.action for d in decisions],
                    )
                elif scenario.expected_action == "SKIP":
                    self.assertEqual(decisions[0].action, "SKIP")

    def test_blocked_schedule_scenarios_never_reach_execute_in_monitor(self):
        """Queries blocked at schedule time should not silently EXECUTE on first scan."""
        blocked_runtime_checks = [
            s for s in SCHEDULE_BLOCK_SCENARIOS
            if s.scenario_id in {
                "unsupported_adx",
                "universe_percentile_schedule",
                "form_symbol_not_in_plan",
            }
        ]
        for scenario in blocked_runtime_checks:
            with self.subTest(scenario_id=scenario.scenario_id):
                try:
                    decisions = simulate_scans(
                        scenario.query,
                        price_series=[200.0],
                        execution_mode="live",
                        strategy_type=scenario.strategy_type,
                        side=scenario.side,
                        symbol=scenario.script_name,
                    )
                except Exception:
                    continue
                self.assertFalse(
                    any(d.action == "EXECUTE" for d in decisions),
                    f"{scenario.scenario_id} should not execute",
                )


if __name__ == "__main__":
    unittest.main()
