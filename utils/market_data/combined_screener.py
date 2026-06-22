"""Combined market screener backed by SQL over cached combined data."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from database import ensure_read_session
from utils.market_data.dynamic_catalog import (
    build_dynamic_field_catalog,
    build_dynamic_query_spec,
)
from utils.market_data.repository import get_cache_status
from utils.market_data.sql_screener import (
    MarketSqlError,
    filters_to_market_sql,
    run_market_sql_screener,
    validate_market_sql_query,
)

DB_CACHE_TTL_SECONDS = 10 * 60
NEPSE_ALPHA_CACHE_TTL_SECONDS = 10 * 60


def get_combined_field_catalog(db: Optional[Session] = None) -> List[Dict[str, Any]]:
    return build_dynamic_field_catalog(db)


def get_combined_query_spec(db: Optional[Session] = None) -> Dict[str, Any]:
    spec = build_dynamic_query_spec(db)
    spec.update(
        {
            "query_language": "sql",
            "market_table": "market_combined",
            "refresh_interval_seconds": DB_CACHE_TTL_SECONDS,
            "merolagani_refresh_interval_seconds": DB_CACHE_TTL_SECONDS,
            "nepse_alpha_refresh_interval_seconds": NEPSE_ALPHA_CACHE_TTL_SECONDS,
        }
    )
    return spec


def run_combined_screener_from_db(
    db: Session,
    symbols: List[str],
    *,
    sql: Optional[str] = None,
    filters: Optional[List[Dict[str, Any]]] = None,
    rank_by: Optional[str] = None,
    rank_direction: str = "desc",
    limit: int = 50,
) -> Dict[str, Any]:
    ensure_read_session(db)
    if sql and sql.strip():
        payload = run_market_sql_screener(db, sql, symbols if symbols else None)
    elif filters is not None:
        generated_sql = filters_to_market_sql(
            db,
            filters,
            rank_by=rank_by,
            rank_direction=rank_direction,
            limit=limit,
        )
        payload = run_market_sql_screener(db, generated_sql, symbols if symbols else None)
    else:
        spec = get_combined_query_spec(db)
        default_sql = (
            f"SELECT * FROM market_combined "
            f"ORDER BY {spec.get('default_rank_by') or 'ltp'} DESC "
            f"LIMIT {max(1, min(int(limit or 25), 500))}"
        )
        payload = run_market_sql_screener(db, default_sql, symbols if symbols else None)

    query_spec = get_combined_query_spec(db)
    payload["query_spec"] = {
        "dynamic": query_spec.get("dynamic"),
        "field_count": query_spec.get("field_count"),
        "default_rank_by": query_spec.get("default_rank_by"),
        "query_language": "sql",
    }
    payload["cache_status"] = get_cache_status(db)
    return payload


def parse_combined_screener_query(query: str, db: Optional[Session] = None) -> Dict[str, Any]:
    if db is None:
        raise MarketSqlError("Database session is required to validate SQL")
    return validate_market_sql_query(db, query)
