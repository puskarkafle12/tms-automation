from utils.backtesting.ai_analysis import compile_display_query, execute_plan, parse_plan


def test_ai_plan_is_validated_defaults_to_ordinary_shares_and_top_ten():
    plan = parse_plan(
        '{"filters":[{"field":"total_trades","operator":"gte","value":20},'
        '{"field":"not_a_field","operator":"gt","value":1}],'
        '"sort_by":"confidence_score","sort_direction":"desc","explanation":"Robust samples first."}'
    )
    assert {item["field"] for item in plan["filters"]} == {"total_trades", "security_type"}
    rows = [
        {"symbol": f"S{index}", "security_type": "ordinary_share", "total_trades": 25, "confidence_score": index}
        for index in range(15)
    ] + [{"symbol": "FUND", "security_type": "mutual_fund", "total_trades": 50, "confidence_score": 100}]
    result = execute_plan(rows, plan)
    assert len(result) == 10
    assert result[0]["symbol"] == "S14"
    assert all(item["security_type"] == "ordinary_share" for item in result)
    query = compile_display_query(plan)
    assert "security_type = 'ordinary_share'" in query
    assert "ORDER BY confidence_score DESC" in query
    assert query.endswith("LIMIT 10;")


def test_all_instruments_plan_does_not_force_equity_filter():
    plan = parse_plan('{"filters":[],"sort_by":"win_rate_pct","sort_direction":"desc"}', ordinary_only=False)
    assert plan["filters"] == []


def test_manual_filters_override_ai_field_and_support_ranges_and_text():
    plan = parse_plan(
        '{"filters":[{"field":"ltp","operator":"gte","value":5000}],"sort_by":"win_rate_pct"}',
        extra_filters=[
            {"field": "ltp", "operator": "gte", "value": 100},
            {"field": "ltp", "operator": "lte", "value": 500},
            {"field": "sector", "operator": "contains", "value": "bank"},
        ],
    )
    assert [item for item in plan["filters"] if item["field"] == "ltp"] == [
        {"field": "ltp", "operator": "gte", "value": 100.0},
        {"field": "ltp", "operator": "lte", "value": 500.0},
    ]
    results = execute_plan([
        {"symbol": "A", "security_type": "ordinary_share", "sector": "Commercial Banks", "ltp": 250, "win_rate_pct": 60},
        {"symbol": "B", "security_type": "ordinary_share", "sector": "Hydropower", "ltp": 250, "win_rate_pct": 90},
        {"symbol": "C", "security_type": "ordinary_share", "sector": "Commercial Banks", "ltp": 700, "win_rate_pct": 80},
    ], plan)
    assert [item["symbol"] for item in results] == ["A"]
