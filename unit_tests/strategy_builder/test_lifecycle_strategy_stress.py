"""High-volume lifecycle query and simulated live-execution stress coverage."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from main import _create_paired_lifecycle_sell, _materialize_lifecycle_schedule
from models.scheduled_order import ScheduledOrder
from schemas.schemas import OrderCreateRequest
from unit_tests.strategies.rule_based_scan_simulator import first_execute_index, simulate_scans
from utils.backtesting.presets import build_preset_query, get_backtest_presets
from utils.monitor_order import (
    _prepare_lifecycle_buy_monitor,
    _prepare_lifecycle_sell_monitor,
    _record_lifecycle_buy_submission,
    submit_scheduled_order_to_tms,
)
from utils.strategy_builder.history_service import TargetHistory, serialize_target_history
from utils.strategy_builder.position_protection import seed_position_after_buy
from utils.strategy_builder.strategy_models import (
    ComparisonNode,
    FieldNode,
    LiteralNode,
    PositionExitAction,
    PositionLifecycleConfig,
)
from utils.strategy_builder.strategy_parser import format_strategy_query, parse_strategy_query


SYMBOL = "MLBBL"


def _comparison(field: str, operator: str, value: float) -> ComparisonNode:
    return ComparisonNode(
        left=FieldNode(name=field), operator=operator, right=LiteralNode(value=value),
    )


def _lifecycle_request(query: str, *, qty: int = 10) -> OrderCreateRequest:
    plan = parse_strategy_query(query)
    return OrderCreateRequest(
        client_id="TEST-CLIENT",
        script_name=SYMBOL,
        security_details={"id": 1, "symbol": SYMBOL, "boardLot": 1, "oddLotAllowed": True},
        price=0,
        qty=qty,
        order_type="buy",
        status="Waiting",
        strategy_type="Custom Query Buy",
        strategy_config={
            "query_text": query,
            "compiled_plan": plan.model_dump(),
            "execution_mode": "live",
        },
    )


def _catalog_lifecycle_queries() -> list[str]:
    queries: list[str] = []
    risk_variants = [
        (4, 8, 3, 20),
        (5, 12, 5, 45),
        (6, 15, 5, 60),
        (8, 21, 7, 90),
    ]
    for preset in get_backtest_presets():
        base = parse_strategy_query(build_preset_query(preset, SYMBOL))
        for stop_pct, target_pct, min_days, max_days in risk_variants:
            position_lifecycle = PositionLifecycleConfig(
                min_holding_days=min_days,
                max_holding_days=max_days,
            )
            lifecycle = base.model_copy(deep=True, update={
                "side": "BUY",
                "lifecycle": True,
                "backtest": None,
                "position_lifecycle": position_lifecycle,
                "position_exit": [
                    PositionExitAction(
                        action="sell", order_mode="all_available",
                        when=_comparison("profit_percent", "lte", -stop_pct),
                    ),
                    PositionExitAction(
                        action="sell", order_mode="all_available",
                        when=_comparison("profit_percent", "gte", target_pct),
                    ),
                ],
            })
            queries.append(format_strategy_query(lifecycle))
    return queries


def _executable_query(index: int) -> tuple[str, float, float, int, int]:
    entry = float(180 + (index % 25))
    stop = float(4 + (index % 5))
    target = float(8 + (index % 14))
    min_days = [0, 1, 3, 5, 7][index % 5]
    max_days = max(min_days + 1, [20, 30, 45, 60, 90][index % 5])
    query = f"""
STRATEGY_VERSION 1
SIDE LIFECYCLE
POSITION_LIFECYCLE {{
  MIN_HOLDING_DAYS {min_days}
  MAX_HOLDING_DAYS {max_days}
  SELL_ACTIVATION BUY_FILLED_AND_SETTLED
  REENTRY AFTER_POSITION_CLOSED
}}
POSITION_EXIT {{
  SELL ALL_AVAILABLE WHEN profit_percent <= -{stop:g}
  SELL ALL_AVAILABLE WHEN profit_percent >= {target:g}
}}
RULE "Stress lifecycle {index}" FOR SYMBOL "{SYMBOL}" {{
  WHEN ltp <= {entry:g}
  ORDER QUANTITY 10
  TRIGGER ON_CROSS
  EXECUTE ONCE PER SYMBOL
}}
"""
    return query, entry, target, min_days, max_days


def test_more_than_five_hundred_real_catalog_lifecycle_queries_round_trip_and_schedule():
    queries = _catalog_lifecycle_queries()
    assert len(queries) >= 500
    assert len(set(queries)) == len(queries)

    for query in queries:
        parsed = parse_strategy_query(query)
        reparsed = parse_strategy_query(format_strategy_query(parsed))
        assert reparsed.lifecycle is True
        request = _lifecycle_request(query)
        _materialize_lifecycle_schedule(request)
        config = request.strategy_config
        sell_plan = parse_strategy_query(config["paired_sell_query_text"])
        assert sell_plan.side == "SELL"
        assert sell_plan.position_exit
        assert config["activation_requires_filled_buy"] is True
        assert config["activation_requires_holding"] is True


def test_one_hundred_twenty_executable_lifecycle_queries_scan_buy_and_sell_signals():
    for index in range(120):
        query, entry, target, min_days, max_days = _executable_query(index)
        request = _lifecycle_request(query)
        _materialize_lifecycle_schedule(request)

        buy_decisions = simulate_scans(
            query,
            price_series=[entry + 1, entry],
            execution_mode="live",
            strategy_type="Custom Query Buy",
            side="buy",
            symbol=SYMBOL,
            qty=10,
        )
        assert first_execute_index(buy_decisions) == 1

        position = seed_position_after_buy({}, entry_price=entry, protection=None)
        history = TargetHistory(position=position)
        sell_decisions = simulate_scans(
            request.strategy_config["paired_sell_query_text"],
            price_series=[entry * (1 + (target + 0.5) / 100)],
            execution_mode="live",
            strategy_type="Custom Query Sell",
            side="sell",
            symbol=SYMBOL,
            qty=10,
            holding_qty=10,
            target_state={SYMBOL: serialize_target_history(history)},
        )
        assert sell_decisions[0].action == "EXECUTE"
        assert request.strategy_config["min_holding_days"] == min_days
        assert request.strategy_config["max_holding_days"] == max_days


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", range(12))
@patch("main._persist_order_field_references", new_callable=AsyncMock)
@patch("main._find_duplicate_scheduled_order", return_value=None)
async def test_full_live_lifecycle_waits_for_fill_settlement_and_minimum_days(
    _duplicate, _persist, variant,
):
    query, entry, target, _query_min_days, max_days = _executable_query(variant)
    plan = parse_strategy_query(query)
    plan.position_lifecycle = plan.position_lifecycle.model_copy(update={"min_holding_days": 5})
    query = format_strategy_query(plan)
    request = _lifecycle_request(query)
    _materialize_lifecycle_schedule(request)
    buy_order = ScheduledOrder(request)
    buy_order.order_id = 1000 + variant

    fake_db = MagicMock()
    next_sell_id = 2000 + variant

    def add_order(order):
        if getattr(order, "order_id", None) is None:
            order.order_id = next_sell_id

    fake_db.add.side_effect = add_order
    paired_sell = await _create_paired_lifecycle_sell(
        fake_db, buy_order, request, owner_user_id=99,
    )
    assert paired_sell is not None
    assert paired_sell.status == "Waiting activation"

    fake_session = MagicMock()
    fake_session.get.side_effect = lambda _model, order_id: (
        paired_sell if int(order_id) == next_sell_id else buy_order
    )
    tms = MagicMock()
    tms.order = AsyncMock(return_value={"status": 200, "message": "accepted"})
    tms.get_latest_order_timing_for_symbol = AsyncMock(return_value={
        "exchange_order_id": f"EX-{variant}", "order_status": "OPEN",
    })
    tms.get_normalized_daily_order_book = AsyncMock(return_value=[{
        "symbol": SYMBOL,
        "buyOrSell": 1,
        "exchangeOrderId": f"EX-{variant}",
        "orderQuantity": 10,
        "totalTradedQuantity": 5,
        "displayActiveStatus": "PARTIALLY_TRADED",
    }])

    with patch("utils.monitor_order._latest_holding_qty", new=AsyncMock(return_value=0)):
        submitted = await submit_scheduled_order_to_tms(
            buy_order,
            {"action": "execute", "price": entry, "qty": 10, "source": "stress scan"},
            high_price=entry + 5,
            fallback_qty=10,
            security_details=request.security_details,
            order_type="buy",
            tms_user=tms,
            execution_gate={"can_execute": True},
        )
    assert submitted.submitted is True
    assert await _record_lifecycle_buy_submission(
        buy_order, tms, submitted_price=entry, submitted_quantity=10,
    ) is True
    assert buy_order.status == "Waiting fill"
    assert buy_order.executed_at is None

    with patch("utils.monitor_order.object_session", return_value=fake_session), patch(
        "utils.monitor_order._latest_holding_qty", new=AsyncMock(return_value=0),
    ):
        ready, message = await _prepare_lifecycle_buy_monitor(buy_order, tms)
    assert ready is False
    assert "5/10" in message

    tms.get_normalized_daily_order_book.return_value[0]["totalTradedQuantity"] = 10
    with patch("utils.monitor_order.object_session", return_value=fake_session), patch(
        "utils.monitor_order._latest_holding_qty", new=AsyncMock(return_value=0),
    ):
        ready, message = await _prepare_lifecycle_buy_monitor(buy_order, tms)
    assert ready is False
    assert "fill confirmed" in message
    assert buy_order.status == "Executed"
    assert paired_sell.strategy_config["linked_buy_fill_confirmed"] is True

    with patch("utils.monitor_order.object_session", return_value=fake_session), patch(
        "utils.monitor_order._linear_holding_sessions", return_value=4,
    ), patch("utils.monitor_order._latest_holding_qty", new=AsyncMock(return_value=10)):
        ready, message = await _prepare_lifecycle_sell_monitor(paired_sell, tms)
    assert ready is False
    assert "4/5" in message

    with patch("utils.monitor_order.object_session", return_value=fake_session), patch(
        "utils.monitor_order._linear_holding_sessions", return_value=5,
    ), patch("utils.monitor_order._latest_holding_qty", new=AsyncMock(return_value=0)):
        ready, message = await _prepare_lifecycle_sell_monitor(paired_sell, tms)
    assert ready is False
    assert "sellable holding" in message

    with patch("utils.monitor_order.object_session", return_value=fake_session), patch(
        "utils.monitor_order._linear_holding_sessions", return_value=5,
    ), patch("utils.monitor_order._latest_holding_qty", new=AsyncMock(return_value=10)):
        ready, message = await _prepare_lifecycle_sell_monitor(paired_sell, tms)
    assert ready is True, message
    assert paired_sell.strategy_config["lifecycle_active"] is True

    position = seed_position_after_buy({}, entry_price=entry, protection=None)
    history = TargetHistory(position=position)
    sell_decision = simulate_scans(
        paired_sell.strategy_config["query_text"],
        price_series=[entry * (1 + (target + 0.5) / 100)],
        execution_mode="live",
        strategy_type="Custom Query Sell",
        side="sell",
        symbol=SYMBOL,
        qty=10,
        holding_qty=10,
        target_state={SYMBOL: serialize_target_history(history)},
    )[0]
    assert sell_decision.action == "EXECUTE"

    sell_tms = MagicMock()
    sell_tms.order = AsyncMock(return_value={"status": 200, "message": "accepted"})
    sell_tms.get_user_stock_details = AsyncMock(return_value=[{
        "scrip": SYMBOL, "symbolName": SYMBOL, "currentBalance": 10,
    }])
    with patch("utils.monitor_order._latest_holding_qty", new=AsyncMock(return_value=10)), patch(
        "utils.monitor_order._linear_holding_sessions", return_value=5,
    ):
        sold = await submit_scheduled_order_to_tms(
            paired_sell,
            {
                "action": "execute",
                "price": entry * (1 + (target + 0.5) / 100),
                "qty": 10,
                "source": "lifecycle target",
                "order_action": {"mode": "all_available"},
            },
            high_price=entry * (1 + (target + 0.5) / 100),
            fallback_qty=10,
            security_details=request.security_details,
            order_type="sell",
            tms_user=sell_tms,
            execution_gate={"can_execute": True},
        )
    assert sold.submitted is True
    sell_tms.order.assert_awaited_once()
    assert request.strategy_config["max_holding_days"] == max_days
