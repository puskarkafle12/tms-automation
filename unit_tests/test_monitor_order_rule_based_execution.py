"""Monitor path: _evaluate_strategy execute payload and TMS order() invocation."""

import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from utils.monitor_order import (
    _evaluate_strategy, _prepare_lifecycle_buy_monitor,
    _prepare_lifecycle_sell_monitor, _record_lifecycle_buy_submission,
    submit_scheduled_order_to_tms,
)
from utils.strategy_builder.strategy_parser import parse_strategy_query


def _make_db_order(*, execution_mode: str = "live", order_type: str = "buy"):
    query = """
STRATEGY_VERSION 1
SIDE BUY
RULE "CZBIL RSI Buy" FOR SYMBOL "CZBIL" {
    WHEN technical_rsi_14 > 30
    ORDER QUANTITY 100
    EXECUTE ONCE
}
"""
    compiled = parse_strategy_query(query).model_dump()
    return SimpleNamespace(
        order_id=1,
        client_id="client-1",
        script_name="CZBIL",
        symbol="CZBIL",
        strategy_type="Technical Buy",
        order_type=order_type,
        side=order_type,
        qty=100,
        remaining_quantity=100,
        price=0,
        status="Monitoring",
        security_details={"id": 1, "symbol": "CZBIL", "boardLot": 1, "oddLotAllowed": True},
        strategy_config={"compiled_plan": compiled, "execution_mode": execution_mode},
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


def _quote(ltp: float = 200.0, high: float = 202.0) -> dict:
    return {
        "ltp": ltp,
        "high": high,
        "low": 195,
        "open": 200,
        "volume": 82902,
        "topBuy": [{"price": ltp, "quantity": 100}],
        "topSell": [{"price": ltp + 0.1, "quantity": 100}],
    }


class EvaluateStrategyBridgeTest(unittest.TestCase):
    @patch("utils.strategies.normalize.get_script_details_fetch_meta")
    def test_evaluate_strategy_returns_execute_payload(self, mock_fetch_meta):
        mock_fetch_meta.return_value = (
            MagicMock(
                available=True,
                rsi_14=35.0,
                macd_signal="Bullish",
                mfi_14=41.0,
                stochastic_14=25.0,
                percent_b=32.0,
                roe=21.0,
                yoy_earnings_growth=52.0,
                pe=27.0,
                pbv=3.0,
            ),
            True,
        )
        db_order = _make_db_order(execution_mode="live")
        decision, log = _evaluate_strategy(db_order, 200.0, _quote(ltp=200.0), scan_count=1)
        self.assertIsNone(log)
        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision["action"], "execute")
        self.assertEqual(decision["qty"], 100)
        self.assertAlmostEqual(decision["price"], 200.0)

    @patch("utils.strategies.normalize.get_script_details_fetch_meta")
    def test_paper_mode_does_not_return_execute(self, mock_fetch_meta):
        mock_fetch_meta.return_value = (
            MagicMock(
                available=True,
                rsi_14=35.0,
                macd_signal="Bullish",
                mfi_14=41.0,
                stochastic_14=25.0,
                percent_b=32.0,
                roe=21.0,
                yoy_earnings_growth=52.0,
                pe=27.0,
                pbv=3.0,
            ),
            True,
        )
        db_order = _make_db_order(execution_mode="paper")
        decision, _ = _evaluate_strategy(db_order, 200.0, _quote(), scan_count=1)
        self.assertIsNone(decision)


class SubmitScheduledOrderToTmsTest(unittest.IsolatedAsyncioTestCase):
    async def test_live_execute_calls_tms_order(self):
        db_order = _make_db_order()
        tms_user = MagicMock()
        tms_user.order = AsyncMock(return_value={"status": 200, "message": "ok"})
        decision = {"action": "execute", "price": 200.0, "qty": 100, "source": "Rule engine"}

        result = await submit_scheduled_order_to_tms(
            db_order,
            decision,
            high_price=202.0,
            fallback_qty=100,
            security_details=db_order.security_details,
            order_type="buy",
            tms_user=tms_user,
            execution_gate={"can_execute": True},
        )

        self.assertTrue(result.submitted)
        tms_user.order.assert_awaited_once_with(
            200.0,
            100,
            security=db_order.security_details,
            order_type="buy",
        )

    async def test_gate_closed_does_not_call_tms_order(self):
        db_order = _make_db_order()
        tms_user = MagicMock()
        tms_user.order = AsyncMock()
        decision = {"action": "execute", "price": 200.0, "qty": 100}

        result = await submit_scheduled_order_to_tms(
            db_order,
            decision,
            high_price=202.0,
            fallback_qty=100,
            security_details=db_order.security_details,
            order_type="buy",
            tms_user=tms_user,
            execution_gate={"can_execute": False, "message": "Market closed"},
        )

        self.assertFalse(result.submitted)
        tms_user.order.assert_not_awaited()

    async def test_buy_above_day_high_blocked(self):
        db_order = _make_db_order()
        tms_user = MagicMock()
        tms_user.order = AsyncMock()
        decision = {"action": "execute", "price": 205.0, "qty": 100}

        result = await submit_scheduled_order_to_tms(
            db_order,
            decision,
            high_price=200.0,
            fallback_qty=100,
            security_details=db_order.security_details,
            order_type="buy",
            tms_user=tms_user,
            execution_gate={"can_execute": True},
        )

        self.assertFalse(result.submitted)
        self.assertIn("exceeds today's high", result.blocked_reason or "")
        tms_user.order.assert_not_awaited()

    async def test_linear_cycle_blocks_another_buy_until_existing_holding_is_sold(self):
        db_order = _make_db_order()
        db_order.strategy_config.update({
            "linear_position_cycle": True,
            "min_holding_days": 5,
            "max_holding_days": 90,
        })
        tms_user = MagicMock()
        tms_user.order = AsyncMock()
        with patch("utils.monitor_order._latest_holding_qty", new=AsyncMock(return_value=25)):
            result = await submit_scheduled_order_to_tms(
                db_order,
                {"action": "execute", "price": 200.0, "qty": 10},
                high_price=202.0,
                fallback_qty=10,
                security_details=db_order.security_details,
                order_type="buy",
                tms_user=tms_user,
                execution_gate={"can_execute": True},
            )

        self.assertFalse(result.submitted)
        self.assertIn("waiting for the existing CZBIL holding", result.blocked_reason or "")
        tms_user.order.assert_not_awaited()

    async def test_sell_calls_order_with_sell_type(self):
        db_order = _make_db_order(order_type="sell")
        db_order.strategy_type = "Custom Query Sell"
        tms_user = MagicMock()
        tms_user.order = AsyncMock(return_value={"status": 200})
        with patch("utils.monitor_order._latest_holding_qty", new=AsyncMock(return_value=100)):
            result = await submit_scheduled_order_to_tms(
                db_order,
                {"action": "execute", "price": 210.0, "qty": 50},
                high_price=220.0,
                fallback_qty=100,
                security_details=db_order.security_details,
                order_type="sell",
                tms_user=tms_user,
                execution_gate={"can_execute": True},
            )

        self.assertTrue(result.submitted)
        tms_user.order.assert_awaited_once_with(
            210.0,
            50,
            security=db_order.security_details,
            order_type="sell",
        )

    async def test_lot_rule_blocked_does_not_call_tms_order(self):
        db_order = _make_db_order()
        db_order.security_details = {"id": 1, "symbol": "CZBIL", "boardLot": 10, "oddLotAllowed": False}
        tms_user = MagicMock()
        tms_user.order = AsyncMock()
        decision = {"action": "execute", "price": 200.0, "qty": 15}

        result = await submit_scheduled_order_to_tms(
            db_order,
            decision,
            high_price=202.0,
            fallback_qty=100,
            security_details=db_order.security_details,
            order_type="buy",
            tms_user=tms_user,
            execution_gate={"can_execute": True},
        )

        self.assertFalse(result.submitted)
        self.assertTrue(result.lot_rule_blocked)
        self.assertIn("board-lot", (result.blocked_reason or "").lower())
        tms_user.order.assert_not_awaited()


class LifecycleActivationTest(unittest.IsolatedAsyncioTestCase):
    def _sell_order(self, *, confirmed=False):
        plan = parse_strategy_query("""
STRATEGY_VERSION 1
SIDE SELL
BACKTEST { MIN_HOLDING_DAYS 5 MAX_HOLDING_DAYS 90 }
POSITION_EXIT { SELL ALL_AVAILABLE WHEN profit_percent >= 15 }
RULE "Dormant exit" FOR SYMBOL "MLBBL" {
  WHEN ltp < 0
  ORDER ALL_AVAILABLE
  EXECUTE ONCE PER SYMBOL
}
""")
        return SimpleNamespace(
            order_id=22, order_type="sell", script_name="MLBBL", status="Waiting activation", qty=20,
            last_checked_ltp=None, last_checked_at=None, updated_at=None, average_buy_price=None,
            strategy_config={"compiled_plan": plan.model_dump(), "linear_position_cycle": True,
                             "lifecycle_role": "sell", "paired_buy_order_id": 11,
                             "min_holding_days": 5, "max_holding_days": 90,
                             **({"linked_buy_fill_confirmed": True,
                                 "linked_buy_executed_at": "2026-07-01T00:00:00",
                                 "linked_buy_execution_price": 100,
                                 "linked_buy_filled_quantity": 20,
                                 "linked_buy_baseline_holding_qty": 0} if confirmed else {})},
        )

    @patch("utils.monitor_order.object_session")
    @patch("utils.monitor_order._latest_holding_qty", new_callable=AsyncMock)
    async def test_sell_waits_for_successful_linked_buy(self, holding_mock, session_mock):
        order = self._sell_order()
        session_mock.return_value.get.return_value = SimpleNamespace(executed_at=None)
        ready, message = await _prepare_lifecycle_sell_monitor(order, AsyncMock())
        self.assertFalse(ready)
        self.assertIn("not confirmed fully traded", message)
        holding_mock.assert_not_awaited()

    @patch("utils.monitor_order.object_session")
    @patch("utils.monitor_order._linear_holding_sessions", return_value=4)
    @patch("utils.monitor_order._latest_holding_qty", new_callable=AsyncMock)
    async def test_sell_does_not_check_or_monitor_before_minimum_sessions(self, holding_mock, _sessions, session_mock):
        order = self._sell_order(confirmed=True)
        session_mock.return_value.get.return_value = SimpleNamespace(executed_at=datetime(2026, 7, 1), execution_price=100, last_checked_ltp=100, price=100)
        ready, message = await _prepare_lifecycle_sell_monitor(order, AsyncMock())
        self.assertFalse(ready)
        self.assertIn("4/5", message)
        self.assertEqual(order.status, "Waiting minimum time")
        holding_mock.assert_not_awaited()

    @patch("utils.monitor_order.object_session")
    @patch("utils.monitor_order._linear_holding_sessions", return_value=5)
    @patch("utils.monitor_order._latest_holding_qty", new_callable=AsyncMock, return_value=20)
    async def test_sell_activates_only_after_holding_is_sellable(self, _holding, _sessions, session_mock):
        order = self._sell_order(confirmed=True)
        session_mock.return_value.get.return_value = SimpleNamespace(executed_at=datetime(2026, 7, 1), execution_price=100, last_checked_ltp=100, price=100)
        ready, message = await _prepare_lifecycle_sell_monitor(order, AsyncMock())
        self.assertTrue(ready, message)
        self.assertTrue(order.strategy_config["lifecycle_active"])
        self.assertTrue(order.strategy_config["lifecycle_holding_verified"])
        self.assertEqual(order.strategy_config["target_state"]["MLBBL"]["position"]["entry_price"], 100)

    @patch("utils.monitor_order.object_session")
    @patch("utils.monitor_order._latest_holding_qty", new_callable=AsyncMock, return_value=0)
    async def test_buy_submission_waits_for_full_tms_traded_quantity(self, _holding, session_mock):
        sell = self._sell_order()
        session_mock.return_value.get.return_value = sell
        buy = SimpleNamespace(
            order_id=11, order_type="buy", script_name="MLBBL", qty=10,
            status="Waiting fill", remaining_quantity=10, executed_at=None,
            execution_price=1149, strategy_config={
                "lifecycle_role": "buy", "linear_position_cycle": True,
                "paired_sell_order_id": 22, "baseline_holding_qty": 0,
                "submitted_at": "2026-07-19T04:00:00", "submitted_quantity": 10,
                "submitted_price": 1149, "exchange_order_id": "EX-1",
            },
        )
        tms = AsyncMock()
        tms.get_normalized_daily_order_book.return_value = [{
            "symbol": "MLBBL", "buyOrSell": 1, "exchangeOrderId": "EX-1",
            "orderQuantity": 10, "totalTradedQuantity": 5,
            "displayActiveStatus": "PARTIALLY_TRADED",
        }]
        ready, message = await _prepare_lifecycle_buy_monitor(buy, tms)
        self.assertFalse(ready)
        self.assertIn("5/10", message)
        self.assertEqual(buy.status, "Waiting fill")
        self.assertIsNone(buy.executed_at)
        self.assertFalse(sell.strategy_config.get("linked_buy_fill_confirmed", False))

        tms.get_normalized_daily_order_book.return_value[0]["totalTradedQuantity"] = 10
        ready, message = await _prepare_lifecycle_buy_monitor(buy, tms)
        self.assertFalse(ready)
        self.assertIn("fill confirmed", message)
        self.assertEqual(buy.status, "Executed")
        self.assertIsNotNone(buy.executed_at)
        self.assertTrue(sell.strategy_config["linked_buy_fill_confirmed"])
        self.assertEqual(sell.strategy_config["linked_buy_filled_quantity"], 10)
        self.assertEqual(sell.qty, 10)

    async def test_broker_acceptance_is_recorded_as_waiting_fill_not_executed(self):
        buy = SimpleNamespace(
            order_type="buy", script_name="MLBBL", status="Executing",
            executed_at=datetime(2026, 7, 19), strategy_config={
                "lifecycle_role": "buy", "linear_position_cycle": True,
                "baseline_holding_qty": 0,
            },
        )
        tms = AsyncMock()
        tms.get_latest_order_timing_for_symbol.return_value = {
            "exchange_order_id": "EX-10", "order_status": "OPEN",
        }
        recorded = await _record_lifecycle_buy_submission(
            buy, tms, submitted_price=1149, submitted_quantity=10,
        )
        self.assertTrue(recorded)
        self.assertEqual(buy.status, "Waiting fill")
        self.assertIsNone(buy.executed_at)
        self.assertFalse(buy.strategy_config["fill_confirmed"])
        self.assertEqual(buy.strategy_config["exchange_order_id"], "EX-10")


if __name__ == "__main__":
    unittest.main()
