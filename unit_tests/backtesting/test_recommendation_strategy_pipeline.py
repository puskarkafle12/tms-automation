"""Recommendation queries must survive backtest -> schedule -> monitor compilation unchanged."""

from utils.backtesting.presets import build_preset_query, get_backtest_presets
from utils.backtesting.recommendations import _trade_range_estimates
from utils.backtesting.strategy_discovery import build_discovery_sell_query, generate_discovery_presets
from utils.strategy_builder.strategy_parser import format_strategy_query, parse_strategy_query, retarget_strategy_query


def _round_trip(query: str, symbol: str, expected_side: str):
    targeted = retarget_strategy_query(query, [symbol])
    parsed = parse_strategy_query(targeted)
    formatted = format_strategy_query(parsed)
    reparsed = parse_strategy_query(formatted)
    assert reparsed.side == expected_side
    assert reparsed.rules
    assert all(rule.symbols == [symbol] for rule in reparsed.rules)
    parsed_payload = parsed.model_dump()
    reparsed_payload = reparsed.model_dump()
    # Rule IDs are parser-generated runtime identities and are intentionally
    # regenerated. The executable strategy contract must otherwise be exact.
    for payload in (parsed_payload, reparsed_payload):
        for rule in payload["rules"]:
            rule.pop("rule_id", None)
    assert reparsed_payload == parsed_payload
    return reparsed.model_dump()


def test_every_professional_preset_compiles_for_the_live_monitor_contract():
    presets = get_backtest_presets()
    assert len(presets) >= 100
    compiled = [_round_trip(build_preset_query(preset, "NABIL"), "NABIL", "BUY") for preset in presets]
    assert len(compiled) == len(presets)
    assert all(plan["rules"][0]["when"] for plan in compiled)


def test_combined_buy_and_sell_queries_share_the_schedule_monitor_contract():
    candidates = generate_discovery_presets(
        budget=100, seed=20260718, min_holding_days=5, max_holding_days=90,
    )
    for candidate in candidates:
        buy_plan = _round_trip(build_preset_query(candidate, "NABIL"), "API", "BUY")
        sell_query = build_discovery_sell_query(candidate, "NABIL")
        assert sell_query
        sell_plan = _round_trip(sell_query, "API", "SELL")
        assert buy_plan["rules"][0]["order"]["mode"] in {"percent_of_available_cash", "quantity", "amount"}
        assert sell_plan["rules"][0]["order"]["mode"] == "percent_of_holding"


def test_lifecycle_language_round_trips_buy_hold_and_risk_managed_sell():
    query = """
STRATEGY_VERSION 1
SIDE LIFECYCLE
POSITION_LIFECYCLE {
  MIN_HOLDING_DAYS 5
  MAX_HOLDING_DAYS 90
  SELL_ACTIVATION BUY_FILLED_AND_SETTLED
  REENTRY AFTER_POSITION_CLOSED
}
POSITION_EXIT {
  SELL ALL_AVAILABLE WHEN profit_percent <= -6
  SELL ALL_AVAILABLE WHEN profit_percent >= 15
  SELL ALL_AVAILABLE WHEN drawdown_from_peak_percent <= -3
}
RULE "MLBBL lifecycle" FOR SYMBOL "MLBBL" {
  WHEN technical_sma_20 = "above" AND technical_macd = "Bullish"
  ORDER PERCENT_OF_AVAILABLE_CASH 100
  TRIGGER ON_CROSS
  EXECUTE ONCE PER SYMBOL
}
"""
    plan = parse_strategy_query(query)
    assert plan.side == "BUY"
    assert plan.lifecycle is True
    assert plan.backtest is None
    assert plan.position_lifecycle.min_holding_days == 5
    assert plan.position_lifecycle.max_holding_days == 90
    assert len(plan.position_exit) == 3
    reparsed = parse_strategy_query(format_strategy_query(plan))
    for payload in (plan, reparsed):
        for rule in payload.rules:
            rule.rule_id = "stable-test-id"
    assert reparsed.model_dump() == plan.model_dump()


def test_recommendation_estimates_use_conservative_range_edges():
    estimates = _trade_range_estimates({
        "buy_zone_low": 98,
        "buy_zone_high": 102,
        "sell_zone_low": 112,
        "sell_zone_high": 116,
        "protective_stop": 95,
    })
    assert estimates["estimated_profit_pct"] == 9.8
    assert estimates["estimated_loss_pct"] == 6.86
    assert "Conservative" in estimates["estimate_basis"]
