"""Execution-time holding-based quantity resolution tests."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from main import _validate_sell_lot_against_holdings, _validate_strategy_order
from schemas.schemas import OrderCreateRequest
from utils.monitor_order import (
    _evaluate_strategy,
    _release_execution_claim,
    _try_claim_order_for_execution,
    submit_scheduled_order_to_tms,
)
from utils.strategy_builder.execution_quantity import resolve_execution_quantity
from utils.strategy_builder.strategy_parser import parse_strategy_query


SELL_100_PERCENT_QUERY = """STRATEGY_VERSION 1
SIDE SELL
RULE "Sell At 10 Percent Gain" FOR SYMBOL "HDL" {
    WHEN ltp >= REFERENCE(field=ltp) * 1.10
    ORDER PERCENT_OF_HOLDING 100
    CONFIRM TRUE_FOR 2 SCANS
    TRIGGER LEVEL
    MAX_SLIPPAGE_PCT 1
    EXECUTE ONCE PER SYMBOL
}
"""

SELL_50_PERCENT_QUERY = SELL_100_PERCENT_QUERY.replace("PERCENT_OF_HOLDING 100", "PERCENT_OF_HOLDING 50")

SELL_ALL_AVAILABLE_QUERY = """STRATEGY_VERSION 1
SIDE SELL
RULE "Sell All" FOR SYMBOL "HDL" {
    WHEN ltp >= 100
    ORDER ALL_AVAILABLE
    EXECUTE ONCE
}
"""

SELL_UP_TO_QUERY = """STRATEGY_VERSION 1
SIDE SELL
RULE "Sell Up To" FOR SYMBOL "HDL" {
    WHEN ltp >= 100
    ORDER SELL_UP_TO 500
    EXECUTE ONCE
}
"""

FIXED_SELL_QUERY = """STRATEGY_VERSION 1
SIDE SELL
RULE "Fixed Sell" FOR SYMBOL "HDL" {
    WHEN ltp >= 100
    ORDER QUANTITY 50
    EXECUTE ONCE
}
"""

BUY_FIXED_QUERY = """STRATEGY_VERSION 1
SIDE BUY
RULE "Buy" FOR SYMBOL "CZBIL" {
    WHEN technical_rsi_14 < 70
    ORDER QUANTITY 100
    EXECUTE ONCE
}
"""


def _nepse_details(**kwargs):
    defaults = {
        "available": True,
        "rsi_14": 50.0,
        "macd_signal": "Bullish",
        "mfi_14": 41.0,
        "stochastic_14": 25.0,
        "percent_b": 32.0,
        "roe": 21.0,
        "yoy_earnings_growth": 52.0,
        "pe": 27.0,
        "pbv": 3.0,
    }
    defaults.update(kwargs)
    return MagicMock(**defaults)


def _tms_quote(ltp: float = 200.0) -> dict:
    return {
        "ltp": ltp,
        "high": ltp + 1,
        "low": ltp - 1,
        "open": ltp,
        "volume": 1000,
        "topBuy": [{"price": ltp, "quantity": 100}],
        "topSell": [{"price": ltp + 0.1, "quantity": 100}],
    }


def _make_sell_order(
    *,
    query: str = SELL_100_PERCENT_QUERY,
    qty: int = 0,
    client_id: str = "35",
):
    compiled = parse_strategy_query(query).model_dump()
    return SimpleNamespace(
        order_id=101,
        client_id=client_id,
        script_name="HDL",
        symbol="HDL",
        strategy_type="Custom Query Sell",
        order_type="sell",
        side="sell",
        qty=qty,
        remaining_quantity=qty,
        price=0,
        status="Monitoring",
        security_details={"symbol": "HDL", "boardLot": 10, "oddLotAllowed": True},
        strategy_config={
            "compiled_plan": compiled,
            "query_text": query.strip(),
            "execution_mode": "live",
            "target_state": {},
            "uses_field_references": True,
            "field_reference_rows": [
                {
                    "rule_name": "Sell At 10 Percent Gain",
                    "symbol": "HDL",
                    "field_key": "ltp",
                    "field_type": "decimal",
                    "numeric_value": 100.0,
                    "source": "schedule",
                }
            ],
        },
        scan_price_history=[],
        scan_volume_history=[],
        stop_loss_price=None,
        stop_limit_price=None,
        book_profit_price=None,
        profit_target_price=None,
        trailing_drop_percent=3.0,
        stable_band_percent=0.2,
        minimum_wait_minutes=5,
        activation_price=None,
        protected_price=None,
        average_buy_price=None,
        partial_legs=[],
        executed_legs=[],
        target_reached=False,
        target_reached_at=None,
        highest_tracked_price=None,
        expiry_time=None,
        expiry_action=None,
        max_allowed_slippage_percent=1.0,
        emergency_execution=False,
        below_stop_loss_check_count=0,
        last_checked_ltp=None,
    )


class HoldingExecutionQuantityResolverTest(unittest.IsolatedAsyncioTestCase):
    async def test_percent_of_holding_100_uses_full_holding(self):
        tms_user = AsyncMock()
        with patch(
            "utils.strategy_builder.execution_quantity.fetch_symbol_holding_qty",
            new=AsyncMock(return_value=222),
        ):
            resolution = await resolve_execution_quantity(
                scheduled_order=SimpleNamespace(client_id="35", qty=0, security_details={"oddLotAllowed": True}),
                matched_order_action={"mode": "percent_of_holding", "value": 100},
                tms_user=tms_user,
                symbol="HDL",
                side="sell",
            )
        self.assertEqual(resolution.final_quantity, 222)
        self.assertEqual(resolution.available_holding, 222)

    async def test_holding_changes_after_scheduling(self):
        tms_user = AsyncMock()
        with patch(
            "utils.strategy_builder.execution_quantity.fetch_symbol_holding_qty",
            new=AsyncMock(return_value=180),
        ):
            resolution = await resolve_execution_quantity(
                scheduled_order=SimpleNamespace(client_id="35", qty=222, security_details={"oddLotAllowed": True}),
                matched_order_action={"mode": "percent_of_holding", "value": 100},
                tms_user=tms_user,
                symbol="HDL",
                side="sell",
            )
        self.assertEqual(resolution.final_quantity, 180)

    async def test_partial_percentage(self):
        tms_user = AsyncMock()
        with patch(
            "utils.strategy_builder.execution_quantity.fetch_symbol_holding_qty",
            new=AsyncMock(return_value=200),
        ):
            resolution = await resolve_execution_quantity(
                scheduled_order=SimpleNamespace(client_id="35", qty=0, security_details={"oddLotAllowed": True}),
                matched_order_action={"mode": "percent_of_holding", "value": 50},
                tms_user=tms_user,
                symbol="HDL",
                side="sell",
            )
        self.assertEqual(resolution.final_quantity, 100)

    async def test_all_available(self):
        tms_user = AsyncMock()
        with patch(
            "utils.strategy_builder.execution_quantity.fetch_symbol_holding_qty",
            new=AsyncMock(return_value=75),
        ):
            resolution = await resolve_execution_quantity(
                scheduled_order=SimpleNamespace(client_id="35", qty=0, security_details={"oddLotAllowed": True}),
                matched_order_action={"mode": "all_available", "value": None},
                tms_user=tms_user,
                symbol="HDL",
                side="sell",
            )
        self.assertEqual(resolution.final_quantity, 75)

    async def test_sell_up_to_when_holding_is_smaller(self):
        tms_user = AsyncMock()
        with patch(
            "utils.strategy_builder.execution_quantity.fetch_symbol_holding_qty",
            new=AsyncMock(return_value=180),
        ):
            resolution = await resolve_execution_quantity(
                scheduled_order=SimpleNamespace(client_id="35", qty=0, security_details={"oddLotAllowed": True}),
                matched_order_action={"mode": "sell_up_to", "value": 500},
                tms_user=tms_user,
                symbol="HDL",
                side="sell",
            )
        self.assertEqual(resolution.final_quantity, 180)

    async def test_sell_up_to_when_holding_is_larger(self):
        tms_user = AsyncMock()
        with patch(
            "utils.strategy_builder.execution_quantity.fetch_symbol_holding_qty",
            new=AsyncMock(return_value=800),
        ):
            resolution = await resolve_execution_quantity(
                scheduled_order=SimpleNamespace(client_id="35", qty=0, security_details={"oddLotAllowed": True}),
                matched_order_action={"mode": "sell_up_to", "value": 500},
                tms_user=tms_user,
                symbol="HDL",
                side="sell",
            )
        self.assertEqual(resolution.final_quantity, 500)

    async def test_zero_holding_blocks_execution(self):
        tms_user = AsyncMock()
        with patch(
            "utils.strategy_builder.execution_quantity.fetch_symbol_holding_qty",
            new=AsyncMock(return_value=0),
        ):
            resolution = await resolve_execution_quantity(
                scheduled_order=SimpleNamespace(client_id="35", qty=0, security_details={"oddLotAllowed": True}),
                matched_order_action={"mode": "percent_of_holding", "value": 100},
                tms_user=tms_user,
                symbol="HDL",
                side="sell",
            )
        self.assertEqual(resolution.final_quantity, 0)
        self.assertIsNotNone(resolution.error)

    async def test_holding_retrieval_error_is_retryable(self):
        tms_user = AsyncMock()
        with patch(
            "utils.strategy_builder.execution_quantity.fetch_symbol_holding_qty",
            new=AsyncMock(side_effect=RuntimeError("network down")),
        ):
            resolution = await resolve_execution_quantity(
                scheduled_order=SimpleNamespace(client_id="35", qty=0, security_details={"oddLotAllowed": True}),
                matched_order_action={"mode": "percent_of_holding", "value": 100},
                tms_user=tms_user,
                symbol="AKJCL",
                side="sell",
            )
        self.assertTrue(resolution.retryable)
        self.assertIn("AKJCL", resolution.error or "")
        self.assertIn("35", resolution.error or "")

    async def test_client_isolation(self):
        tms_user_a = AsyncMock()
        tms_user_b = AsyncMock()

        async def _holding_for(tms_user, symbol):
            if tms_user is tms_user_a:
                return 100
            return 250

        with patch(
            "utils.strategy_builder.execution_quantity.fetch_symbol_holding_qty",
            side_effect=_holding_for,
        ):
            resolution_a = await resolve_execution_quantity(
                scheduled_order=SimpleNamespace(client_id="A", qty=0, security_details={"oddLotAllowed": True}),
                matched_order_action={"mode": "all_available"},
                tms_user=tms_user_a,
                symbol="HDL",
                side="sell",
            )
            resolution_b = await resolve_execution_quantity(
                scheduled_order=SimpleNamespace(client_id="B", qty=0, security_details={"oddLotAllowed": True}),
                matched_order_action={"mode": "all_available"},
                tms_user=tms_user_b,
                symbol="HDL",
                side="sell",
            )
        self.assertEqual(resolution_a.final_quantity, 100)
        self.assertEqual(resolution_b.final_quantity, 250)


class MonitorScanHoldingFetchTest(unittest.TestCase):
    @patch("utils.strategies.normalize.get_script_details_fetch_meta")
    def test_no_holding_fetch_during_monitoring(self, mock_fetch_meta):
        mock_fetch_meta.return_value = (_nepse_details(), True)
        db_order = _make_sell_order(qty=0)
        holding_calls = {"count": 0}

        async def _track_holding(*args, **kwargs):
            holding_calls["count"] += 1
            return 222

        with patch("utils.strategy_builder.holdings_preflight.build_holdings_map", side_effect=_track_holding):
            with patch("utils.monitor_order._latest_holding_qty", side_effect=_track_holding):
                _evaluate_strategy(db_order, 105.0, _tms_quote(ltp=105.0), scan_count=1, details=_nepse_details())
                _evaluate_strategy(db_order, 111.0, _tms_quote(ltp=111.0), scan_count=2, details=_nepse_details())
                _evaluate_strategy(db_order, 112.0, _tms_quote(ltp=112.0), scan_count=3, details=_nepse_details())

        self.assertEqual(holding_calls["count"], 0)

    @patch("utils.strategies.normalize.get_script_details_fetch_meta")
    def test_execute_payload_defers_holding_quantity(self, mock_fetch_meta):
        mock_fetch_meta.return_value = (_nepse_details(), True)
        db_order = _make_sell_order(qty=222)
        first, _ = _evaluate_strategy(db_order, 111.0, _tms_quote(ltp=111.0), scan_count=1, details=_nepse_details())
        second, _ = _evaluate_strategy(db_order, 112.0, _tms_quote(ltp=112.0), scan_count=2, details=_nepse_details())
        self.assertIsNone(first)
        self.assertIsNotNone(second)
        assert second is not None
        self.assertEqual(second["action"], "execute")
        self.assertIn("order_action", second)
        self.assertEqual(second["order_action"]["mode"], "percent_of_holding")
        self.assertNotIn("qty", second)


class SubmitExecutionQuantityTest(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_immediately_before_execution(self):
        db_order = _make_sell_order(qty=0)
        tms_user = MagicMock()
        tms_user.order = AsyncMock(return_value={"status": 200})
        holding_calls = {"count": 0}

        async def _holding(*args, **kwargs):
            holding_calls["count"] += 1
            return 222

        with patch("utils.strategy_builder.execution_quantity.fetch_symbol_holding_qty", side_effect=_holding):
            with patch("utils.monitor_order._latest_holding_qty", side_effect=_holding):
                result = await submit_scheduled_order_to_tms(
                    db_order,
                    {
                        "action": "execute",
                        "price": 112.0,
                        "order_action": {"mode": "percent_of_holding", "value": 100},
                    },
                    high_price=115.0,
                    fallback_qty=0,
                    security_details=db_order.security_details,
                    order_type="sell",
                    tms_user=tms_user,
                    execution_gate={"can_execute": True},
                )

        self.assertTrue(result.submitted)
        self.assertEqual(result.execution_qty, 222)
        self.assertEqual(holding_calls["count"], 1)
        tms_user.order.assert_awaited_once_with(
            112.0,
            222,
            security=db_order.security_details,
            order_type="sell",
        )

    async def test_holding_retrieval_error_does_not_submit(self):
        db_order = _make_sell_order(qty=0)
        tms_user = MagicMock()
        tms_user.order = AsyncMock()
        with patch(
            "utils.strategy_builder.execution_quantity.fetch_symbol_holding_qty",
            new=AsyncMock(side_effect=RuntimeError("network down")),
        ):
            result = await submit_scheduled_order_to_tms(
                db_order,
                {
                    "action": "execute",
                    "price": 112.0,
                    "order_action": {"mode": "percent_of_holding", "value": 100},
                },
                high_price=115.0,
                fallback_qty=0,
                security_details=db_order.security_details,
                order_type="sell",
                tms_user=tms_user,
                execution_gate={"can_execute": True},
            )
        self.assertFalse(result.submitted)
        self.assertTrue(result.retryable)
        tms_user.order.assert_not_awaited()

    async def test_fixed_quantity_regression(self):
        db_order = _make_sell_order(query=FIXED_SELL_QUERY, qty=50)
        tms_user = MagicMock()
        tms_user.order = AsyncMock(return_value={"status": 200})
        with patch("utils.monitor_order._latest_holding_qty", new=AsyncMock(return_value=100)):
            result = await submit_scheduled_order_to_tms(
                db_order,
                {"action": "execute", "price": 112.0, "qty": 50},
                high_price=115.0,
                fallback_qty=50,
                security_details=db_order.security_details,
                order_type="sell",
                tms_user=tms_user,
                execution_gate={"can_execute": True},
            )
        self.assertTrue(result.submitted)
        tms_user.order.assert_awaited_once_with(
            112.0,
            50,
            security=db_order.security_details,
            order_type="sell",
        )


class DynamicQuantitySchedulingTest(unittest.IsolatedAsyncioTestCase):
    def _order(self, query: str, *, qty: int = 0) -> OrderCreateRequest:
        compiled = parse_strategy_query(query).model_dump()
        return OrderCreateRequest(
            client_id="C1",
            script_name="HDL",
            price=0,
            qty=qty,
            order_type="sell",
            status="Waiting",
            strategy_type="Custom Query Sell",
            security_details={"symbol": "HDL", "boardLot": 10},
            strategy_config={"query_text": query, "compiled_plan": compiled, "execution_mode": "live"},
        )

    async def test_percent_of_holding_schedules_without_freezing_qty(self):
        tms_user = AsyncMock()
        tms_user.get_user_stock_details.return_value = [{"scrip": "HDL", "currentBalance": 4}]
        order_data = self._order(SELL_100_PERCENT_QUERY, qty=100)
        _validate_strategy_order(order_data)
        await _validate_sell_lot_against_holdings(order_data, tms_user)
        self.assertEqual(order_data.qty, 0)
        self.assertEqual(order_data.remaining_quantity, 0)
        self.assertEqual(
            order_data.strategy_config["compiled_plan"]["rules"][0]["order"]["mode"],
            "percent_of_holding",
        )

    async def test_fixed_sell_quantity_still_rejects_when_it_exceeds_holding(self):
        fixed_qty_query = SELL_100_PERCENT_QUERY.replace("ORDER PERCENT_OF_HOLDING 100", "ORDER QUANTITY 100")
        tms_user = AsyncMock()
        tms_user.get_user_stock_details.return_value = [{"scrip": "HDL", "currentBalance": 4}]
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            await _validate_sell_lot_against_holdings(self._order(fixed_qty_query, qty=100), tms_user)
        self.assertIn("Sell quantity cannot exceed DP holding quantity (4)", str(ctx.exception.detail))


class DuplicateWorkerClaimTest(unittest.TestCase):
    def test_only_one_worker_claims_execution(self):
        db = MagicMock()
        first_result = MagicMock(rowcount=1)
        second_result = MagicMock(rowcount=0)
        release_result = MagicMock(rowcount=1)
        third_result = MagicMock(rowcount=1)
        db.execute.side_effect = [first_result, second_result, release_result, third_result]

        first = _try_claim_order_for_execution(db, 99)
        second = _try_claim_order_for_execution(db, 99)
        _release_execution_claim(db, 99)
        third = _try_claim_order_for_execution(db, 99)

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertTrue(third)
        self.assertEqual(db.execute.call_count, 4)


if __name__ == "__main__":
    unittest.main()
