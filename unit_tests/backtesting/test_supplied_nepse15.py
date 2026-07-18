from dataclasses import dataclass
from datetime import date

from utils.backtesting.accelerated import compile_preset_exit_signals, compile_preset_signals
from utils.backtesting.batch import _run_symbol_task
from utils.backtesting.presets import build_preset_query, get_backtest_presets
from utils.backtesting.service import Bar, run_backtest
from utils.strategy_builder.strategy_parser import parse_strategy_query
from utils.technical_indicators import calculate_indicator_rows


@dataclass
class _IndicatorBar:
    open: float
    high: float
    low: float
    close: float
    volume: float


def _market_rows(count: int = 340):
    indicator_bars = []
    bars = []
    for index in range(count):
        close = 100 + index * .22 + ((index % 11) - 5) * .45
        open_price = close - (.35 if index % 3 else -.2)
        item = _IndicatorBar(
            open_price, max(open_price, close) + 1.1,
            min(open_price, close) - 1.0, close,
            35_000 + (index % 17) * 2_000,
        )
        indicator_bars.append(item)
        bars.append(Bar(
            timestamp=1_704_067_200 + index * 86_400,
            open=item.open, high=item.high, low=item.low, close=item.close,
            volume=item.volume, extras={},
        ))
    indicator_rows = calculate_indicator_rows(indicator_bars)
    rows = []
    for index, (bar, indicators) in enumerate(zip(bars, indicator_rows)):
        previous = bars[index - 1].close if index else bar.open
        rows.append({
            "symbol": "NABIL", "ltp": bar.close, "open": bar.open,
            "high": bar.high, "low": bar.low, "volume": bar.volume,
            "previous_close": previous, "change": bar.close - previous,
            "change_percent": (bar.close / previous - 1) * 100,
            "position_in_52_week_range_percent": 75, **indicators,
        })
    return indicator_bars, bars, rows


def test_supplied_catalog_is_unique_and_all_queries_compile():
    catalog = get_backtest_presets()
    supplied = [item for item in catalog if item["family"] == "user_supplied_nepse15"]
    assert len(supplied) == 15
    assert len({item["source_hash"] for item in catalog}) == len(catalog)
    assert sorted(
        item["team_recommended_priority"] for item in supplied
        if item["team_recommended_priority"] is not None
    ) == [1, 2, 3, 4, 5]
    for preset in supplied:
        plan = parse_strategy_query(build_preset_query(preset, "NABIL"))
        assert plan.rules[0].order.mode == "risk_percent"
        assert plan.rules[0].order.value == 1
        assert plan.backtest.min_holding_days == 5
        assert plan.backtest.max_holding_days == preset["defaults"]["max_holding_days"]


def test_all_supplied_presets_execute_independently_with_condition_exits():
    _, bars, rows = _market_rows()
    supplied = [item for item in get_backtest_presets() if item["family"] == "user_supplied_nepse15"]
    for preset in supplied:
        entries = compile_preset_signals(preset["id"], rows)
        exits = compile_preset_exit_signals(preset["id"], rows)
        assert len(entries) == len(bars)
        assert len(exits) == len(bars)
        output = run_backtest(
            symbol="NABIL", query_text=build_preset_query(preset, "NABIL"),
            start_date=date.fromisoformat(bars[0].day), end_date=date.fromisoformat(bars[-1].day),
            bars=bars, prepared_rows=rows, entry_signals=entries, exit_signals=exits,
            compact=True,
        )
        assert output["assumptions"]["min_holding_days"] == 5
        assert output["period"]["bars"] == len(bars)


def test_supplied_setup_fields_do_not_change_when_future_bars_are_added():
    indicator_bars, _, rows = _market_rows()
    prefix_rows = calculate_indicator_rows(indicator_bars[:300])
    for index in range(1, 16):
        assert prefix_rows[-1][f"technical_nepse15_entry_{index}"] == rows[299][f"technical_nepse15_entry_{index}"]
        assert prefix_rows[-1][f"technical_nepse15_exit_{index}"] == rows[299][f"technical_nepse15_exit_{index}"]


def test_global_holding_window_caps_but_does_not_replace_strategy_holding(monkeypatch):
    _, bars, _ = _market_rows()
    supplied = [item for item in get_backtest_presets() if item["family"] == "user_supplied_nepse15"]
    monkeypatch.setattr("utils.backtesting.batch.fetch_historical_bars", lambda *_args, **_kwargs: bars)
    output = _run_symbol_task({
        "symbol": "NABIL", "start_date": date.fromisoformat(bars[0].day),
        "end_date": date.fromisoformat(bars[-1].day), "data_source": "merolagani",
        "presets": supplied, "settings": {
            "professional": True, "initial_capital": 100000, "fee_pct": .4,
            "fixed_fee": 0, "charge_model": "nepse_equity", "investor_type": "individual",
            "apply_cgt": True, "dp_charge": 25, "slippage_pct": .1,
            "position_size_pct": 100, "min_holding_days": 5, "max_holding_days": 90,
            "trailing_stop_pct": None, "max_volume_participation_pct": 10,
            "risk_free_rate_pct": 4,
        },
    })
    assert not output.get("error")
    actual = {row["preset_id"]: row["assumptions"]["max_holding_days"] for row in output["results"]}
    assert actual == {item["id"]: item["defaults"]["max_holding_days"] for item in supplied}
