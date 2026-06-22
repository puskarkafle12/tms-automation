"""Thread-pool workers for market analysis (each opens its own DB session)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from database import SessionLocal, ensure_read_session
from utils.market_data.combined_screener import (
    get_combined_field_catalog,
    get_combined_query_spec,
    run_combined_screener_from_db,
)
from utils.market_data.combined_screener import parse_combined_screener_query
from utils.market_data.repository import (
    get_cache_status,
    get_new_symbols,
    get_table_display_metadata,
    load_latest_daily_stock_rows,
    load_table_rows,
)
from utils.market_data.screen_presets import ensure_market_screen_presets, list_market_screen_presets
from utils.market_data.sql_screener import MarketSqlError


def worker_get_fields() -> Dict[str, Any]:
    db = SessionLocal()
    try:
        ensure_read_session(db)
        return {
            "fields": get_combined_field_catalog(db),
            "cache_ttl_seconds": 10 * 60,
            "query_spec": get_combined_query_spec(db),
        }
    finally:
        db.close()


def worker_get_presets() -> Dict[str, Any]:
    db = SessionLocal()
    try:
        ensure_market_screen_presets(db)
        return {
            "presets": list_market_screen_presets(db),
            "groups": [
                {"category": "INVESTOR", "label": "Investor"},
                {"category": "TRADER", "label": "Trader"},
            ],
        }
    finally:
        db.close()


def worker_get_status() -> Dict[str, Any]:
    from utils.market_data.scheduler import get_market_data_scheduler_status

    db = SessionLocal()
    try:
        ensure_read_session(db)
        return {
            **get_cache_status(db),
            "scheduler": get_market_data_scheduler_status(db),
        }
    finally:
        db.close()


def worker_get_new_stocks(days: int) -> Dict[str, Any]:
    db = SessionLocal()
    try:
        ensure_read_session(db)
        return {"days": days, "symbols": get_new_symbols(db, days=days)}
    finally:
        db.close()


def worker_get_market_data(source: str) -> Dict[str, Any]:
    db = SessionLocal()
    try:
        ensure_read_session(db)
        rows = load_table_rows(db, source)
        if not rows and source in {"combined", "merolagani"}:
            fallback_rows = load_latest_daily_stock_rows(db)
            if fallback_rows:
                rows = fallback_rows
        display = get_table_display_metadata(source, rows)
        return {
            "source": source,
            "count": len(rows),
            "rows": rows,
            "columns": display["columns"],
            "column_labels": display["column_labels"],
            "cache_status": get_cache_status(db),
        }
    finally:
        db.close()


def worker_parse_query(query: str) -> Dict[str, Any]:
    db = SessionLocal()
    try:
        ensure_read_session(db)
        return parse_combined_screener_query(query, db=db)
    finally:
        db.close()


def worker_run_market_screen(
    *,
    symbols: List[str],
    sql: Optional[str],
    filters: Optional[List[Dict[str, Any]]],
    rank_by: Optional[str],
    rank_direction: str,
    limit: int,
    allow_select_star: bool = True,
) -> Dict[str, Any]:
    db = SessionLocal()
    try:
        ensure_read_session(db)
        return run_combined_screener_from_db(
            db,
            symbols,
            sql=sql,
            filters=filters if not sql else None,
            rank_by=rank_by,
            rank_direction=rank_direction,
            limit=limit,
            allow_select_star=allow_select_star,
        )
    finally:
        db.close()
