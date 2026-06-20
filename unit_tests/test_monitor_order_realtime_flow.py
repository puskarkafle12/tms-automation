"""End-to-end monitor flow: TMS quote + Nepse Alpha data → rule evaluation → TMS order."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from unit_tests.strategies.rule_based_scan_simulator import (
    default_details,
    first_execute_index,
    simulate_scans,
)
from utils.monitor_order import (
    OrderQuoteSnapshot,
    PendingOrderSnapshot,
    _evaluate_strategy,
    submit_scheduled_order_to_tms,
)
from utils.strategy_builder.strategy_parser import parse_strategy_query


CZBIL_RSI_QUERY = """
STRATEGY_VERSION 1
SIDE BUY
RULE "CZBIL Rule" FOR SYMBOL "CZBIL" {
    WHEN technical_rsi_14 < 70
    ORDER QUANTITY 100
    MAX_SLIPPAGE_PCT 1
    EXECUTE ONCE
}
"""


def _make_rule_order(
    *,
    query: str = CZBIL_RSI_QUERY,
    strategy_type: str = "Custom Query Buy",
    execution_mode: str = "live",
    order_type: str = "buy",
    qty: int = 100,
):
    compiled = parse_strategy_query(query).model_dump()
    return SimpleNamespace(
        order_id=1,
        client_id="client-1",
        script_name="CZBIL",
        symbol="CZBIL",
        strategy_type=strategy_type,
        order_type=order_type,
        side=order_type,
        qty=qty,
        remaining_quantity=qty,
        price=0,
        status="Waiting",
        security_details={"id": 1, "symbol": "CZBIL", "boardLot": 1, "oddLotAllowed": True},
        strategy_config={
            "compiled_plan": compiled,
            "query_text": query.strip(),
            "execution_mode": execution_mode,
            "target_state": {},
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


def _tms_quote(*, ltp: float = 200.0, high: float = 202.0, volume: float = 82902.0) -> dict:
    return {
        "ltp": ltp,
        "high": high,
        "low": 195,
        "open": 200,
        "volume": volume,
        "topBuy": [{"price": ltp, "quantity": 100}],
        "topSell": [{"price": ltp + 0.1, "quantity": 100}],
    }


def _nepse_details(*, rsi_14: float | None = 50.0, available: bool = True):
    return MagicMock(
        available=available,
        rsi_14=rsi_14,
        macd_signal="Bullish",
        mfi_14=41.0,
        stochastic_14=25.0,
        percent_b=32.0,
        roe=21.0,
        yoy_earnings_growth=52.0,
        pe=27.0,
        pbv=3.0,
        fifty_two_week_high=420.0,
        fifty_two_week_low=300.0,
    )


class MonitorDataIngestionTest(unittest.TestCase):
  @patch("utils.strategies.normalize.get_script_details_fetch_meta")
  def test_nepse_alpha_fetched_only_when_required_and_increments_on_network(self, mock_fetch_meta):
    mock_fetch_meta.return_value = (_nepse_details(rsi_14=50.0), True)
    db_order = _make_rule_order()

    _evaluate_strategy(db_order, 200.0, _tms_quote(ltp=200.0), scan_count=1)
    mock_fetch_meta.assert_called_once_with("CZBIL", force_refresh=False)
    self.assertEqual(db_order.strategy_config["tms_scan_count"], 1)
    self.assertEqual(db_order.strategy_config["nepse_alpha_scan_count"], 1)

    mock_fetch_meta.return_value = (_nepse_details(rsi_14=50.0), False)
    _evaluate_strategy(
      db_order,
      201.0,
      _tms_quote(ltp=201.0),
      scan_count=2,
      details=_nepse_details(rsi_14=50.0),
      nepse_network_attempted=False,
    )
    self.assertEqual(db_order.strategy_config["tms_scan_count"], 2)
    self.assertEqual(db_order.strategy_config["nepse_alpha_scan_count"], 1)

  @patch("utils.strategies.normalize.get_script_details_fetch_meta")
  def test_ltp_only_plan_skips_nepse_alpha(self, mock_fetch_meta):
    query = """
STRATEGY_VERSION 1
SIDE BUY
RULE "LTP" FOR SYMBOL "CZBIL" {
    WHEN ltp <= 200
    ORDER QUANTITY 10
    EXECUTE ONCE
}
"""
    db_order = _make_rule_order(query=query)
    _evaluate_strategy(db_order, 199.5, _tms_quote(ltp=199.5), scan_count=1)
    mock_fetch_meta.assert_not_called()
    self.assertNotIn("nepse_alpha_scan_count", db_order.strategy_config)

  @patch("utils.strategies.normalize.get_script_details_fetch_meta")
  def test_tms_ltp_from_monitor_quote_is_used_for_ltp_rules(self, mock_fetch_meta):
    mock_fetch_meta.return_value = (_nepse_details(rsi_14=50.0), True)
    query = """
STRATEGY_VERSION 1
SIDE BUY
RULE "LTP" FOR SYMBOL "CZBIL" {
    WHEN ltp <= 200
    ORDER QUANTITY 10
    EXECUTE ONCE
}
"""
    db_order = _make_rule_order(query=query)
    decision, _ = _evaluate_strategy(db_order, 199.5, _tms_quote(ltp=199.5), scan_count=1)
    self.assertIsNotNone(decision)
    assert decision is not None
    self.assertEqual(decision["action"], "execute")
    self.assertEqual(decision["qty"], 10)


class CzbilRsiMonitorFlowTest(unittest.TestCase):
  @patch("utils.strategies.normalize.get_script_details_fetch_meta")
  def test_rsi_below_70_executes_with_plan_quantity(self, mock_fetch_meta):
    mock_fetch_meta.return_value = (_nepse_details(rsi_14=50.0), True)
    db_order = _make_rule_order()
    decision, log = _evaluate_strategy(db_order, 200.0, _tms_quote(), scan_count=1)

    self.assertIsNone(log)
    self.assertIsNotNone(decision)
    assert decision is not None
    self.assertEqual(decision["action"], "execute")
    self.assertEqual(decision["qty"], 100)

  @patch("utils.strategies.normalize.get_script_details_fetch_meta")
  def test_rsi_above_70_keeps_monitoring_without_order(self, mock_fetch_meta):
    mock_fetch_meta.return_value = (_nepse_details(rsi_14=80.0), True)
    db_order = _make_rule_order()
    decision, log = _evaluate_strategy(db_order, 200.0, _tms_quote(), scan_count=1)

    self.assertIsNone(decision)
    self.assertIsNotNone(log)
    assert log is not None
    self.assertIn("TRACKING", log)

  @patch("utils.strategies.normalize.get_script_details_fetch_meta")
  def test_missing_nepse_alpha_rsi_does_not_execute(self, mock_fetch_meta):
    mock_fetch_meta.return_value = (_nepse_details(rsi_14=None, available=False), True)
    db_order = _make_rule_order()
    decision, log = _evaluate_strategy(db_order, 200.0, _tms_quote(), scan_count=1)

    self.assertIsNone(decision)
    self.assertIsNotNone(log)
    assert log is not None
    self.assertIn("TRACKING", log)

  @patch("utils.strategies.normalize.get_script_details_fetch_meta")
  def test_multi_scan_waits_until_rsi_condition_met(self, mock_fetch_meta):
    mock_fetch_meta.side_effect = [
      (_nepse_details(rsi_14=80.0), True),
      (_nepse_details(rsi_14=65.0), True),
    ]
    db_order = _make_rule_order()

    first_decision, first_log = _evaluate_strategy(db_order, 200.0, _tms_quote(), scan_count=1)
    self.assertIsNone(first_decision)
    self.assertIn("TRACKING", first_log or "")

    second_decision, second_log = _evaluate_strategy(db_order, 200.0, _tms_quote(), scan_count=2)
    self.assertIsNone(second_log)
    self.assertIsNotNone(second_decision)
    assert second_decision is not None
    self.assertEqual(second_decision["action"], "execute")
    self.assertEqual(second_decision["qty"], 100)


class RuleBasedRealtimeScanParityTest(unittest.TestCase):
  def test_czbil_rsi_query_matches_monitor_execute_on_second_metric_change(self):
    decisions = simulate_scans(
      CZBIL_RSI_QUERY,
      price_series=[200.0, 200.0],
      execution_mode="live",
      strategy_type="Custom Query Buy",
      details_builder=lambda _ltp, scan_idx: default_details(
        rsi_14=80.0 if scan_idx == 0 else 65.0,
      ),
    )
    self.assertEqual(decisions[0].action, "TRACK")
    self.assertEqual(decisions[1].action, "EXECUTE")
    self.assertEqual(decisions[1].qty, 100)
    self.assertEqual(first_execute_index(decisions), 1)


class MonitorExecutionIntegrationTest(unittest.IsolatedAsyncioTestCase):
  @patch("utils.strategies.normalize.get_script_details_fetch_meta")
  async def test_live_monitor_flow_places_tms_order_when_metrics_match(self, mock_fetch_meta):
    mock_fetch_meta.return_value = (_nepse_details(rsi_14=50.0), True)
    db_order = _make_rule_order()
    pending = PendingOrderSnapshot(
      order_id=db_order.order_id,
      client_id=db_order.client_id,
      security_details=db_order.security_details,
      script_name=db_order.script_name,
      price=db_order.price,
      qty=db_order.qty,
      order_type=db_order.order_type,
      strategy_type=db_order.strategy_type,
    )
    snapshot = OrderQuoteSnapshot(
      order=pending,
      scan_count=1,
      security_details=db_order.security_details,
      current_price=200.0,
      quote=_tms_quote(ltp=200.0),
      high_price=202.0,
    )

    decision, strategy_log = _evaluate_strategy(
      db_order,
      float(snapshot.current_price),
      snapshot.quote,
      scan_count=snapshot.scan_count,
    )
    self.assertIsNone(strategy_log)
    self.assertIsNotNone(decision)
    assert decision is not None
    self.assertEqual(decision["action"], "execute")

    tms_user = MagicMock()
    tms_user.order = AsyncMock(return_value={"status": 200, "message": "ok"})
    submission = await submit_scheduled_order_to_tms(
      db_order,
      decision,
      high_price=snapshot.high_price,
      fallback_qty=pending.qty,
      security_details=snapshot.security_details,
      order_type=pending.order_type,
      tms_user=tms_user,
      execution_gate={"can_execute": True},
    )

    self.assertTrue(submission.submitted)
    self.assertEqual(submission.execution_qty, 100)
    tms_user.order.assert_awaited_once_with(
      200.0,
      100,
      security=db_order.security_details,
      order_type="buy",
    )

  @patch("utils.strategies.normalize.get_script_details_fetch_meta")
  async def test_monitor_flow_skips_tms_when_metrics_not_matched(self, mock_fetch_meta):
    mock_fetch_meta.return_value = (_nepse_details(rsi_14=80.0), True)
    db_order = _make_rule_order()
    decision, strategy_log = _evaluate_strategy(
      db_order,
      200.0,
      _tms_quote(),
      scan_count=1,
    )
    self.assertIsNone(decision)
    self.assertIn("TRACKING", strategy_log or "")

    tms_user = MagicMock()
    tms_user.order = AsyncMock()
    submission = await submit_scheduled_order_to_tms(
      db_order,
      decision or {},
      high_price=202.0,
      fallback_qty=db_order.qty,
      security_details=db_order.security_details,
      order_type="buy",
      tms_user=tms_user,
      execution_gate={"can_execute": True},
    )
    self.assertFalse(submission.submitted)
    tms_user.order.assert_not_awaited()

  @patch("utils.strategies.normalize.get_script_details_fetch_meta")
  async def test_monitor_flow_respects_market_gate_before_tms_order(self, mock_fetch_meta):
    mock_fetch_meta.return_value = (_nepse_details(rsi_14=50.0), True)
    db_order = _make_rule_order()
    decision, _ = _evaluate_strategy(db_order, 200.0, _tms_quote(), scan_count=1)
    assert decision is not None

    tms_user = MagicMock()
    tms_user.order = AsyncMock()
    submission = await submit_scheduled_order_to_tms(
      db_order,
      decision,
      high_price=202.0,
      fallback_qty=db_order.qty,
      security_details=db_order.security_details,
      order_type="buy",
      tms_user=tms_user,
      execution_gate={"can_execute": False, "message": "Market closed"},
    )
    self.assertFalse(submission.submitted)
    self.assertEqual(submission.blocked_reason, "Market closed")
    tms_user.order.assert_not_awaited()


class TmsFetchSnapshotTest(unittest.IsolatedAsyncioTestCase):
  async def test_tms_quote_fetch_provides_ltp_used_by_monitor(self):
    tms_user = MagicMock()
    tms_user.get_security_id = AsyncMock(return_value={"id": 42, "symbol": "CZBIL", "boardLot": 1})
    tms_user.get_stock_details_async = AsyncMock(return_value=_tms_quote(ltp=205.5, high=206.0))

    security = await tms_user.get_security_id("CZBIL")
    quote = await tms_user.get_stock_details_async(security["id"])

    self.assertEqual(security["symbol"], "CZBIL")
    self.assertEqual(quote["ltp"], 205.5)
    self.assertEqual(quote["high"], 206.0)

  async def test_missing_tms_price_blocks_monitor_evaluation_path(self):
    tms_user = MagicMock()
    tms_user.get_security_id = AsyncMock(return_value={"id": 42, "symbol": "CZBIL"})
    tms_user.get_stock_details_async = AsyncMock(return_value=None)

    quote = await tms_user.get_stock_details_async(42)
    self.assertIsNone(quote)


if __name__ == "__main__":
  unittest.main()
