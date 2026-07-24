from utils.backtesting.result_retention import (
    RETENTION_POLICY_VERSION,
    is_retained_result,
    is_revalidation_candidate,
)
from utils.backtesting.result_artifacts import rejection_key


def test_retention_uses_standard_or_high_win_evidence_thresholds():
    assert RETENTION_POLICY_VERSION == "trades-16-win-50-or-trades-9-win-60-v2"
    assert is_retained_result({"total_trades": 16, "win_rate_pct": 50})
    assert is_retained_result({"total_trades": 9, "win_rate_pct": 60})
    assert is_retained_result({"total_trades": 100, "win_rate_pct": 59.99})
    assert not is_retained_result({"total_trades": 15, "win_rate_pct": 59.99})
    assert not is_retained_result({"total_trades": 8, "win_rate_pct": 100})


def test_retention_rejects_missing_or_invalid_metrics():
    assert not is_retained_result({})
    assert not is_retained_result({"total_trades": "invalid", "win_rate_pct": 80})


def test_only_borderline_rejections_are_monthly_revalidation_candidates():
    assert is_revalidation_candidate({"total_trades": 9, "win_rate_pct": 35})
    assert is_revalidation_candidate({"total_trades": 15, "win_rate_pct": 59.99})
    assert not is_revalidation_candidate({"total_trades": 8, "win_rate_pct": 90})
    assert not is_revalidation_candidate({"total_trades": 100, "win_rate_pct": 34.99})
    assert not is_revalidation_candidate({"total_trades": 16, "win_rate_pct": 50})


def test_rejection_identity_does_not_change_with_backtest_dates():
    preset = {"id": "strategy-1", "version": 1, "defaults": {}, "condition": {"field": "rsi"}}
    common = {"initial_capital": 100000}
    first = rejection_key(
        symbol="NABIL", preset=preset,
        config={**common, "start_date": "2018-01-01", "end_date": "2025-01-01"},
        engine_version="engine-v1", indicator_version="indicator-v1",
    )
    later = rejection_key(
        symbol="NABIL", preset=preset,
        config={**common, "start_date": "2020-01-01", "end_date": "2026-01-01"},
        engine_version="engine-v1", indicator_version="indicator-v1",
    )
    assert first == later
