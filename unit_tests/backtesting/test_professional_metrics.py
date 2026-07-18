from datetime import date, timedelta
from types import SimpleNamespace

from utils.backtesting.professional import assign_robust_scores, fdr_benjamini_hochberg, wilson_interval


def test_wilson_interval_penalizes_thin_perfect_sample():
    thin_low, thin_high = wilson_interval(5, 5)
    strong_low, strong_high = wilson_interval(50, 50)
    assert thin_high == 100
    assert strong_high == 100
    assert thin_low < strong_low


def test_benjamini_hochberg_is_monotonic_by_p_value():
    adjusted = fdr_benjamini_hochberg([0.001, 0.02, 0.2, 0.8])
    assert adjusted == sorted(adjusted)
    assert all(0 <= value <= 1 for value in adjusted)


def test_robust_score_caps_weak_out_of_sample_results():
    rows = [
        {"oos_expectancy_pct": 8, "oos_return_pct": 50, "oos_sharpe_ratio": 5,
         "oos_max_drawdown_pct": 1, "walk_forward_profitable_pct": 100, "oos_trades": 30,
         "data_completeness_pct": 99, "p_value": .01, "warning_codes": []},
        {"oos_expectancy_pct": 6, "oos_return_pct": -1, "oos_sharpe_ratio": 3,
         "oos_max_drawdown_pct": 3, "walk_forward_profitable_pct": 100, "oos_trades": 30,
         "data_completeness_pct": 99, "p_value": .01, "warning_codes": []},
        {"oos_expectancy_pct": 7, "oos_return_pct": 30, "oos_sharpe_ratio": 4,
         "oos_max_drawdown_pct": 2, "walk_forward_profitable_pct": 100, "oos_trades": 3,
         "data_completeness_pct": 99, "p_value": .01, "warning_codes": []},
    ]
    assign_robust_scores(rows)
    assert rows[0]["robust_score"] > 49
    assert rows[1]["robust_score"] <= 49
    assert rows[2]["robust_score"] <= 39
