from datetime import date, datetime, timedelta, timezone

from utils.backtesting.accelerated import compile_preset_signals
from utils.backtesting.presets import build_preset_query, get_backtest_presets
from utils.backtesting.service import Bar, run_backtest
from utils.backtesting.strategy_discovery import (
    build_discovery_sell_query,
    discovery_space_size,
    generate_discovery_presets,
)
from utils.strategy_builder.strategy_parser import parse_strategy_query


def _bar(day: int, price: float) -> Bar:
    timestamp = int(datetime(2025, 1, day, tzinfo=timezone.utc).timestamp())
    return Bar(timestamp, price, price + 1, price - 1, price, 10_000)


def test_discovery_is_deterministic_unique_and_billion_scale():
    base_ids = [item["id"] for item in get_backtest_presets()]
    assert discovery_space_size(len(base_ids)) >= 1_000_000_000
    first = generate_discovery_presets(
        budget=250, seed=42, base_ids=base_ids, min_holding_days=5, max_holding_days=60,
    )
    second = generate_discovery_presets(
        budget=250, seed=42, base_ids=base_ids, min_holding_days=5, max_holding_days=60,
    )
    assert [item["source_hash"] for item in first] == [item["source_hash"] for item in second]
    assert len({item["source_hash"] for item in first}) == 250
    assert {item["defaults"]["min_holding_days"] for item in first} == {5}
    assert len({item["exit_rule_id"] for item in first}) >= 8


def test_all_generated_nested_function_queries_parse():
    candidates = generate_discovery_presets(
        budget=1000, seed=20260718, min_holding_days=5, max_holding_days=90,
    )
    assert len(candidates) == 1000
    for candidate in candidates:
        plan = parse_strategy_query(build_preset_query(candidate, "NABIL"))
        assert plan.rules[0].when is not None


def test_combination_uses_component_states_before_single_cross():
    rows = [
        {"ltp": 100, "change_percent": 1, "technical_rsi_14": 35},
        {"ltp": 101, "change_percent": 1, "technical_rsi_14": 36},
        {"ltp": 100, "change_percent": -1, "technical_rsi_14": 36},
    ]
    raw = compile_preset_signals("rsi_recovery_40", rows, trigger_on_cross=False)
    crossed = compile_preset_signals("rsi_recovery_40", rows)
    assert raw == [True, True, False]
    assert crossed == [True, False, False]


def test_independent_sell_condition_exits_at_next_open():
    bars = [_bar(1, 100), _bar(2, 101), _bar(3, 104), _bar(4, 105)]
    query = '''STRATEGY_VERSION 1
SIDE BUY
RULE "Entry" FOR SYMBOL "NABIL" {
  WHEN ltp > 0
  ORDER QUANTITY 10
  EXECUTE MAX 10 TIMES PER SYMBOL
}'''
    output = run_backtest(
        symbol="NABIL", query_text=query, start_date=date(2025, 1, 1), end_date=date(2025, 1, 4),
        bars=bars, entry_signals=[True, False, False, False],
        exit_signals=[False, True, False, False], min_holding_days=0,
        max_holding_days=60, stop_loss_pct=20, take_profit_pct=100,
        fee_pct=0, slippage_pct=0,
    )
    trade = output["trades"][0]
    assert trade["entry_date"] == "2025-01-02"
    assert trade["exit_date"] == "2025-01-03"
    assert trade["exit_price"] == 104
    assert trade["exit_reason"] == "condition_exit_next_open"


def test_discovered_sell_query_is_valid_for_paper_and_live_pipeline():
    candidate = generate_discovery_presets(
        budget=1, seed=7, base_ids=[item["id"] for item in get_backtest_presets()[:3]],
        min_holding_days=5, max_holding_days=60,
    )[0]
    query = build_discovery_sell_query(candidate, "NABIL")
    plan = parse_strategy_query(query or "")
    assert plan.side == "SELL"
    assert plan.rules[0].symbols == ["NABIL"]
    assert plan.rules[0].order.mode == "percent_of_holding"


def test_every_match_has_no_lifetime_trade_cap():
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    bars = [Bar(int((start + timedelta(days=index)).timestamp()), 100, 101, 99, 100, 10_000) for index in range(370)]
    entries = [index % 3 == 0 for index in range(len(bars))]
    exits = [index % 3 == 1 for index in range(len(bars))]
    query = '''STRATEGY_VERSION 1
SIDE BUY
RULE "Unlimited research entries" FOR SYMBOL "NABIL" {
  WHEN ltp > 0
  ORDER QUANTITY 1
  EXECUTE ON EVERY MATCH
}'''
    plan = parse_strategy_query(query)
    assert plan.rules[0].execution.frequency == "every_match"
    assert plan.rules[0].execution.max_times is None
    output = run_backtest(
        symbol="NABIL", query_text=query, start_date=date(2020, 1, 1), end_date=date(2021, 1, 4),
        bars=bars, entry_signals=entries, exit_signals=exits, min_holding_days=0,
        max_holding_days=60, stop_loss_pct=20, take_profit_pct=100,
        fee_pct=0, slippage_pct=0,
    )
    assert output["summary"]["total_trades"] > 100


def test_default_minimum_hold_delays_stop_until_day_five():
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    bars = [Bar(int((start + timedelta(days=index)).timestamp()), 100, 101, 90, 100, 10_000) for index in range(8)]
    query = '''STRATEGY_VERSION 1
SIDE BUY
RULE "Default holding window" FOR SYMBOL "NABIL" {
  WHEN ltp > 0
  ORDER QUANTITY 1
  EXECUTE ON EVERY MATCH
}'''
    output = run_backtest(
        symbol="NABIL", query_text=query, start_date=date(2025, 1, 1), end_date=date(2025, 1, 8),
        bars=bars, entry_signals=[True] + [False] * 7, stop_loss_pct=5,
        take_profit_pct=100, fee_pct=0, slippage_pct=0,
    )
    trade = output["trades"][0]
    assert trade["holding_days"] == 5
    assert trade["exit_reason"] == "stop_loss"


def test_buy_sell_cycles_are_linear_and_ignore_entries_while_holding():
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    bars = [
        Bar(int((start + timedelta(days=index)).timestamp()), 100, 101, 90, 100, 100_000)
        for index in range(28)
    ]
    query = '''STRATEGY_VERSION 1
SIDE BUY
RULE "Linear cycle" FOR SYMBOL "NABIL" {
  WHEN ltp > 0
  ORDER QUANTITY 10
  EXECUTE ON EVERY MATCH
}'''
    output = run_backtest(
        symbol="NABIL", query_text=query, start_date=date(2025, 1, 1), end_date=date(2025, 1, 28),
        bars=bars, entry_signals=[True] * len(bars), exit_signals=[True] * len(bars),
        min_holding_days=5, max_holding_days=90, stop_loss_pct=5, take_profit_pct=100,
        fee_pct=0, slippage_pct=0,
    )
    trades = output["trades"]
    assert len(trades) >= 3
    assert all(trade["holding_days"] >= 5 for trade in trades)
    assert all(trade["exit_reason"] == "stop_loss" for trade in trades[:-1])
    for previous, current in zip(trades, trades[1:]):
        assert current["entry_date"] > previous["exit_date"]


def test_maximum_holding_day_forces_exit_without_a_sell_signal():
    start = datetime(2025, 2, 1, tzinfo=timezone.utc)
    bars = [
        Bar(int((start + timedelta(days=index)).timestamp()), 100, 101, 99, 100, 100_000)
        for index in range(12)
    ]
    query = '''STRATEGY_VERSION 1
SIDE BUY
RULE "Maximum hold" FOR SYMBOL "NABIL" {
  WHEN ltp > 0
  ORDER QUANTITY 10
  EXECUTE ON EVERY MATCH
}'''
    output = run_backtest(
        symbol="NABIL", query_text=query, start_date=date(2025, 2, 1), end_date=date(2025, 2, 12),
        bars=bars, entry_signals=[True] + [False] * 11, exit_signals=[False] * 12,
        min_holding_days=5, max_holding_days=7, stop_loss_pct=50, take_profit_pct=100,
        fee_pct=0, slippage_pct=0,
    )
    assert output["trades"][0]["holding_days"] == 7
    assert output["trades"][0]["exit_reason"] == "max_holding_days"
