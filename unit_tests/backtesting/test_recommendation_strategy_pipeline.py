"""Recommendation queries must survive backtest -> schedule -> monitor compilation unchanged."""

from utils.backtesting.presets import build_preset_query, get_backtest_presets
from utils.backtesting.accelerated import compile_preset_exit_signals, compile_preset_signals
from utils.backtesting.recommendations import _trade_range_estimates
from utils.backtesting.strategy_discovery import build_discovery_sell_query, generate_discovery_presets
from utils.backtesting.v2_jobs import IPO_WORKSPACE_TRADABILITY_GATE, _apply_ipo_workspace_gate
from utils.strategy_builder.history_service import TargetHistory, append_observation
from utils.strategy_builder.rule_evaluator import evaluate_rule
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


def test_new_ipo_presets_are_distinct_limited_history_hypotheses():
    presets = [
        preset for preset in get_backtest_presets()
        if preset["category"] == "New IPO aftermarket research"
    ]
    assert len(presets) == 34
    assert {preset["family"] for preset in presets} == {"new_ipo_aftermarket"}
    assert all("technical_sma_200" not in preset["condition"] for preset in presets)
    assert all(preset["exit_rule_id"] and preset["exit_condition"] for preset in presets)
    assert all("PREVIOUS(field=ltp, offset=1) < PREVIOUS(field=open, offset=1)" in preset["condition"] for preset in presets)
    assert all("PREVIOUS(field=change_percent, offset=1) <= -4" not in preset["condition"] for preset in presets)
    assert all("PREVIOUS(field=volume, offset=1) > 5000" not in preset["condition"] for preset in presets)
    tier1 = [preset for preset in presets if preset.get("tier") == "ipo_tier1_research"]
    assert len(tier1) == 4
    assert {preset["recommended_listing_age_days"] for preset in tier1} == {90, 180, 365, 730}
    lifecycle = {preset["id"]: preset for preset in presets}
    assert lifecycle["ipo_markup_peak_protection"]["defaults"]["trailing_stop_pct"] == 7
    assert lifecycle["ipo_post_spike_recovery"]["defaults"]["take_profit_pct"] == 16
    assert lifecycle["ipo_post_spike_recovery"]["defaults"]["trailing_stop_pct"] == 5


def test_new_ipo_tradability_gate_allows_buy_only_after_prior_red_candle():
    query = '''STRATEGY_VERSION 1
SIDE BUY
RULE "IPO tradability gate" FOR SYMBOL "IPO" {
  WHEN PREVIOUS(field=ltp, offset=1) < PREVIOUS(field=open, offset=1)
  ORDER PERCENT_OF_AVAILABLE_CASH 100
}'''
    rule = parse_strategy_query(query).rules[0]

    def matches(*, decline_close=95, decline_open=98):
        history = TargetHistory()
        observations = {
            "ltp": [100, decline_close, decline_close + 1],
            "open": [100, decline_open, decline_close],
            "change_percent": [0, -3, 1],
            "volume": [1000, 100, 1000],
        }
        for field, values in observations.items():
            for index, value in enumerate(values):
                append_observation(
                    history, field, value,
                    source_timestamp=f"2026-01-{index + 1:02d}",
                    policy="count_only_new_trade",
                )
        result = evaluate_rule(
            rule, "IPO",
            {"ltp": decline_close + 1, "open": decline_close, "change_percent": 1, "volume": 1000},
            history, trigger_on_cross=False,
        )
        return result.final_result

    assert matches() is True
    assert matches(decline_close=99, decline_open=98) is False
    assert matches(decline_close=98, decline_open=98) is False


def test_new_ipo_presets_use_generic_causal_compiler_fallback():
    rows = [
        {"session_date": "2026-01-01", "ltp": 100, "open": 100, "volume": 1000, "change_percent": 0},
        {"session_date": "2026-01-02", "ltp": 95, "open": 98, "volume": 9000, "change_percent": -5},
        {
            "session_date": "2026-01-03", "ltp": 100, "open": 96, "volume": 8000, "change_percent": 5.26,
            "technical_vwap_20": 95, "technical_price_zscore_20": 0,
            "technical_cmf_20": .1,
        },
    ]
    assert compile_preset_signals("ipo_first_base_vwap_reclaim", rows) == [False, False, True]
    assert len(compile_preset_exit_signals("ipo_post_spike_recovery", rows)) == len(rows)


def test_ipo_workspace_applies_tradability_gate_to_every_catalog_strategy():
    presets = get_backtest_presets()
    normal = next(item for item in presets if item["id"] == "consecutive_rises_5")
    dedicated = next(item for item in presets if item["id"] == "ipo_nonextended_markup")
    gated_normal, gated_dedicated = _apply_ipo_workspace_gate(
        [normal, dedicated],
        {"run_type": "ipo_research", "apply_ipo_tradability_gate": True},
    )
    assert IPO_WORKSPACE_TRADABILITY_GATE in gated_normal["condition"]
    assert gated_normal["source_hash"] != normal["source_hash"]
    assert gated_normal["force_condition_compiler"] is True
    assert gated_normal["apply_ipo_tradability_gate"] is True
    assert gated_dedicated["condition"].count(IPO_WORKSPACE_TRADABILITY_GATE) == 1


def test_ipo_workspace_keeps_discovery_component_path_instead_of_force_compiler():
    candidate = generate_discovery_presets(
        budget=1, seed=7,
        base_ids=[item["id"] for item in get_backtest_presets() if str(item["id"]).startswith("ipo_")][:3],
        min_holding_days=5, max_holding_days=60, include_singles=True,
    )[0]
    assert candidate.get("component_ids")
    gated = _apply_ipo_workspace_gate(
        [candidate],
        {"run_type": "ipo_research", "apply_ipo_tradability_gate": True},
    )[0]
    assert gated["apply_ipo_tradability_gate"] is True
    assert gated.get("force_condition_compiler") is not True
    assert gated["ipo_tradability_gate_condition"] == IPO_WORKSPACE_TRADABILITY_GATE
    assert IPO_WORKSPACE_TRADABILITY_GATE in gated["condition"]


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
