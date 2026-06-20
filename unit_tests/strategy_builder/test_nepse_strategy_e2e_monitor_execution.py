"""M/E/P scenarios from NEPSE_Strategy_E2E_Test_Pack.md (monitoring, execution, preflight)."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from unit_tests.strategies.rule_based_scan_simulator import (
    default_snapshot,
    first_execute_index,
    simulate_scans,
)
from unit_tests.strategy_builder.nepse_e2e_test_pack import EXISTING_COVERAGE, query_by_id
from utils.monitor_order import _try_claim_order_for_execution
from utils.strategy_builder.history_service import (
    TargetHistory,
    deserialize_target_history,
    serialize_target_history,
)
from utils.strategy_builder.reference_store import ReferenceRow, ReferenceStore
from utils.strategy_builder.rule_evaluator import evaluate_rule
from utils.strategy_builder.schedule_preflight import run_schedule_preflight
from utils.strategy_builder.strategy_models import RuleBlock
from utils.strategy_builder.strategy_parser import parse_strategy_query
from utils.strategies.handlers import evaluate_profit_ladder_sell
from utils.strategies.risk_guard import can_place_order
from utils.strategies.types import AccountState, MarketSnapshot, OrderContext, ScannerMemory, StrategyConfig, ScriptDetails


def _mock_db(*, logged_in: bool = True):
    db = MagicMock()
    session_row = MagicMock() if logged_in else None
    user_row = MagicMock()

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


def _mock_tms(*, ltp: float = 500.0, holdings: dict | None = None):
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


class NepseE2EPreflightMatrixTest(unittest.IsolatedAsyncioTestCase):
    """P01–P10 preflight failure matrix."""

    async def test_p01_blocks_without_client(self):
        if "P01" in EXISTING_COVERAGE:
            self.skipTest("covered elsewhere")
        case = query_by_id("Q01")
        result = await run_schedule_preflight(
            query_text=case.query,
            compiled_plan=None,
            strategy_type="Custom Query Buy",
            client_id=None,
            script_name="NABIL",
            db=_mock_db(),
        )
        self.assertFalse(result["ready"])
        self.assertEqual(result["status"], "monitor_unavailable")

    @patch("utils.tms_client_resolver.get_tms_user_for_client", new_callable=AsyncMock)
    @patch("utils.strategy_builder.schedule_preflight.get_script_details")
    async def test_p02_blocks_when_client_not_logged_in(self, mock_details, mock_get_tms):
        if "P02" in EXISTING_COVERAGE:
            self.skipTest("covered elsewhere")
        mock_get_tms.return_value = _mock_tms()
        mock_details.return_value = ScriptDetails(available=True, rsi_14=50.0)
        case = query_by_id("Q01")
        result = await run_schedule_preflight(
            query_text=case.query,
            compiled_plan=None,
            strategy_type="Custom Query Buy",
            client_id="C1",
            script_name="NABIL",
            db=_mock_db(logged_in=False),
        )
        self.assertFalse(result["ready"])
        self.assertEqual(result["status"], "monitor_unavailable")

    @patch("utils.tms_client_resolver.get_tms_user_for_client", new_callable=AsyncMock)
    @patch("utils.strategy_builder.schedule_preflight.get_script_details")
    async def test_p03_bulk_symbol_missing_live_quote(self, mock_details, mock_get_tms):
        case = query_by_id("Q02")
        tms = _mock_tms(ltp=0)
        mock_get_tms.return_value = tms
        mock_details.return_value = ScriptDetails(available=True, rsi_14=50.0)
        result = await run_schedule_preflight(
            query_text=case.query,
            compiled_plan=None,
            strategy_type="Custom Query Buy",
            client_id="C1",
            script_name="NABIL",
            db=_mock_db(),
        )
        self.assertFalse(result["ready"])
        self.assertIn(result["status"], {"missing_data", "baseline_unavailable"})

    @patch("utils.tms_client_resolver.get_tms_user_for_client", new_callable=AsyncMock)
    @patch("utils.strategy_builder.schedule_preflight.get_script_details")
    async def test_p04_bulk_symbol_missing_rsi(self, mock_details, mock_get_tms):
        case = query_by_id("Q02")
        mock_get_tms.return_value = _mock_tms(ltp=500.0)

        def details_for_symbol(symbol):
            if symbol == "EBL":
                return ScriptDetails(available=False, rsi_14=None)
            return ScriptDetails(available=True, rsi_14=50.0)

        mock_details.side_effect = lambda symbol, **kwargs: details_for_symbol(symbol)
        result = await run_schedule_preflight(
            query_text=case.query,
            compiled_plan=None,
            strategy_type="Custom Query Buy",
            client_id="C1",
            script_name="EBL",
            db=_mock_db(),
        )
        self.assertFalse(result["ready"])
        self.assertEqual(result["status"], "missing_data")

    @patch("utils.tms_client_resolver.get_tms_user_for_client", new_callable=AsyncMock)
    @patch("utils.strategy_builder.schedule_preflight.get_script_details")
    async def test_p08_sell_without_holding_rejected(self, mock_details, mock_get_tms):
        if "P08" in EXISTING_COVERAGE:
            self.skipTest("covered elsewhere")
        case = query_by_id("Q19")
        mock_get_tms.return_value = _mock_tms(holdings={"NABIL": 0})
        mock_details.return_value = ScriptDetails(available=True, rsi_14=50.0)
        result = await run_schedule_preflight(
            query_text=case.query,
            compiled_plan=None,
            strategy_type=case.strategy_type,
            client_id="C1",
            script_name="NABIL",
            db=_mock_db(),
            holdings={"NABIL": 0},
        )
        self.assertFalse(result["ready"])

    @patch("utils.tms_client_resolver.get_tms_user_for_client", new_callable=AsyncMock)
    @patch("utils.strategy_builder.schedule_preflight.get_script_details")
    async def test_p05_blocks_when_52_week_high_missing(self, mock_details, mock_get_tms):
        case = query_by_id("Q08")
        mock_get_tms.return_value = _mock_tms(ltp=500.0)
        mock_details.return_value = ScriptDetails(
            available=True,
            rsi_14=40.0,
            fifty_two_week_high=None,
            fifty_two_week_low=100.0,
        )
        result = await run_schedule_preflight(
            query_text=case.query,
            compiled_plan=None,
            strategy_type="Custom Query Buy",
            client_id="C1",
            script_name="NABIL",
            db=_mock_db(),
        )
        self.assertFalse(result["ready"])
        error_codes = {item.get("code") for item in result.get("errors") or []}
        self.assertIn("NEPSE_ALPHA_52WEEK_MISSING", error_codes)

    @patch("utils.tms_client_resolver.get_tms_user_for_client", new_callable=AsyncMock)
    @patch("utils.strategy_builder.schedule_preflight.get_script_details")
    async def test_p06_blocks_when_52_week_low_missing(self, mock_details, mock_get_tms):
        case = query_by_id("Q08")
        mock_get_tms.return_value = _mock_tms(ltp=500.0)
        mock_details.return_value = ScriptDetails(
            available=True,
            rsi_14=40.0,
            fifty_two_week_high=600.0,
            fifty_two_week_low=None,
        )
        result = await run_schedule_preflight(
            query_text=case.query,
            compiled_plan=None,
            strategy_type="Custom Query Buy",
            client_id="C1",
            script_name="NABIL",
            db=_mock_db(),
        )
        self.assertFalse(result["ready"])
        error_codes = {item.get("code") for item in result.get("errors") or []}
        self.assertIn("NEPSE_ALPHA_52WEEK_MISSING", error_codes)

    @patch("utils.tms_client_resolver.get_tms_user_for_client", new_callable=AsyncMock)
    @patch("utils.strategy_builder.schedule_preflight.get_script_details")
    async def test_p07_blocks_when_market_depth_unavailable(self, mock_details, mock_get_tms):
        if "Q09" in EXISTING_COVERAGE:
            self.skipTest("covered elsewhere")
        case = query_by_id("Q09")
        tms = _mock_tms(ltp=500.0)
        tms.get_stock_details_async = AsyncMock(return_value={"ltp": 500.0})
        mock_get_tms.return_value = tms
        mock_details.return_value = ScriptDetails(available=True, rsi_14=50.0)
        result = await run_schedule_preflight(
            query_text=case.query,
            compiled_plan=None,
            strategy_type="Custom Query Buy",
            client_id="C1",
            script_name="NABIL",
            db=_mock_db(),
        )
        self.assertFalse(result["ready"])
        error_codes = {item.get("code") for item in result.get("errors") or []}
        self.assertIn("MARKET_DEPTH_UNAVAILABLE", error_codes)


class NepseE2EMonitoringMatrixTest(unittest.TestCase):
    """M01–M10 monitoring and restart semantics."""

    def test_m01_reference_stays_fixed_while_ltp_moves(self):
        if "M01" in EXISTING_COVERAGE:
            self.skipTest("covered elsewhere")
        case = query_by_id("Q02")
        plan = parse_strategy_query(case.query)
        rule = RuleBlock.model_validate(plan.rules[0].model_dump())
        store = ReferenceStore.from_rows([
            ReferenceRow(rule_name=rule.name, symbol="NABIL", field_key="ltp", field_type="decimal", numeric_value=500.0),
        ])
        history = TargetHistory()
        matched = evaluate_rule(rule, "NABIL", {"ltp": 480.0}, history, reference_store=store)
        self.assertTrue(matched.matched)
        not_matched = evaluate_rule(rule, "NABIL", {"ltp": 510.0}, history, reference_store=store)
        self.assertFalse(not_matched.matched)

    def test_m02_confirmation_counter_survives_restart(self):
        history = TargetHistory(confirmation_streak=1, last_confirmation_trade_timestamp="2026-06-20 10:00:00")
        restored = deserialize_target_history(serialize_target_history(history))
        self.assertEqual(restored.confirmation_streak, 1)
        self.assertEqual(restored.last_confirmation_trade_timestamp, "2026-06-20 10:00:00")

    def test_m03_same_last_traded_at_does_not_advance_confirmation(self):
        case = query_by_id("Q04")
        same_time = (datetime.utcnow() - timedelta(seconds=5)).strftime("%Y-%m-%d %H:%M:%S")

        def snapshot(ltp, _idx):
            return default_snapshot(ltp=ltp, symbol="NABIL", last_traded_time=same_time)

        decisions = simulate_scans(
            case.query,
            price_series=[500.0, 500.0, 500.0],
            symbol="NABIL",
            strategy_type="Technical Buy",
            qty=10,
            snapshot_builder=snapshot,
        )
        self.assertEqual(decisions[0].tracking_status, "WAITING_CONFIRMATION_1/2")
        self.assertEqual(decisions[1].tracking_status, "WAITING_CONFIRMATION_1/2")
        self.assertFalse(any(d.action == "EXECUTE" for d in decisions))

    def test_m06_position_peak_persists_across_restart(self):
        payload = serialize_target_history(
            TargetHistory(position={"highest_price_since_entry": 520.0, "entry_price": 500.0}),
        )
        restored = deserialize_target_history(payload)
        self.assertEqual(restored.position["highest_price_since_entry"], 520.0)

    def test_m07_execution_claim_is_idempotent(self):
        db = MagicMock()
        db.execute.return_value.rowcount = 1
        self.assertTrue(_try_claim_order_for_execution(db, 42))
        db.execute.return_value.rowcount = 0
        self.assertFalse(_try_claim_order_for_execution(db, 42))

    def test_m05_profit_ladder_does_not_repeat_executed_leg(self):
        ctx = OrderContext(
            strategy_type="Custom Query Sell",
            canonical_strategy="Profit Ladder Sell",
            side="sell",
            symbol="EBL",
            qty=100,
            remaining_qty=100,
            target_price=700.0,
            average_buy_price=700.0,
            executed_legs=["0"],
            partial_legs=[
                {"id": "0", "targetPrice": 720.0, "sellPercent": 50.0},
                {"id": "1", "targetPrice": 780.0, "sellPercent": 50.0},
            ],
            config=StrategyConfig(),
        )
        first_leg = evaluate_profit_ladder_sell(
            ctx,
            _snapshot(ltp=730.0, symbol="EBL"),
            ScannerMemory(),
            ScriptDetails(available=True),
        )
        self.assertNotEqual(first_leg.action, "EXECUTE")


def _snapshot(**kwargs) -> MarketSnapshot:
    defaults = dict(symbol="NABIL", ltp=500.0)
    defaults.update(kwargs)
    return MarketSnapshot(**defaults)


class NepseE2EExecutionMatrixTest(unittest.TestCase):
    """E01–E12 execution and idempotency checks."""

    def test_e01_paper_mode_q03_tracks_without_live_execute(self):
        case = query_by_id("Q03")
        decisions = simulate_scans(
            case.query,
            price_series=[500.0, 500.0, 500.0],
            symbol="NABIL",
            strategy_type="Technical Buy",
            execution_mode="paper",
            qty=10,
        )
        self.assertFalse(any(d.action == "EXECUTE" for d in decisions))

    def test_e09_insufficient_cash_blocks_buy(self):
        ctx = OrderContext(
            strategy_type="Technical Buy",
            canonical_strategy="Technical Buy",
            side="buy",
            symbol="NABIL",
            qty=100,
            remaining_qty=100,
            target_price=0,
            config=StrategyConfig(),
        )
        snapshot = MarketSnapshot(symbol="NABIL", ltp=500.0)
        account = AccountState(available_balance=1000.0)
        decision = can_place_order(
            context=ctx,
            snapshot=snapshot,
            account=account,
            price=500.0,
            qty=100,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "INSUFFICIENT_BALANCE")

    def test_e10_execute_once_blocks_second_match(self):
        if "E10" in EXISTING_COVERAGE:
            self.skipTest("covered elsewhere")
        case = query_by_id("Q01")
        decisions = simulate_scans(
            case.query,
            price_series=[0.5, 0.5, 0.5],
            symbol="NABIL",
            strategy_type="Technical Buy",
            qty=10,
            snapshot_builder=lambda ltp, idx: default_snapshot(
                ltp=ltp,
                symbol="NABIL",
                last_traded_time=f"2026-06-20 10:00:{idx:02d}",
            ),
        )
        execute_idx = first_execute_index(decisions)
        self.assertIsNotNone(execute_idx)
        later = [d.action for d in decisions[execute_idx + 1 :]]
        self.assertFalse(any(action == "EXECUTE" for action in later))

    def test_q05_cooldown_blocks_immediate_reentry(self):
        case = query_by_id("Q05")
        history = TargetHistory(
            execution_count=1,
            last_executed_at=datetime.now(timezone.utc).isoformat(),
        )
        target_state = {"CZBIL": serialize_target_history(history)}

        def positive_change(ltp, idx):
            return default_snapshot(
                ltp=ltp,
                symbol="CZBIL",
                change_percent=1.0,
                last_traded_time=(datetime.utcnow() - timedelta(seconds=idx)).strftime("%Y-%m-%d %H:%M:%S"),
            )

        decisions = simulate_scans(
            case.query,
            price_series=[200.0, 200.0, 200.0, 200.0, 200.0],
            symbol="CZBIL",
            strategy_type="Technical Buy",
            qty=10,
            snapshot_builder=positive_change,
            target_state=target_state,
        )
        self.assertFalse(any(d.action == "EXECUTE" for d in decisions))
        self.assertTrue(any("COOLDOWN" in (d.reason_code or "") for d in decisions))

    def test_p10_stale_quote_skips_confirmation(self):
        case = query_by_id("Q04")
        old_time = (datetime.utcnow() - timedelta(seconds=120)).strftime("%Y-%m-%d %H:%M:%S")

        def snapshot(ltp, idx):
            return default_snapshot(
                ltp=ltp,
                symbol="NABIL",
                last_traded_time=old_time,
            )

        decisions = simulate_scans(
            case.query,
            price_series=[500.0, 500.0, 500.0],
            symbol="NABIL",
            strategy_type="Technical Buy",
            qty=10,
            snapshot_builder=snapshot,
        )
        self.assertTrue(all(d.tracking_status == "STALE_DATA" for d in decisions))
        self.assertFalse(any(d.action == "EXECUTE" for d in decisions))


if __name__ == "__main__":
    unittest.main()
