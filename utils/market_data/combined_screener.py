"""Combined market screener backed by SQL over cached combined data."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

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
FIELD_CATALOG_CACHE_TTL_SECONDS = 10 * 60

_field_catalog_cache: Optional[Tuple[float, List[Dict[str, Any]]]] = None
_query_spec_cache: Optional[Tuple[float, Dict[str, Any]]] = None


def invalidate_combined_catalog_cache() -> None:
    global _field_catalog_cache, _query_spec_cache
    _field_catalog_cache = None
    _query_spec_cache = None


def get_combined_field_catalog(db: Optional[Session] = None) -> List[Dict[str, Any]]:
    global _field_catalog_cache
    now = time.time()
    if _field_catalog_cache and now - _field_catalog_cache[0] < FIELD_CATALOG_CACHE_TTL_SECONDS:
        return _field_catalog_cache[1]
    catalog = build_dynamic_field_catalog(db)
    _field_catalog_cache = (now, catalog)
    return catalog


def get_combined_query_spec(db: Optional[Session] = None) -> Dict[str, Any]:
    global _query_spec_cache
    now = time.time()
    if _query_spec_cache and now - _query_spec_cache[0] < FIELD_CATALOG_CACHE_TTL_SECONDS:
        return _query_spec_cache[1]
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
    _query_spec_cache = (now, spec)
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
