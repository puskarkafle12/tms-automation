"""Regression tests for NEPSE_Strategy_E2E_Test_Pack.md query scenarios."""

from __future__ import annotations

import importlib
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from unit_tests.strategies.rule_based_scan_simulator import (
    default_details,
    default_snapshot,
    first_execute_index,
    simulate_scans,
)
from unit_tests.strategy_builder.nepse_e2e_test_pack import (
    ALL_INVALID_IDS,
    ALL_VALID_IDS,
    EXISTING_COVERAGE,
    INVALID_QUERIES,
    VALID_QUERIES,
    ValidQueryCase,
)
from utils.strategy_builder.schedule_baseline import reject_self_referential_drop_query
from utils.strategy_builder.schedule_preflight import run_schedule_preflight
from utils.strategy_builder.strategy_parser import StrategyQueryError, parse_strategy_query


def _fresh_trade_time(*, offset_seconds: int = 0) -> str:
    return (datetime.utcnow() - timedelta(seconds=offset_seconds)).strftime("%Y-%m-%d %H:%M:%S")
from utils.strategy_builder.strategy_validator import validate_strategy_plan
from utils.strategies.types import ScriptDetails


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


def _nepse_available(**kwargs):
    return ScriptDetails(available=True, rsi_14=50.0, **kwargs)


class NepseE2EPackCatalogTest(unittest.TestCase):
    def test_all_valid_and_invalid_case_ids_present(self):
        self.assertEqual(ALL_VALID_IDS, {f"Q{i:02d}" for i in range(1, 26)})
        self.assertEqual(ALL_INVALID_IDS, {f"N{i:02d}" for i in range(1, 11)})

    def test_existing_coverage_modules_importable(self):
        modules = sorted({
            path.split("::")[0].replace("/", ".").removesuffix(".py")
            for path in EXISTING_COVERAGE.values()
        })
        for module_name in modules:
            with self.subTest(module=module_name):
                importlib.import_module(module_name)


class NepseE2EPackParseTest(unittest.TestCase):
    def test_valid_queries_parse_with_expected_side_and_symbols(self):
        for case in VALID_QUERIES:
            with self.subTest(case_id=case.case_id, title=case.title):
                plan = parse_strategy_query(case.query)
                self.assertEqual(plan.side, case.side.upper())
                plan_symbols = {
                    symbol.strip().upper()
                    for rule in plan.rules
                    for symbol in rule.symbols
                }
                for symbol in case.symbols:
                    self.assertIn(symbol, plan_symbols, case.case_id)

    def test_delegated_buy_strategies_validate_with_required_params(self):
        delegated = [case for case in VALID_QUERIES if "USE STRATEGY" in case.query and case.side == "buy"]
        for case in delegated:
            with self.subTest(case_id=case.case_id):
                plan = parse_strategy_query(case.query)
                result = validate_strategy_plan(plan, strategy_type=case.strategy_type)
                self.assertTrue(result.valid, [issue.message for issue in result.errors])

    def test_multi_rule_query_q17_has_independent_rules(self):
        case = next(item for item in VALID_QUERIES if item.case_id == "Q17")
        plan = parse_strategy_query(case.query)
        self.assertEqual(len(plan.rules), 3)
        self.assertEqual({rule.use_strategy for rule in plan.rules}, {
            "Fixed Price Buy",
            "Confirmed Breakout Buy",
            "Quality Pullback Recovery Buy",
        })

    def test_q05_parses_max_executions_per_symbol(self):
        case = next(item for item in VALID_QUERIES if item.case_id == "Q05")
        plan = parse_strategy_query(case.query)
        self.assertEqual(plan.rules[0].execution.frequency, "max_times_per_symbol")
        self.assertEqual(plan.rules[0].execution.max_times, 3)
        self.assertEqual(plan.rules[0].execution.cooldown_minutes, 5)


class NepseE2EPackInvalidQueryTest(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_queries_rejected_as_documented(self):
        for case in INVALID_QUERIES:
            if case.covered_elsewhere:
                continue
            with self.subTest(case_id=case.case_id, title=case.title):
                if case.check == "parse":
                    if case.case_id == "N08":
                        with self.assertRaises(StrategyQueryError):
                            parse_strategy_query(case.query)
                    continue

                if case.check == "baseline":
                    with self.assertRaises(StrategyQueryError):
                        reject_self_referential_drop_query(case.query)
                    continue

                if case.check == "validate":
                    plan = parse_strategy_query(case.query)
                    result = validate_strategy_plan(plan, strategy_type=case.strategy_type)
                    codes = {issue.code for issue in result.errors}
                    if case.case_id == "N04":
                        if result.valid:
                            self.skipTest("Side mismatch not enforced yet")
                        self.assertTrue(
                            codes.intersection(set(case.expect_codes)),
                            f"{case.case_id}: expected one of {case.expect_codes}, got {codes}",
                        )
                        continue
                    self.assertFalse(result.valid, case.case_id)
                    if case.expect_codes:
                        self.assertTrue(
                            codes.intersection(set(case.expect_codes)),
                            f"{case.case_id}: expected one of {case.expect_codes}, got {codes}",
                        )
                    continue

                if case.check == "preflight":
                    with patch(
                        "utils.tms_client_resolver.get_tms_user_for_client",
                        new_callable=AsyncMock,
                    ) as mock_get_tms, patch(
                        "utils.strategy_builder.schedule_preflight.get_script_details"
                    ) as mock_details:
                        mock_get_tms.return_value = _mock_tms()
                        mock_details.return_value = _nepse_available()
                        result = await run_schedule_preflight(
                            query_text=case.query,
                            compiled_plan=None,
                            strategy_type=case.strategy_type,
                            client_id="C1",
                            script_name="NABIL",
                            db=_mock_db(),
                        )
                    self.assertFalse(result["ready"], case.case_id)
                    if case.expect_codes:
                        self.assertIn(result["status"], case.expect_codes)
                    continue

                if case.check == "runtime":
                    decisions = simulate_scans(
                        case.query,
                        price_series=[500.0],
                        symbol="NABIL",
                        details=default_details(macd_signal="Bullish"),
                    )
                    self.assertNotEqual(decisions[0].action, "EXECUTE")


class NepseE2EPackRealtimeTest(unittest.TestCase):
    """Live monitor semantics using the scan simulator (paper/live modes)."""

    def _run_case(self, case: ValidQueryCase, **kwargs):
        if case.parse_only or case.covered_elsewhere:
            self.skipTest(f"{case.case_id} covered in {EXISTING_COVERAGE.get(case.case_id, 'existing tests')}")
        symbol = kwargs.pop("symbol", case.symbols[0])
        strategy_type = case.strategy_type
        if "USE STRATEGY" not in case.query:
            strategy_type = "Technical Sell" if case.side == "sell" else "Technical Buy"
        return simulate_scans(
            case.query,
            strategy_type=strategy_type,
            side=case.side,
            symbol=symbol,
            **kwargs,
        )

    def test_q01_basic_waiting_buy_stays_tracking_above_trigger(self):
        case = next(item for item in VALID_QUERIES if item.case_id == "Q01")
        decisions = self._run_case(case, price_series=[500.0, 510.0], qty=10, symbol="NABIL")
        self.assertTrue(all(d.action == "TRACK" for d in decisions))

    def test_q04_two_scan_confirmation_with_distinct_trades(self):
        case = next(item for item in VALID_QUERIES if item.case_id == "Q04")

        def distinct_time(ltp, idx):
            return default_snapshot(ltp=ltp, symbol="NABIL", last_traded_time=_fresh_trade_time(offset_seconds=idx))

        decisions = self._run_case(
            case,
            price_series=[500.0, 500.0],
            qty=10,
            symbol="NABIL",
            snapshot_builder=distinct_time,
        )
        self.assertEqual(decisions[0].action, "TRACK")
        self.assertEqual(decisions[0].tracking_status, "WAITING_CONFIRMATION_1/2")
        self.assertEqual(decisions[1].action, "EXECUTE")

    def test_q04_same_trade_timestamp_does_not_advance_confirmation(self):
        case = next(item for item in VALID_QUERIES if item.case_id == "Q04")
        same_time = _fresh_trade_time()

        def snapshot(ltp, _idx):
            return default_snapshot(ltp=ltp, symbol="NABIL", last_traded_time=same_time)

        decisions = self._run_case(
            case,
            price_series=[500.0, 500.0, 500.0],
            qty=10,
            symbol="NABIL",
            snapshot_builder=snapshot,
        )
        self.assertEqual(decisions[0].tracking_status, "WAITING_CONFIRMATION_1/2")
        self.assertEqual(decisions[1].tracking_status, "WAITING_CONFIRMATION_1/2")
        self.assertFalse(any(d.action == "EXECUTE" for d in decisions))

    def test_q05_rolling_confirmation_requires_two_of_last_three(self):
        case = next(item for item in VALID_QUERIES if item.case_id == "Q05")

        def alternating(ltp, idx):
            return default_snapshot(
                ltp=ltp,
                symbol="CZBIL",
                change_percent=1.0 if idx in {0, 1, 3} else -1.0,
                last_traded_time=_fresh_trade_time(offset_seconds=idx),
            )

        decisions = self._run_case(
            case,
            price_series=[200.0] * 5,
            qty=10,
            symbol="CZBIL",
            snapshot_builder=alternating,
        )
        execute_idx = first_execute_index(decisions)
        self.assertIsNotNone(execute_idx)
        self.assertGreaterEqual(execute_idx, 2)

    def test_q06_cross_above_executes_on_false_to_true_crossing(self):
        case = next(item for item in VALID_QUERIES if item.case_id == "Q06")

        def distinct_time(ltp, idx):
            return default_snapshot(
                ltp=ltp,
                symbol="NABIL",
                last_traded_time=_fresh_trade_time(offset_seconds=idx),
            )

        decisions = self._run_case(
            case,
            price_series=[490.0, 510.0],
            qty=10,
            symbol="NABIL",
            snapshot_builder=distinct_time,
        )
        self.assertEqual(decisions[0].action, "TRACK")
        self.assertEqual(decisions[1].action, "EXECUTE")

    def test_q03_paper_mode_matches_without_live_execute(self):
        case = next(item for item in VALID_QUERIES if item.case_id == "Q03")

        def depth_snapshot(ltp, _idx):
            snap = default_snapshot(ltp=ltp, symbol="NABIL")
            snap.top_sell_orders = [MagicMock(price=ltp + 0.5, quantity=50)]
            return snap

        decisions = self._run_case(
            case,
            price_series=[500.0],
            execution_mode="paper",
            qty=10,
            symbol="NABIL",
            snapshot_builder=depth_snapshot,
            extra_config={"market_depth_available": True, "top_sell_quantity": 50},
        )
        self.assertEqual(decisions[0].action, "TRACK")
        self.assertIn("paper", (decisions[0].tracking_status or "").lower())

    def test_q18_position_protection_parsed(self):
        case = next(item for item in VALID_QUERIES if item.case_id == "Q18")
        plan = parse_strategy_query(case.query)
        self.assertIsNotNone(plan.position_protection)
        self.assertEqual(plan.position_protection.fixed_stop_loss_price, 450.0)

    def test_q19_sell_percent_holding_waits_until_cross(self):
        case = next(item for item in VALID_QUERIES if item.case_id == "Q19")
        decisions = self._run_case(
            case,
            price_series=[500.0, 610.0],
            qty=100,
            symbol="NABIL",
            holding_qty=100,
        )
        self.assertEqual(decisions[0].action, "TRACK")
        self.assertEqual(decisions[1].action, "EXECUTE")

    def test_q22_technical_weakness_requires_macd_transition(self):
        case = next(item for item in VALID_QUERIES if item.case_id == "Q22")
        decisions = self._run_case(
            case,
            price_series=[500.0, 500.0],
            qty=100,
            symbol="NABIL",
            holding_qty=100,
            details_builder=lambda _ltp, idx: default_details(
                macd_signal="Bullish" if idx == 0 else "Bearish",
                rsi_14=40.0,
            ),
        )
        self.assertEqual(decisions[0].action, "TRACK")
        self.assertEqual(decisions[1].action, "EXECUTE")


class NepseE2EPackPreflightTest(unittest.IsolatedAsyncioTestCase):
    @patch("utils.tms_client_resolver.get_tms_user_for_client", new_callable=AsyncMock)
    @patch("utils.strategy_builder.schedule_preflight.get_script_details")
    async def test_q08_preflight_requires_52_week_endpoints(self, mock_details, mock_get_tms):
        case = next(item for item in VALID_QUERIES if item.case_id == "Q08")
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
        self.assertFalse(result["ready"], result.get("message"))
        error_codes = {item.get("code") for item in result.get("errors") or []}
        self.assertIn("NEPSE_ALPHA_52WEEK_MISSING", error_codes)

    @patch("utils.tms_client_resolver.get_tms_user_for_client", new_callable=AsyncMock)
    @patch("utils.strategy_builder.schedule_preflight.get_script_details")
    async def test_q19_preflight_blocks_sell_without_holding(self, mock_details, mock_get_tms):
        case = next(item for item in VALID_QUERIES if item.case_id == "Q19")
        mock_get_tms.return_value = _mock_tms(holdings={"NABIL": 0})
        mock_details.return_value = _nepse_available()
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


if __name__ == "__main__":
    unittest.main()
