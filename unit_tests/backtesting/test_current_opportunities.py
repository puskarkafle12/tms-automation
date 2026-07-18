from utils.backtesting.current_opportunities import condition_progress, qualifies_default, reliability_score
from utils.backtesting.presets import get_backtest_presets
from utils.backtesting.current_opportunities import evaluate_latest_completed_signal


def _summary(**overrides):
    value = {
        "total_trades": 48, "wins": 29, "losses": 19, "win_rate_pct": 60.42,
        "net_return_pct": 120, "profit_factor": 1.8, "sharpe_ratio": 1.19,
        "max_drawdown_pct": 20, "gross_profit": 20000, "largest_winning_trade": 2000,
    }
    value.update(overrides)
    return value


def test_reliability_score_is_transparent_and_bounded():
    result = reliability_score(_summary(), confidence_score=80, technical_score=75,
                               liquidity_score=70, fresh=True, indicators_complete=True)
    assert 0 <= result["score"] <= 100
    assert set(result["components"]) == {
        "historical_win_rate", "completed_trades", "confidence", "net_return",
        "profit_factor", "sharpe", "drawdown_protection",
        "current_technical_confirmation", "liquidity", "data_freshness",
    }


def test_default_qualification_rejects_thin_drawdown_and_stale_data():
    assert qualifies_default(_summary(), active=True, fresh=True, indicators_complete=True, liquidity_score=70)
    assert not qualifies_default(_summary(total_trades=19), active=True, fresh=True, indicators_complete=True, liquidity_score=70)
    assert not qualifies_default(_summary(max_drawdown_pct=30), active=True, fresh=True, indicators_complete=True, liquidity_score=70)
    assert not qualifies_default(_summary(), active=True, fresh=False, indicators_complete=True, liquidity_score=70)
    assert not qualifies_default(_summary(), active=True, fresh=True, indicators_complete=False, liquidity_score=70)


def test_latest_completed_row_generates_condition_evidence():
    preset = next(item for item in get_backtest_presets() if item["id"] == "rsi_momentum_50")
    rows = [
        {"symbol": "TEST", "ltp": 100, "change_percent": -1, "technical_rsi_14": 40,
         "last_traded_at": "2026-01-01T15:00:00+05:45", "received_at": "2026-01-01T15:00:00+05:45"},
        {"symbol": "TEST", "ltp": 105, "change_percent": 5, "technical_rsi_14": 60,
         "last_traded_at": "2026-01-02T15:00:00+05:45", "received_at": "2026-01-02T15:00:00+05:45"},
    ]
    result = evaluate_latest_completed_signal(preset, "TEST", rows)
    assert result["active"] is True
    assert result["failed_conditions"] == []
    assert result["conditions"]


def test_inactive_latest_condition_is_not_a_buy():
    preset = next(item for item in get_backtest_presets() if item["id"] == "rsi_momentum_50")
    rows = [
        {"symbol": "TEST", "ltp": 100, "change_percent": 1, "technical_rsi_14": 55,
         "last_traded_at": "2026-01-01T15:00:00+05:45", "received_at": "2026-01-01T15:00:00+05:45"},
        {"symbol": "TEST", "ltp": 99, "change_percent": -1, "technical_rsi_14": 45,
         "last_traded_at": "2026-01-02T15:00:00+05:45", "received_at": "2026-01-02T15:00:00+05:45"},
    ]
    result = evaluate_latest_completed_signal(preset, "TEST", rows)
    assert result["active"] is False
    assert result["failed_conditions"]


def test_condition_progress_marks_readiness_without_predicting_a_signal():
    result = condition_progress([
        {"matched": True}, {"matched": True}, {"matched": False},
    ])
    assert result == {
        "conditions_passed": 2,
        "conditions_total": 3,
        "condition_progress_pct": 66.67,
        "near_trigger": True,
    }
    assert condition_progress([{"matched": True}, {"matched": True}])["near_trigger"] is False
