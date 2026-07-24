"""Validated AI query plans over persisted backtest combinations."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

NUMERIC_FIELDS = {
    "total_trades", "win_rate_pct", "confidence_score", "net_return_pct",
    "max_drawdown_pct", "sharpe_ratio", "profit_factor", "expectancy_pct",
    "alpha_vs_benchmark_pct", "technical_signal_score", "technical_buy_score",
    "technical_sell_score", "listing_age_days", "latest_volume", "ltp", "bars",
    "robust_score", "oos_trades", "oos_win_rate_pct", "oos_return_pct",
    "oos_expectancy_pct", "oos_sharpe_ratio", "oos_max_drawdown_pct",
    "walk_forward_profitable_pct", "data_completeness_pct", "liquidity_score",
    "median_volume_20", "average_turnover_20", "min_holding_days", "max_holding_days",
    "stop_loss_pct", "take_profit_pct", "trailing_stop_pct", "slippage_pct_each_side",
}
TEXT_FIELDS = {
    "symbol", "preset_id", "preset_name", "category", "sample_quality",
    "technical_signal", "security_type", "sector", "preset_family", "recommendation_status",
    "current_signal_status",
}
ALLOWED_FIELDS = NUMERIC_FIELDS | TEXT_FIELDS
ALLOWED_OPERATORS = {"eq", "neq", "gt", "gte", "lt", "lte", "contains"}
DEFAULT_OUTPUT_COLUMNS = [
    "symbol", "preset_name", "current_signal_status", "robust_score",
    "win_rate_pct", "total_trades", "net_return_pct", "max_drawdown_pct",
]


def build_plan_prompt(message: str, *, symbol: str | None = None) -> tuple[str, str]:
    system = f"""You translate a trader's question into a safe query plan over stored backtest rows.
Return JSON only with this shape:
{{"filters":[{{"field":"total_trades","operator":"gte","value":20}}],"columns":["symbol","preset_name","total_trades","win_rate_pct"],"sort_by":"confidence_score","sort_direction":"desc","explanation":"One concise explanation of why these filters, selected columns, and ranking answer the request."}}
Allowed numeric fields: {', '.join(sorted(NUMERIC_FIELDS))}.
Allowed text fields: {', '.join(sorted(TEXT_FIELDS))}.
Operators: eq, neq, gt, gte, lt, lte, contains. Sort direction: asc or desc.
Use robust_score as the default ranking; do not rank by win rate alone unless explicitly requested.
Choose practical thresholds likely to return results; preserve explicit numeric limits from the trader.
Choose 3 to 10 output columns from the allowed fields. Include symbol and preset_name unless the trader explicitly asks otherwise.
The server always limits output to 10 and validates every field. Do not include SQL or extra prose."""
    scoped = f" Analyze only symbol {symbol}." if symbol else ""
    return system, f"Trader request: {message.strip()}.{scoped}"


def parse_plan(
    raw: str, *, symbol: str | None = None, ordinary_only: bool = True,
    max_listing_age_days: int | None = None, min_volume: float | None = None,
    extra_filters: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    cleaned = (raw or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", cleaned, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        cleaned = fenced.group(1).strip()
    plan = json.loads(cleaned)
    filters: List[Dict[str, Any]] = []
    for item in plan.get("filters") or []:
        field = str(item.get("field") or "")
        operator = str(item.get("operator") or "").lower()
        if field not in ALLOWED_FIELDS or operator not in ALLOWED_OPERATORS:
            continue
        if (field in NUMERIC_FIELDS and operator == "contains") or (field in TEXT_FIELDS and operator not in {"eq", "neq", "contains"}):
            continue
        if field in NUMERIC_FIELDS:
            try:
                value: Any = float(item.get("value"))
            except (TypeError, ValueError):
                continue
        else:
            value = str(item.get("value") or "").strip()
            if not value:
                continue
        filters.append({"field": field, "operator": operator, "value": value})
    manual_filters: List[Dict[str, Any]] = []
    for item in extra_filters or []:
        field = str(item.get("field") or "")
        operator = str(item.get("operator") or "").lower()
        if field not in ALLOWED_FIELDS or operator not in ALLOWED_OPERATORS:
            continue
        if (field in NUMERIC_FIELDS and operator == "contains") or (field in TEXT_FIELDS and operator not in {"eq", "neq", "contains"}):
            continue
        try:
            value = float(item.get("value")) if field in NUMERIC_FIELDS else str(item.get("value") or "").strip()
        except (TypeError, ValueError):
            continue
        if value == "":
            continue
        manual_filters.append({"field": field, "operator": operator, "value": value})
    if manual_filters:
        manual_fields = {item["field"] for item in manual_filters}
        filters = [item for item in filters if item["field"] not in manual_fields]
        filters.extend(manual_filters)
    if symbol:
        filters = [item for item in filters if item["field"] != "symbol"]
        filters.append({"field": "symbol", "operator": "eq", "value": symbol.upper()})
    if ordinary_only and not any(item["field"] == "security_type" for item in filters):
        filters.append({"field": "security_type", "operator": "eq", "value": "ordinary_share"})
    if max_listing_age_days is not None:
        filters = [item for item in filters if item["field"] != "listing_age_days"]
        filters.append({"field": "listing_age_days", "operator": "lte", "value": float(max_listing_age_days)})
    if min_volume is not None:
        filters = [item for item in filters if item["field"] != "latest_volume"]
        filters.append({"field": "latest_volume", "operator": "gte", "value": float(min_volume)})
    sort_by = str(plan.get("sort_by") or "robust_score")
    if sort_by not in NUMERIC_FIELDS:
        sort_by = "robust_score"
    direction = "asc" if str(plan.get("sort_direction")).lower() == "asc" else "desc"
    requested_columns = [
        str(item) for item in (plan.get("columns") or [])
        if str(item) in ALLOWED_FIELDS
    ]
    columns = list(dict.fromkeys(requested_columns))[:10] or list(DEFAULT_OUTPUT_COLUMNS)
    if "symbol" not in columns:
        columns.insert(0, "symbol")
    return {
        "filters": filters, "sort_by": sort_by, "sort_direction": direction,
        "columns": columns[:10],
        "explanation": str(plan.get("explanation") or "Ranks the matching stored simulations by robust confidence."),
    }


def _matches(row: Dict[str, Any], condition: Dict[str, Any]) -> bool:
    left, right, operator = row.get(condition["field"]), condition["value"], condition["operator"]
    if left is None:
        return False
    if condition["field"] in NUMERIC_FIELDS:
        try:
            left = float(left)
        except (TypeError, ValueError):
            return False
    else:
        left, right = str(left).lower(), str(right).lower()
    return {
        "eq": left == right, "neq": left != right, "gt": left > right,
        "gte": left >= right, "lt": left < right, "lte": left <= right,
        "contains": str(right) in str(left),
    }[operator]


def execute_plan(rows: List[Dict[str, Any]], plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    matched = [row for row in rows if all(_matches(row, item) for item in plan["filters"])]
    sort_by = plan["sort_by"]
    matched.sort(
        key=lambda row: (row.get(sort_by) is not None, float(row.get(sort_by) or 0), int(row.get("total_trades") or 0)),
        reverse=plan["sort_direction"] == "desc",
    )
    return matched[:10]


def compile_display_query(plan: Dict[str, Any]) -> str:
    operators = {"eq": "=", "neq": "!=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<=", "contains": "CONTAINS"}
    clauses = []
    for item in plan["filters"]:
        value = f"'{item['value']}'" if item["field"] in TEXT_FIELDS else f"{item['value']:g}"
        clauses.append(f"{item['field']} {operators[item['operator']]} {value}")
    where = " AND ".join(clauses) if clauses else "TRUE"
    columns = ", ".join(plan.get("columns") or DEFAULT_OUTPUT_COLUMNS)
    return f"SELECT {columns} FROM saved_backtest_results\nWHERE {where}\nORDER BY {plan['sort_by']} {plan['sort_direction'].upper()}\nLIMIT 10;"
