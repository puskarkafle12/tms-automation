import pytest

from utils.backtesting.v2_query import (
    ResultQueryError,
    compile_filters,
    compile_strong_buy_filters,
    compile_strong_buy_sorts,
)


def test_result_filters_are_parameterized_and_force_ordinary_shares():
    sql, params = compile_filters({"join": "and", "conditions": [
        {"field": "oos_trades", "operator": "gte", "value": 10},
        {"field": "symbol", "operator": "contains", "value": "NAB"},
    ]})
    assert "s.security_type = 'ordinary_share'" in sql
    assert ":filter_0" in sql and ":filter_1" in sql
    assert params == {"filter_0": 10.0, "filter_1": "%NAB%"}


def test_result_filters_allow_explicit_non_equity_universe():
    sql, _ = compile_filters({"join": "and", "conditions": []}, include_non_equities=True)
    assert sql == "TRUE"


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
