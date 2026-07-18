import pytest

from utils.backtesting.v2_query import ResultQueryError, compile_filters


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
