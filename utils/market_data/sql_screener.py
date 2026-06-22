"""Run market screener queries as SQL against combined cache data."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Set

from sqlalchemy import text
from sqlalchemy.orm import Session

from database import ensure_read_session
from utils.market_data.dynamic_catalog import build_dynamic_field_catalog, build_dynamic_query_spec
from utils.market_data.repository import get_cache_status

MARKET_TABLE = "market_combined"
SCREEN_VIEW_NAME = "v_nepse_stock_screen"
LEGACY_TABLE = "combined_market_data"
MAX_SQL_LENGTH = 32_000
MAX_SQL_LIMIT = 500
AI_BASE_SELECT_COLUMNS = ("symbol", "ltp", "percent_change", "qty")

FORBIDDEN_SQL_PATTERNS = (
    r"\binsert\b",
    r"\bupdate\b",
    r"\bdelete\b",
    r"\bdrop\b",
    r"\balter\b",
    r"\bcreate\b",
    r"\btruncate\b",
    r"\bgrant\b",
    r"\brevoke\b",
    r"\bunion\b",
    r"\bjoin\b",
    r"\binto\b",
    r"\bpg_catalog\b",
    r"\binformation_schema\b",
    r";\s*\S",  # multiple statements
    r"--",
    r"/\*",
)

ALLOWED_QUERY_SOURCES = (
    MARKET_TABLE,
    SCREEN_VIEW_NAME,
    LEGACY_TABLE,
)

NUMERIC_OPERATORS = {
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
    "eq": "=",
    "neq": "!=",
}


class MarketSqlError(ValueError):
    """Invalid or unsafe market screener SQL."""


def _quote_identifier(key: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_]", "", str(key or ""))
    if not safe:
        raise MarketSqlError(f"Invalid column name: {key!r}")
    return safe


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        inner = ", ".join(_sql_literal(item) for item in value)
        return f"({inner})"
    text_value = str(value).replace("'", "''")
    return f"'{text_value}'"


def _json_text_expr(column: str, json_key: str, dialect_name: str) -> str:
    escaped_key = json_key.replace("'", "''")
    if dialect_name == "sqlite":
        return f"json_extract({column}, '$.{escaped_key}')"
    return f"{column}->>'{escaped_key}'"


def _json_number_expr(column: str, json_key: str, alias: str, dialect_name: str) -> str:
    text_expr = _json_text_expr(column, json_key, dialect_name)
    if dialect_name == "sqlite":
        return f"CAST({text_expr} AS REAL) AS {alias}"
    return f"NULLIF({text_expr}, '')::double precision AS {alias}"


def build_market_combined_subquery(db: Session) -> str:
    """Inline subquery exposing combined_data JSON keys as typed SQL columns."""
    dialect_name = db.get_bind().dialect.name
    catalog = build_dynamic_field_catalog(db)
    selects = ["symbol", "updated_at"]
    seen: Set[str] = set()
    for item in catalog:
        key = _quote_identifier(item["key"])
        if key in seen or key in {"symbol", "updated_at"}:
            continue
        seen.add(key)
        json_key = str(item["key"])
        if item.get("type") == "number":
            selects.append(
                _json_number_expr("combined_data", json_key, key, dialect_name)
            )
        else:
            selects.append(f"{_json_text_expr('combined_data', json_key, dialect_name)} AS {key}")
    column_sql = ",\n        ".join(selects)
    return f"""
        SELECT
        {column_sql}
        FROM market_screener_cache
        WHERE combined_data IS NOT NULL
    """


def normalize_user_sql(query: str) -> str:
    """Accept full SELECT, WITH preset SQL, or legacy WHERE/ORDER BY fragments."""
    cleaned = re.sub(r"--[^\n]*", "", query or "")
    cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.DOTALL)
    cleaned = cleaned.strip().rstrip(";")
    if not cleaned:
        raise MarketSqlError("SQL query is empty")
    upper = cleaned.upper()
    if upper.startswith("SELECT") or upper.startswith("WITH"):
        return cleaned
    if not upper.startswith("WHERE"):
        cleaned = f"WHERE {cleaned}"
    return f"SELECT * FROM {MARKET_TABLE} {cleaned}"


def validate_market_sql(sql: str, *, allow_select_star: bool = True) -> None:
    lowered = sql.lower()
    if len(sql) > MAX_SQL_LENGTH:
        raise MarketSqlError("SQL query is too long")
    if not (lowered.strip().startswith("select") or lowered.strip().startswith("with")):
        raise MarketSqlError("Only SELECT or WITH queries are allowed")
    if not allow_select_star and re.search(r"select\s+\*\s+from\s+market_combined\b", lowered):
        raise MarketSqlError("Use an explicit column list in SELECT — SELECT * FROM market_combined is not allowed for AI queries")
    if not any(source in lowered for source in ALLOWED_QUERY_SOURCES):
        raise MarketSqlError(
            f"Query must read FROM {MARKET_TABLE} or {SCREEN_VIEW_NAME}"
        )
    for pattern in FORBIDDEN_SQL_PATTERNS:
        if re.search(pattern, lowered):
            raise MarketSqlError("Query contains forbidden SQL syntax")
    if re.search(r"\bmarket_screener_cache\b", lowered):
        raise MarketSqlError(f"Use {MARKET_TABLE} or {SCREEN_VIEW_NAME} instead of market_screener_cache")


def _split_select_list(select_list: str) -> List[str]:
    parts: List[str] = []
    depth = 0
    current: List[str] = []
    for char in select_list:
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            part = "".join(current).strip()
            if part:
                parts.append(part)
            current = []
            continue
        current.append(char)
    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return parts


def _select_expression_name(expression: str) -> Optional[str]:
    cleaned = expression.strip()
    if not cleaned:
        return None
    alias_match = re.search(r"\bas\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*$", cleaned, flags=re.IGNORECASE)
    if alias_match:
        return alias_match.group(1).lower()
    token = cleaned.split(".")[-1].strip()
    if re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", token):
        return token.lower()
    return None


def _select_list_column_names(select_list: str) -> Set[str]:
    names: Set[str] = set()
    for expression in _split_select_list(select_list):
        name = _select_expression_name(expression)
        if name:
            names.add(name)
    return names


def _ensure_ai_display_columns(sql: str) -> str:
    """Prepend symbol/ltp/percent_change/qty when AI omits them from SELECT."""
    pattern = re.compile(
        r"(select\s+(?:distinct\s+)?)(.*?)(\s+from\s+market_combined\b)",
        re.IGNORECASE | re.DOTALL,
    )
    matches = list(pattern.finditer(sql))
    if not matches:
        return sql
    match = matches[-1]
    existing = _select_list_column_names(match.group(2))
    missing = [column for column in AI_BASE_SELECT_COLUMNS if column not in existing]
    if not missing:
        return sql
    select_prefix = match.group(1)
    original_list = match.group(2).strip()
    from_suffix = match.group(3)
    merged = ", ".join([*missing, original_list]) if original_list else ", ".join(missing)
    replacement = f"{select_prefix}{merged}{from_suffix}"
    return f"{sql[:match.start()]}{replacement}{sql[match.end():]}"


def _validate_ai_select_columns(sql: str) -> None:
    pattern = re.compile(
        r"select\s+(?:distinct\s+)?(.*?)\s+from\s+market_combined\b",
        re.IGNORECASE | re.DOTALL,
    )
    matches = list(pattern.finditer(sql))
    if not matches:
        return
    names = _select_list_column_names(matches[-1].group(1))
    if "symbol" not in names:
        raise MarketSqlError(
            "SELECT must include symbol so each row shows a stock name. "
            f"Also include: {', '.join(AI_BASE_SELECT_COLUMNS)}"
        )


def _adapt_sql_for_dialect(sql: str, dialect_name: str) -> str:
    if dialect_name == "sqlite":
        sql = sql.replace("::numeric", "")
        sql = re.sub(r"\sNULLS FIRST", "", sql, flags=re.IGNORECASE)
        sql = re.sub(r"\sNULLS LAST", "", sql, flags=re.IGNORECASE)
        sql = re.sub(r"\bGREATEST\s*\(", "MAX(", sql, flags=re.IGNORECASE)
    return sql


def _expand_screen_view(sql: str, db: Session) -> str:
    if SCREEN_VIEW_NAME not in sql.lower():
        return sql
    from utils.market_data.screen_view import build_v_nepse_stock_screen_subquery

    view_sql = build_v_nepse_stock_screen_subquery(db)
    return re.sub(
        rf"\bFROM\s+{SCREEN_VIEW_NAME}\b",
        f"FROM ({view_sql})",
        sql,
        flags=re.IGNORECASE,
    )


def _expand_market_table(sql: str, db: Session) -> str:
    subquery = build_market_combined_subquery(db)
    for table_name in (MARKET_TABLE, LEGACY_TABLE):
        if table_name not in sql.lower():
            continue
        sql = re.sub(
            rf"\bFROM\s+{table_name}\b",
            f"FROM ({subquery}) AS {MARKET_TABLE}",
            sql,
            count=1,
            flags=re.IGNORECASE,
        )
    return sql


def _enforce_limit(sql: str, limit: Optional[int] = None) -> str:
    if re.search(r"\blimit\b", sql, flags=re.IGNORECASE):
        match = re.search(r"\blimit\s+(\d+)", sql, flags=re.IGNORECASE)
        if match:
            current = int(match.group(1))
            if current > MAX_SQL_LIMIT:
                sql = re.sub(
                    r"\blimit\s+\d+",
                    f"LIMIT {MAX_SQL_LIMIT}",
                    sql,
                    count=1,
                    flags=re.IGNORECASE,
                )
        return sql
    applied = max(1, min(int(limit or 25), MAX_SQL_LIMIT))
    return f"{sql.rstrip()} LIMIT {applied}"


def _apply_symbol_filter(sql: str, symbols: Sequence[str]) -> str:
    if not symbols:
        return sql
    safe_symbols = ", ".join(f"'{_quote_identifier(sym)}'" for sym in symbols if str(sym).strip())
    if not safe_symbols:
        return sql
    clause = f"symbol IN ({safe_symbols})"
    upper = sql.upper()
    if " WHERE " in upper:
        return re.sub(r"\bWHERE\b", f"WHERE {clause} AND ", sql, count=1, flags=re.IGNORECASE)
    if " GROUP BY " in upper:
        return re.sub(r"\bGROUP BY\b", f"WHERE {clause} GROUP BY", sql, count=1, flags=re.IGNORECASE)
    if " ORDER BY " in upper:
        return re.sub(r"\bORDER BY\b", f"WHERE {clause} ORDER BY", sql, count=1, flags=re.IGNORECASE)
    if " LIMIT " in upper:
        return re.sub(r"\bLIMIT\b", f"WHERE {clause} LIMIT", sql, count=1, flags=re.IGNORECASE)
    return f"{sql} WHERE {clause}"


def prepare_market_sql(
    db: Session,
    query: str,
    symbols: Optional[Sequence[str]] = None,
    *,
    allow_select_star: bool = True,
) -> str:
    normalized = normalize_user_sql(query)
    validate_market_sql(normalized, allow_select_star=allow_select_star)
    if not allow_select_star:
        if re.search(r"select\s+\*", normalized, flags=re.IGNORECASE):
            raise MarketSqlError("Use an explicit column list in SELECT — SELECT * is not allowed for AI queries")
        normalized = _ensure_ai_display_columns(normalized)
        _validate_ai_select_columns(normalized)
    dialect_name = db.get_bind().dialect.name
    prepared = _expand_screen_view(normalized, db)
    prepared = _expand_market_table(prepared, db)
    if not any(
        token in prepared.lower()
        for token in (MARKET_TABLE, SCREEN_VIEW_NAME, "market_screener_cache")
    ):
        raise MarketSqlError(f"Could not prepare query for {MARKET_TABLE}")
    prepared = _adapt_sql_for_dialect(prepared, dialect_name)
    prepared = _apply_symbol_filter(prepared, symbols or [])
    prepared = _enforce_limit(prepared)
    return prepared


def filters_to_market_sql(
    db: Session,
    filters: List[Dict[str, Any]],
    *,
    rank_by: Optional[str] = None,
    rank_direction: str = "desc",
    limit: int = 25,
) -> str:
    spec = build_dynamic_query_spec(db)
    alias_map = spec.get("alias_map") or {}
    allowed = set(spec.get("allowed_filter_keys") or [])
    where_parts: List[str] = []

    for item in filters:
        raw_field = str(item.get("field") or "").strip()
        if not raw_field:
            continue
        field = alias_map.get(raw_field.lower(), raw_field)
        canonical = _quote_identifier(field)
        if canonical not in allowed and field not in allowed and raw_field not in allowed:
            raise MarketSqlError(f"Unknown filter field: {raw_field}")
        field = canonical
        operator = str(item.get("operator") or "gte").lower()
        value = item.get("value")
        if operator == "between":
            bounds = value if isinstance(value, list) else []
            if len(bounds) != 2:
                raise MarketSqlError(f"BETWEEN requires two values for {field}")
            where_parts.append(f"{field} BETWEEN {_sql_literal(bounds[0])} AND {_sql_literal(bounds[1])}")
        elif operator == "in":
            values = value if isinstance(value, list) else [value]
            where_parts.append(f"{field} IN {_sql_literal(values)}")
        elif operator == "contains":
            where_parts.append(f"{field} ILIKE '%' || {_sql_literal(str(value))} || '%'")
        elif operator in NUMERIC_OPERATORS:
            where_parts.append(f"{field} {NUMERIC_OPERATORS[operator]} {_sql_literal(value)}")
        elif operator in {"eq", "neq"}:
            sql_op = "=" if operator == "eq" else "!="
            where_parts.append(f"{field} {sql_op} {_sql_literal(value)}")
        else:
            raise MarketSqlError(f"Unsupported operator: {operator}")

    where_sql = " AND ".join(where_parts) if where_parts else "TRUE"
    order_field = _quote_identifier(rank_by or spec.get("default_rank_by") or "ltp")
    direction = "ASC" if str(rank_direction).lower() == "asc" else "DESC"
    applied_limit = max(1, min(int(limit or 25), MAX_SQL_LIMIT))
    return (
        f"SELECT * FROM {MARKET_TABLE} "
        f"WHERE {where_sql} "
        f"ORDER BY {order_field} {direction} "
        f"LIMIT {applied_limit}"
    )


def run_market_sql_screener(
    db: Session,
    query: str,
    symbols: Optional[List[str]] = None,
    *,
    allow_select_star: bool = True,
) -> Dict[str, Any]:
    from utils.market_data.dynamic_catalog import build_column_labels_for_keys

    ensure_read_session(db)
    prepared_sql = prepare_market_sql(db, query, symbols, allow_select_star=allow_select_star)
    try:
        rows = db.execute(text(prepared_sql)).mappings().all()
    except Exception:
        ensure_read_session(db)
        raise
    results: List[Dict[str, Any]] = []
    result_keys: List[str] = []
    for index, row in enumerate(rows, start=1):
        record = dict(row)
        record["rank"] = index
        if not result_keys:
            result_keys = [key for key in record.keys() if key != "rank"]
        results.append(record)

    display_keys = ["rank", *result_keys] if result_keys else ["rank", "symbol"]
    column_labels = build_column_labels_for_keys(display_keys)
    column_labels["rank"] = "Rank"

    loaded = len(symbols) if symbols else int(
        db.execute(text("SELECT COUNT(*) FROM market_screener_cache WHERE combined_data IS NOT NULL")).scalar() or 0
    )
    status = get_cache_status(db)
    return {
        "results": results,
        "stats": {
            "requested": loaded,
            "loaded": loaded,
            "failed": 0,
            "cache_hits": loaded,
            "matched": len(results),
            "returned": len(results),
            "data_source": "database_sql",
        },
        "sql": prepared_sql,
        "result_columns": display_keys,
        "column_labels": column_labels,
        "cache_status": status,
    }


def validate_market_sql_query(db: Session, query: str, *, allow_select_star: bool = True) -> Dict[str, Any]:
    ensure_read_session(db)
    prepared = prepare_market_sql(db, query, allow_select_star=allow_select_star)
    return {
        "sql": prepared,
        "table": MARKET_TABLE,
        "valid": True,
    }
