from datetime import date, datetime, timezone

import pytest

from utils.backtesting.service import BacktestError, Bar, _historical_rows, fetch_historical_bars, run_backtest
from utils.backtesting.presets import build_preset_query, get_backtest_presets
from utils.strategy_builder.strategy_parser import parse_strategy_query


def _bar(day: int, open_price: float, high: float, low: float, close: float) -> Bar:
    timestamp = int(datetime(2025, 1, day, tzinfo=timezone.utc).timestamp())
    return Bar(timestamp, open_price, high, low, close, 1000)


def _query(condition: str = "ltp <= 100") -> str:
    return f'''STRATEGY_VERSION 1
SIDE BUY
RULE "Test entry" FOR SYMBOL "NABIL" {{
  WHEN {condition}
  ORDER QUANTITY 10
  EXECUTE MAX 100 TIMES PER SYMBOL
}}'''


def test_backtest_enters_next_open_and_reports_winning_trade():
    bars = [
        _bar(1, 105, 106, 89, 90),
        _bar(2, 92, 103, 91, 101),
        _bar(3, 101, 102, 100, 101),
    ]

    result = run_backtest(
        symbol="NABIL",
        query_text=_query(),
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 3),
        initial_capital=100000,
        stop_loss_pct=5,
        take_profit_pct=10,
        max_holding_days=20,
        fee_pct=0,
        slippage_pct=0,
        bars=bars,
    )

    assert result["summary"]["total_trades"] == 1
    assert result["summary"]["wins"] == 1
    assert result["summary"]["win_rate_pct"] == 100
    trade = result["trades"][0]
    assert trade["signal_date"] == "2025-01-01"
    assert trade["entry_date"] == "2025-01-02"
    assert trade["entry_price"] == 92
    assert trade["exit_price"] == pytest.approx(101.2)
    assert trade["exit_reason"] == "take_profit"


def test_backtest_rejects_live_only_fields_with_clear_error():
    with pytest.raises(BacktestError, match="live-only data"):
        run_backtest(
            symbol="NABIL",
            query_text=_query("best_bid > 100"),
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 2),
            bars=[_bar(1, 100, 101, 99, 100), _bar(2, 100, 101, 99, 100)],
        )


def test_backtest_rejects_symbol_not_present_in_query():
    with pytest.raises(BacktestError, match="does not contain a rule"):
        run_backtest(
            symbol="EBL",
            query_text=_query(),
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 2),
            bars=[_bar(1, 100, 101, 99, 100), _bar(2, 100, 101, 99, 100)],
        )


def test_all_presets_compile_for_nepse_symbol():
    presets = get_backtest_presets()
    assert len(presets) == 140
    assert len({preset["id"] for preset in presets}) == 140
    for preset in presets:
        query = build_preset_query(preset, "NABIL")
        plan = parse_strategy_query(query)
        assert plan.rules[0].symbols == ["NABIL"]
        assert 'CHARGE_MODEL "nepse_equity"' in query
        assert f'STOP_LOSS_PCT {preset["defaults"]["stop_loss_pct"]:g}' in query
        assert f'TAKE_PROFIT_PCT {preset["defaults"]["take_profit_pct"]:g}' in query
        assert f'MAX_HOLDING_DAYS {preset["defaults"]["max_holding_days"]}' in query
        assert preset["exit_condition"]


def test_preset_query_embeds_run_holding_and_cost_overrides_for_replay_and_promotion():
    query = build_preset_query(
        get_backtest_presets()[-1], "NABIL",
        backtest_config={"min_holding_days": 7, "max_holding_days": 42, "slippage_pct": .25},
    )
    plan = parse_strategy_query(query)
    assert plan.backtest is not None
    assert plan.backtest.charge_model == "nepse_equity"
    assert plan.backtest.min_holding_days == 7
    assert plan.backtest.max_holding_days == 42
    assert plan.backtest.slippage_pct == .25


def test_minimum_holding_days_delays_target_but_not_run_reproducibility():
    bars = [
        _bar(1, 105, 106, 89, 90),
        _bar(2, 92, 103, 91, 101),
        _bar(3, 101, 103, 100, 102),
        _bar(4, 102, 104, 101, 103),
    ]
    result = run_backtest(
        symbol="NABIL", query_text=_query(), start_date=date(2025, 1, 1), end_date=date(2025, 1, 4),
        initial_capital=100000, stop_loss_pct=5, take_profit_pct=10,
        min_holding_days=2, max_holding_days=20, fee_pct=0, slippage_pct=0, bars=bars,
    )
    assert result["trades"][0]["exit_date"] == "2025-01-04"
    assert result["trades"][0]["holding_days"] == 2
    assert result["assumptions"]["min_holding_days"] == 2
    assert result["assumptions"]["max_holding_days"] == 20


def test_backtest_language_configuration_overrides_api_defaults():
    query = '''STRATEGY_VERSION 1
SIDE BUY
BACKTEST {
  INITIAL_CAPITAL 50000
  CHARGE_MODEL "legacy_flat"
  FEE_PCT 0
  SLIPPAGE_PCT 0
  STOP_LOSS_PCT 5
  TAKE_PROFIT_PCT 10
  MAX_HOLDING_DAYS 20
  POSITION_SIZE_PCT 50
  MAX_VOLUME_PARTICIPATION_PCT 100
  DATA_SOURCE "auto"
}
RULE "Language config" FOR SYMBOL "NABIL" {
  WHEN ltp <= 100
  ORDER PERCENT_OF_AVAILABLE_CASH 100
  EXECUTE MAX 10 TIMES PER SYMBOL
}'''
    result = run_backtest(
        symbol="NABIL", query_text=query,
        start_date=date(2025, 1, 1), end_date=date(2025, 1, 3),
        initial_capital=999999, bars=[
            _bar(1, 105, 106, 89, 90),
            _bar(2, 92, 103, 91, 101),
            _bar(3, 101, 102, 100, 101),
        ],
    )
    assert result["summary"]["initial_capital"] == 50000
    assert result["trades"][0]["quantity"] == 271


def test_full_history_fetch_uses_one_upstream_request(monkeypatch):
    calls = []
    payload = {
        "s": "ok",
        "t": [1514808000, 1751371200],
        "o": [100, 120], "h": [110, 130], "l": [95, 115],
        "c": [105, 125], "v": [1000, 2000],
    }

    class Response:
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def read(self):
            import json
            return json.dumps(payload).encode()

    def fake_open(request, timeout):
        calls.append((request.full_url, timeout))
        return Response()

    monkeypatch.setattr("utils.backtesting.service.urlopen", fake_open)
    bars = fetch_historical_bars("NABIL", date(2018, 1, 1), date(2025, 7, 2))
    assert len(bars) == 2
    assert len(calls) == 1
    assert "rangeStartDate" in calls[0][0]


def test_compact_backtest_reuses_prepared_indicators():
    bars = [
        _bar(1, 105, 106, 89, 90),
        _bar(2, 92, 103, 91, 101),
        _bar(3, 101, 102, 100, 101),
    ]
    rows = list(_historical_rows("NABIL", bars))
    result = run_backtest(
        symbol="NABIL", query_text=_query(), start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 3), fee_pct=0, slippage_pct=0,
        stop_loss_pct=5, take_profit_pct=10, bars=bars,
        prepared_rows=rows, compact=True,
    )
    assert result["summary"]["total_trades"] == 1
    assert result["bars"] == []
    assert result["trades"] == []
    assert result["equity_curve"] == []


def test_partial_batch_result_is_sorted_before_full_scan_finishes():
    from utils.backtesting.batch import build_batch_result

    presets = get_backtest_presets()[:2]
    outputs = [{
        "symbol": "AAA", "error": None, "results": [
            {"symbol": "AAA", "preset_id": presets[0]["id"], "preset_name": presets[0]["name"],
             "category": presets[0]["category"], "bars": 100, "total_trades": 20,
             "win_rate_pct": 55, "confidence_score": 49.2, "net_return_pct": 10,
             "max_drawdown_pct": 5, "sharpe_ratio": 1, "profit_factor": 1.5,
             "expectancy_pct": 1, "alpha_vs_benchmark_pct": 2, "sample_quality": "strong"},
            {"symbol": "AAA", "preset_id": presets[1]["id"], "preset_name": presets[1]["name"],
             "category": presets[1]["category"], "bars": 100, "total_trades": 5,
             "win_rate_pct": 80, "confidence_score": 56.6, "net_return_pct": 4,
             "max_drawdown_pct": 3, "sharpe_ratio": .5, "profit_factor": 1.2,
             "expectancy_pct": .5, "alpha_vs_benchmark_pct": 1, "sample_quality": "moderate"},
        ],
    }]
    partial = build_batch_result(
        symbol_outputs=outputs, selected_presets=presets,
        data_source="merolagani", symbols_requested=644, workers=8,
    )
    assert partial["symbols_requested"] == 644
    assert partial["symbols_completed"] == 1
    assert partial["rankings"][0]["win_rate_pct"] == 80
    assert partial["stock_summary"][0]["best_preset_name"] == presets[1]["name"]
