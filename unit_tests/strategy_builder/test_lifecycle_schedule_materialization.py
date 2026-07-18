import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock, MagicMock, patch

from main import _create_paired_lifecycle_sell, _materialize_lifecycle_schedule
from models.scheduled_order import ScheduledOrder
from schemas.schemas import OrderCreateRequest
from utils.strategy_builder.strategy_parser import parse_strategy_query


def _request(query: str, *, order_type: str = "buy") -> OrderCreateRequest:
    plan = parse_strategy_query(query)
    return OrderCreateRequest(
        client_id="TEST-CLIENT",
        script_name="MLBBL",
        price=0,
        qty=10,
        order_type=order_type,
        strategy_type="Custom Query Buy",
        strategy_config={"query_text": query, "compiled_plan": plan.model_dump()},
    )


LIFECYCLE_QUERY = """
STRATEGY_VERSION 1
SIDE LIFECYCLE
POSITION_LIFECYCLE {
  MIN_HOLDING_DAYS 7
  MAX_HOLDING_DAYS 45
  SELL_ACTIVATION BUY_FILLED_AND_SETTLED
  REENTRY AFTER_POSITION_CLOSED
}
POSITION_EXIT {
  SELL ALL_AVAILABLE WHEN profit_percent <= -6
  SELL ALL_AVAILABLE WHEN profit_percent >= 15
}
RULE "SMA 20 Trend" FOR SYMBOL "MLBBL" {
  WHEN technical_sma_20 = "above" AND technical_macd = "Bullish"
  ORDER PERCENT_OF_AVAILABLE_CASH 100
  TRIGGER ON_CROSS
  EXECUTE ONCE PER SYMBOL
}
"""


def test_lifecycle_query_materializes_dormant_sell_without_existing_holding():
    request = _request(LIFECYCLE_QUERY)

    _materialize_lifecycle_schedule(request)

    config = request.strategy_config
    assert config["linear_position_cycle"] is True
    assert config["activation_requires_filled_buy"] is True
    assert config["activation_requires_holding"] is True
    assert config["reentry_requires_closed_position"] is True
    assert config["min_holding_days"] == 7
    assert config["max_holding_days"] == 45
    assert "BACKTEST" not in config["query_text"]
    assert "EXECUTE ONCE PER SYMBOL" in config["query_text"]
    sell_plan = parse_strategy_query(config["paired_sell_query_text"])
    assert sell_plan.side == "SELL"
    assert sell_plan.lifecycle is False
    assert sell_plan.rules[0].symbols == ["MLBBL"]
    assert sell_plan.rules[0].order.mode == "all_available"
    assert len(sell_plan.position_exit) == 2


def test_lifecycle_query_uses_safe_default_holding_window():
    request = _request(LIFECYCLE_QUERY.replace(
        "POSITION_LIFECYCLE {\n  MIN_HOLDING_DAYS 7\n  MAX_HOLDING_DAYS 45\n  SELL_ACTIVATION BUY_FILLED_AND_SETTLED\n  REENTRY AFTER_POSITION_CLOSED\n}\n",
        "",
    ))

    _materialize_lifecycle_schedule(request)

    assert request.strategy_config["min_holding_days"] == 5
    assert request.strategy_config["max_holding_days"] == 90


def test_legacy_lifecycle_max_execution_is_canonicalized_to_one_entry():
    legacy_query = LIFECYCLE_QUERY.replace(
        "POSITION_LIFECYCLE {\n  MIN_HOLDING_DAYS 7\n  MAX_HOLDING_DAYS 45\n  SELL_ACTIVATION BUY_FILLED_AND_SETTLED\n  REENTRY AFTER_POSITION_CLOSED\n}\n",
        "BACKTEST {\n  MIN_HOLDING_DAYS 7\n  MAX_HOLDING_DAYS 45\n}\n",
    ).replace("EXECUTE ONCE PER SYMBOL", "EXECUTE MAX 100 TIMES PER SYMBOL")
    request = _request(legacy_query)

    _materialize_lifecycle_schedule(request)

    assert "EXECUTE MAX 100" not in request.strategy_config["query_text"]
    assert "EXECUTE ONCE PER SYMBOL" in request.strategy_config["query_text"]
    assert "BACKTEST" not in request.strategy_config["query_text"]
    assert "POSITION_LIFECYCLE" in request.strategy_config["query_text"]
    compiled_rule = request.strategy_config["compiled_plan"]["rules"][0]
    assert compiled_rule["execution"]["frequency"] == "once_per_symbol"
    assert compiled_rule["execution"]["max_times"] is None


def test_lifecycle_requires_an_exit_contract():
    query = LIFECYCLE_QUERY.replace(
        "POSITION_EXIT {\n  SELL ALL_AVAILABLE WHEN profit_percent <= -6\n  SELL ALL_AVAILABLE WHEN profit_percent >= 15\n}\n",
        "",
    )
    request = _request(query)

    with pytest.raises(HTTPException, match="POSITION_EXIT"):
        _materialize_lifecycle_schedule(request)


def test_lifecycle_cannot_be_scheduled_as_standalone_sell():
    request = _request(LIFECYCLE_QUERY, order_type="sell")

    with pytest.raises(HTTPException, match="scheduled as a BUY"):
        _materialize_lifecycle_schedule(request)


@pytest.mark.asyncio
@patch("main._persist_order_field_references", new_callable=AsyncMock)
@patch("main._find_duplicate_scheduled_order", return_value=None)
async def test_paired_sell_is_created_dormant_without_portfolio_validation(_duplicate, _persist):
    request = _request(LIFECYCLE_QUERY)
    _materialize_lifecycle_schedule(request)
    buy_order = ScheduledOrder(request)
    buy_order.order_id = 11
    db = MagicMock()

    def assign_id(order):
        if getattr(order, "order_id", None) is None:
            order.order_id = 22

    db.add.side_effect = assign_id
    db.flush.side_effect = lambda: None

    sell_order = await _create_paired_lifecycle_sell(db, buy_order, request, owner_user_id=99)

    assert sell_order is not None
    assert sell_order.order_id == 22
    assert sell_order.status == "Waiting activation"
    assert sell_order.order_type == "sell"
    assert sell_order.strategy_config["activation_requires_filled_buy"] is True
    assert sell_order.strategy_config["activation_requires_holding"] is True
    assert sell_order.strategy_config["lifecycle_active"] is False
    assert buy_order.strategy_config["paired_sell_order_id"] == 22
