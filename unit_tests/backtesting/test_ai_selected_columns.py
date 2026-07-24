import json

from utils.backtesting.ai_analysis import compile_display_query, parse_plan


def test_ai_plan_returns_validated_selected_sql_columns():
    plan = parse_plan(json.dumps({
        "filters": [{"field": "total_trades", "operator": "gte", "value": 16}],
        "columns": ["symbol", "preset_name", "win_rate_pct", "not_a_column", "total_trades"],
        "sort_by": "win_rate_pct",
        "sort_direction": "desc",
        "explanation": "Show the requested evidence.",
    }), ordinary_only=False)

    assert plan["columns"] == ["symbol", "preset_name", "win_rate_pct", "total_trades"]
    sql = compile_display_query(plan)
    assert sql.startswith("SELECT symbol, preset_name, win_rate_pct, total_trades")
    assert "SELECT *" not in sql

