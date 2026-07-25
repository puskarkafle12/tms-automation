import pytest

from utils.backtesting.v2_query import (
    ResultQueryError,
    compile_filters,
    compile_result_sorts,
    compile_strong_buy_filters,
    compile_strong_buy_sorts,
    latest_completed_market_session,
    _strategy_planning_range,
    _with_ipo_trade_floor,
)


def test_result_filters_are_parameterized_and_force_ordinary_shares():
    sql, params = compile_filters({"join": "and", "conditions": [
        {"field": "oos_trades", "operator": "gte", "value": 10},
        {"field": "symbol", "operator": "contains", "value": "NAB"},
    ]})
    assert "s.security_type = 'ordinary_share'" in sql
    assert ":filter_0" in sql and ":filter_1" in sql
    assert params == {"filter_0": 10.0, "filter_1": "%NAB%"}


def test_ipo_results_always_exclude_zero_trade_simulations():
    assert _with_ipo_trade_floor("TRUE") == "r.total_trades > 0"
    assert _with_ipo_trade_floor("") == "r.total_trades > 0"
    assert _with_ipo_trade_floor("s.security_type = 'ordinary_share'") == (
        "(s.security_type = 'ordinary_share') AND r.total_trades > 0"
    )


def test_ipo_cache_counts_report_trade_and_zero_trade_totals():
    from utils.backtesting.v2_query import _ipo_cache_counts

    class _Result:
        def mappings(self):
            return self

        def one(self):
            return {
                "cached_total": 12,
                "trade_outcomes": 3,
                "zero_trade_outcomes": 9,
            }

    class _Session:
        def execute(self, _statement, _params=None):
            return _Result()

    assert _ipo_cache_counts(_Session(), run_id="run-1", owner_id="local") == {
        "cached_total": 12,
        "trade_outcomes": 3,
        "zero_trade_outcomes": 9,
    }


def test_csv_row_helper_serializes_nested_json():
    from utils.backtesting.v2_query import _csv_row_from_result
    row = _csv_row_from_result({
        "symbol": "SIPD", "total_trades": 1, "warning_codes": ["cached"],
        "current_evidence": {"reason": "ok"},
    })
    assert row["symbol"] == "SIPD"
    assert row["total_trades"] == 1
    assert row["warning_codes"] == '["cached"]'
    assert '"reason":"ok"' in row["current_evidence"]


def test_result_filters_allow_explicit_non_equity_universe():
    sql, _ = compile_filters({"join": "and", "conditions": []}, include_non_equities=True)
    assert sql == "TRUE"


def test_result_signal_and_holding_configuration_filters_are_validated():
    sql, params = compile_filters({"join": "and", "conditions": [
        {"field": "current_signal_status", "operator": "eq", "value": "strong_buy"},
        {"field": "min_holding_days", "operator": "eq", "value": 5},
        {"field": "max_holding_days", "operator": "lte", "value": 90},
    ]})
    assert "r.current_signal_status = :filter_0" in sql
    assert "r.assumptions->>'min_holding_days'" in sql
    assert params == {"filter_0": "strong_buy", "filter_1": 5.0, "filter_2": 90.0}


def test_result_filters_reject_unknown_fields_and_sql_payloads():
    with pytest.raises(ResultQueryError):
        compile_filters({"field": "drop table backtest_results", "operator": "eq", "value": 1})


def test_nested_or_filters_are_supported():
    sql, params = compile_filters({"join": "or", "conditions": [
        {"field": "sector", "operator": "eq", "value": "Bank"},
        {"field": "robust_score", "operator": "gte", "value": 70},
    ]})
    assert " OR " in sql
    assert params["filter_0"] == "Bank"


def test_results_support_validated_multi_column_sorting():
    inner, outer, sorts = compile_result_sorts({"sorts": [
        {"field": "robust_score", "direction": "desc"},
        {"field": "oos_return_pct", "direction": "desc"},
        {"field": "max_drawdown_pct", "direction": "asc"},
    ]})
    assert inner.startswith("r.robust_score DESC NULLS LAST,r.oos_return_pct DESC NULLS LAST,r.max_drawdown_pct ASC NULLS LAST")
    assert outer.startswith("robust_score DESC NULLS LAST,oos_return_pct DESC NULLS LAST,max_drawdown_pct ASC NULLS LAST")
    assert sorts[2] == {"field": "max_drawdown_pct", "direction": "asc"}


def test_result_sorting_rejects_unknown_and_duplicate_fields():
    with pytest.raises(ResultQueryError):
        compile_result_sorts({"sorts": [{"field": "drop table runs", "direction": "desc"}]})
    with pytest.raises(ResultQueryError):
        compile_result_sorts({"sorts": [
            {"field": "win_rate_pct", "direction": "desc"},
            {"field": "win_rate_pct", "direction": "asc"},
        ]})


def test_recommendations_support_validated_multi_column_sorting():
    sql, sorts = compile_strong_buy_sorts({"sorts": [
        {"field": "win_rate_pct", "direction": "desc"},
        {"field": "net_profit", "direction": "asc"},
        {"field": "average_holding_days", "direction": "desc"},
    ]})
    assert sql == "win_rate_pct DESC NULLS LAST,net_profit ASC NULLS LAST,average_holding_days DESC NULLS LAST"
    assert sorts[1] == {"field": "net_profit", "direction": "asc"}


def test_recommendation_sorting_rejects_unknown_or_duplicate_fields():
    with pytest.raises(ResultQueryError):
        compile_strong_buy_sorts({"sorts": [{"field": "drop table runs", "direction": "desc"}]})
    with pytest.raises(ResultQueryError):
        compile_strong_buy_sorts({"sorts": [
            {"field": "win_rate_pct", "direction": "desc"},
            {"field": "win_rate_pct", "direction": "asc"},
        ]})


def test_recommendations_compile_multiple_parameterized_filters():
    params = {}
    sql, filters = compile_strong_buy_filters([
        {"field": "recommendation_score", "operator": "gte", "value": "70"},
        {"field": "max_drawdown_pct", "operator": "lte", "value": 25},
        {"field": "sector", "operator": "contains", "value": "Bank"},
    ], params, "score_expression")
    assert "(score_expression) >= :advanced_filter_0" in sql
    assert "r.max_drawdown_pct <= :advanced_filter_1" in sql
    assert "s.sector ILIKE :advanced_filter_2" in sql
    assert params == {"advanced_filter_0": 70.0, "advanced_filter_1": 25.0, "advanced_filter_2": "%Bank%"}
    assert filters[0] == {"field": "recommendation_score", "operator": "gte", "value": 70.0}


def test_recommendation_filters_reject_unsafe_or_invalid_conditions():
    with pytest.raises(ResultQueryError):
        compile_strong_buy_filters([
            {"field": "drop table backtest_results", "operator": "eq", "value": 1},
        ], {}, "score_expression")
    with pytest.raises(ResultQueryError):
        compile_strong_buy_filters([
            {"field": "win_rate_pct", "operator": "contains", "value": 70},
        ], {}, "score_expression")
    with pytest.raises(ResultQueryError):
        compile_strong_buy_filters([
            {"field": "sector", "operator": "gte", "value": "Bank"},
        ], {}, "score_expression")


def test_latest_market_session_uses_index_friendly_top_row_lookup():
    class ScalarResult:
        def scalar(self):
            return "2026-07-24"

    class Session:
        def execute(self, statement):
            sql = str(statement)
            assert "ORDER BY session_date DESC" in sql
            assert "LIMIT 1" in sql
            assert "MAX(" not in sql
            return ScalarResult()

    assert latest_completed_market_session(Session()) == "2026-07-24"


def test_planning_range_uses_selected_exit_level_and_atr_stop():
    result = _strategy_planning_range({
        "current_signal_status": "buy",
        "ltp": 100,
        "current_evidence": {"latest_values": {"technical_atr_percent": 4}},
        "assumptions": {
            "stop_loss_pct": 8,
            "take_profit_pct": 15,
            "atr_stop_multiple": 2,
            "exit_rule_id": "sr_resistance_rejection_exit",
            "protection_latest_values": {
                "technical_atr_14": 3,
                "technical_sr_resistance_lower": 110,
                "technical_sr_resistance_upper": 112,
            },
        },
    })
    assert result["protective_stop"] == 94
    assert result["sell_zone_low"] == 110
    assert result["sell_zone_high"] == 112
    assert result["planning_range_basis"]["sell_zone_basis"] == "Current causal resistance zone"
