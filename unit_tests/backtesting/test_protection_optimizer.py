from utils.backtesting.protection_optimizer import (
    STOP_CONFIGURATIONS,
    choose_protection_champion,
    protection_score,
)
from utils.backtesting.service import Bar
from utils.backtesting.presets import get_backtest_presets


def test_score_penalizes_thin_high_win_rate_and_large_drawdown():
    lucky = {"total_trades": 2, "win_rate_pct": 100, "expectancy_pct": 8, "profit_factor": 4, "net_return_pct": 16, "max_drawdown_pct": 20}
    robust = {"total_trades": 18, "win_rate_pct": 61, "expectancy_pct": 3, "profit_factor": 1.8, "net_return_pct": 22, "max_drawdown_pct": 7}
    assert protection_score(robust) > protection_score(lucky)


def test_two_stage_search_returns_one_auditable_champion():
    calls = []

    def evaluate(exit_rule_id, _condition, stop):
        calls.append((exit_rule_id, stop["id"]))
        return {
            "total_trades": 18,
            "win_rate_pct": 65 if exit_rule_id == "trend" else 55,
            "expectancy_pct": 4 if stop["id"] == "fixed_balanced_6" else 2,
            "profit_factor": 2 if exit_rule_id == "trend" else 1.2,
            "net_return_pct": 20,
            "max_drawdown_pct": 6,
            "sharpe_ratio": 1.1,
        }

    result = choose_protection_champion(
        [("trend", "trend condition"), ("flow", "flow condition")],
        evaluate,
        finalist_exit_count=1,
    )
    assert result["champion"]["exit_rule_id"] == "trend"
    assert result["champion"]["stop"]["id"] == "fixed_balanced_6"
    assert result["sell_rules_tested"] == 2
    assert result["stop_methods_tested"] == len(STOP_CONFIGURATIONS)
    assert result["total_evaluations"] == 7


def test_professional_stock_run_persists_only_selected_protection(monkeypatch):
    from datetime import date, datetime, timedelta, timezone
    from utils.backtesting.batch import _run_symbol_task
    from utils.backtesting import accelerated, strategy_discovery

    start = date(2025, 1, 1)
    bars = []
    for index in range(90):
        day = start + timedelta(days=index)
        close = 100 + index * .35 + (index % 5)
        bars.append(Bar(
            int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp()),
            close - .5, close + 1.5, close - 1.5, close, 100_000,
        ))
    monkeypatch.setattr("utils.backtesting.batch.fetch_historical_bars", lambda *_args: bars)
    monkeypatch.setattr(
        accelerated,
        "compile_preset_signals",
        lambda _preset_id, rows, trigger_on_cross=True: [index % 4 == 0 for index in range(len(rows))],
    )
    monkeypatch.setattr(
        strategy_discovery,
        "compile_discovery_exit_signals",
        lambda preset, rows: [
            index % (5 if preset.get("exit_rule_id") == "trend_breakdown_exit" else 7) == 0
            for index in range(len(rows))
        ],
    )
    preset = next(item for item in get_backtest_presets() if item["id"] == "rsi_momentum_50")
    output = _run_symbol_task({
        "symbol": "NABIL",
        "start_date": start,
        "end_date": start + timedelta(days=89),
        "data_source": "merolagani",
        "presets": [preset],
        "settings": {
            "professional": True,
            "initial_capital": 100_000,
            "fee_pct": 0,
            "fixed_fee": 0,
            "slippage_pct": 0,
            "charge_model": "legacy_flat",
            "investor_type": "individual",
            "apply_cgt": False,
            "dp_charge": 0,
            "position_size_pct": 100,
            "trailing_stop_pct": None,
            "max_volume_participation_pct": 100,
            "risk_free_rate_pct": 0,
            "min_holding_days": 0,
            "max_holding_days": 20,
        },
    })
    assert output["error"] is None
    assert len(output["results"]) == 1
    assumptions = output["results"][0]["assumptions"]
    assert assumptions["protection_optimization"]["total_evaluations"] == 38
    assert assumptions["exit_rule_id"]
    assert assumptions["sell_strategy_query"]


def test_atr_stop_uses_entry_session_volatility():
    from datetime import date, datetime, timezone
    from utils.backtesting.service import _historical_rows, run_backtest

    def bar(day, open_price, high, low, close):
        return Bar(
            int(datetime(2025, 1, day, tzinfo=timezone.utc).timestamp()),
            open_price, high, low, close, 100_000,
        )

    bars = [
        bar(1, 105, 106, 89, 90),
        bar(2, 100, 101, 95, 100),
        bar(3, 100, 101, 99, 100),
    ]
    rows = list(_historical_rows("NABIL", bars))
    for row in rows:
        row["technical_atr_14"] = 2
    query = '''STRATEGY_VERSION 1
SIDE BUY
RULE "ATR protection" FOR SYMBOL "NABIL" {
  WHEN ltp <= 90
  ORDER QUANTITY 10
  EXECUTE MAX 1 TIMES PER SYMBOL
}'''
    result = run_backtest(
        symbol="NABIL",
        query_text=query,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 3),
        bars=bars,
        prepared_rows=rows,
        initial_capital=100_000,
        fee_pct=0,
        slippage_pct=0,
        min_holding_days=0,
        max_holding_days=20,
        stop_loss_pct=8,
        take_profit_pct=20,
        atr_stop_multiple=2,
    )
    assert result["trades"][0]["exit_reason"] == "atr_stop"
    assert result["trades"][0]["exit_price"] == 96
