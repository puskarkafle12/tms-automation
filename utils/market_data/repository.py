"""Database helpers for market snapshots and screener cache."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from database import ensure_read_session
from utils.market_data.canonical_fields import (
    build_combined_record,
    canonicalize_merolagani_record,
    expand_legacy_field_aliases,
    get_column_label,
    ordered_columns_for_source,
)
from utils.external_data_sources.nepse_alpha.screener import flatten_nepse_alpha_for_screener


def _json_dump(value: Any) -> str:
    return json.dumps(value, default=str)


def get_last_refresh(db: Session, refresh_type: str) -> Optional[datetime]:
    row = db.execute(
        text(
            """
            SELECT completed_at
            FROM market_data_refresh_log
            WHERE refresh_type = :refresh_type AND status = 'ok'
            ORDER BY completed_at DESC
            LIMIT 1
            """
        ),
        {"refresh_type": refresh_type},
    ).scalar()
    if isinstance(row, str):
        return datetime.fromisoformat(row)
    return row


def log_refresh(
    db: Session,
    *,
    refresh_type: str,
    status: str,
    symbol_count: int = 0,
    message: str = "",
    started_at: Optional[datetime] = None,
) -> None:
    db.execute(
        text(
            """
            INSERT INTO market_data_refresh_log (
                refresh_type, status, symbol_count, message, started_at, completed_at
            )
            VALUES (
                :refresh_type, :status, :symbol_count, :message, :started_at, NOW()
            )
            """
        ),
        {
            "refresh_type": refresh_type,
            "status": status,
            "symbol_count": symbol_count,
            "message": message[:2000] if message else "",
            "started_at": started_at or datetime.utcnow(),
        },
    )


def has_daily_snapshot(db: Session, snapshot_date: date) -> bool:
    return bool(
        db.execute(
            text("SELECT 1 FROM merolagani_daily_snapshots WHERE snapshot_date = :snapshot_date LIMIT 1"),
            {"snapshot_date": snapshot_date},
        ).scalar()
    )


def save_daily_snapshot(db: Session, snapshot_date: date, rows: List[Dict[str, Any]]) -> int:
    symbols = sorted({extract_symbol(row) for row in rows if extract_symbol(row)})
    db.execute(
        text(
            """
            INSERT INTO merolagani_daily_snapshots (snapshot_date, symbol_count, created_at)
            VALUES (:snapshot_date, :symbol_count, NOW())
            ON CONFLICT (snapshot_date) DO UPDATE SET
                symbol_count = EXCLUDED.symbol_count,
                created_at = NOW()
            """
        ),
        {"snapshot_date": snapshot_date, "symbol_count": len(symbols)},
    )

    for row in rows:
        symbol = extract_symbol(row)
        if not symbol:
            continue
        db.execute(
            text(
                """
                INSERT INTO merolagani_daily_stocks (snapshot_date, symbol, data, created_at)
                VALUES (:snapshot_date, :symbol, CAST(:data AS JSON), NOW())
                ON CONFLICT (snapshot_date, symbol) DO UPDATE SET
                    data = EXCLUDED.data,
                    created_at = NOW()
                """
            ),
            {"snapshot_date": snapshot_date, "symbol": symbol, "data": _json_dump(row)},
        )
        db.execute(
            text(
                """
                INSERT INTO market_symbol_registry (symbol, first_seen_date, last_seen_date, is_watchlist, created_at, updated_at)
                VALUES (:symbol, :snapshot_date, :snapshot_date, TRUE, NOW(), NOW())
                ON CONFLICT (symbol) DO UPDATE SET
                    last_seen_date = EXCLUDED.last_seen_date,
                    updated_at = NOW()
                """
            ),
            {"symbol": symbol, "snapshot_date": snapshot_date},
        )
    return len(symbols)


def get_cache_symbol_count(db: Session) -> int:
    ensure_read_session(db)
    return int(db.execute(text("SELECT COUNT(*) FROM market_screener_cache")).scalar() or 0)


def load_latest_daily_stock_rows(db: Session) -> List[Dict[str, Any]]:
    snapshot_date = db.execute(
        text("SELECT snapshot_date FROM merolagani_daily_snapshots ORDER BY snapshot_date DESC LIMIT 1")
    ).scalar()
    if not snapshot_date:
        return []

    rows = db.execute(
        text(
            """
            SELECT symbol, data
            FROM merolagani_daily_stocks
            WHERE snapshot_date = :snapshot_date
            ORDER BY symbol ASC
            """
        ),
        {"snapshot_date": snapshot_date},
    ).mappings().all()

    output: List[Dict[str, Any]] = []
    for row in rows:
        payload = row.get("data") or {}
        if isinstance(payload, str):
            payload = json.loads(payload)
        if isinstance(payload, dict):
            output.append(payload)
    return output


def get_new_symbols(db: Session, *, days: int = 15) -> List[Dict[str, Any]]:
    cutoff = date.today() - timedelta(days=max(1, days))
    first_snapshot = db.execute(
        text("SELECT MIN(snapshot_date) FROM merolagani_daily_snapshots"),
    ).scalar()
    rows = db.execute(
        text(
            """
            SELECT symbol, first_seen_date, last_seen_date, is_watchlist
            FROM market_symbol_registry
            WHERE first_seen_date >= :cutoff
              AND (:first_snapshot IS NULL OR first_seen_date > :first_snapshot)
            ORDER BY first_seen_date DESC, symbol ASC
            """
        ),
        {"cutoff": cutoff, "first_snapshot": first_snapshot},
    ).mappings().all()
    return [dict(row) for row in rows]


def upsert_screener_cache_row(
    db: Session,
    *,
    symbol: str,
    merolagani_data: Optional[Dict[str, Any]] = None,
    nepse_alpha_data: Optional[Dict[str, Any]] = None,
    combined_data: Optional[Dict[str, Any]] = None,
    merolagani_fetched_at: Optional[datetime] = None,
    nepse_alpha_fetched_at: Optional[datetime] = None,
) -> None:
    db.execute(
        text(
            """
            INSERT INTO market_screener_cache (
                symbol, merolagani_data, nepse_alpha_data, combined_data,
                merolagani_fetched_at, nepse_alpha_fetched_at, updated_at
            )
            VALUES (
                :symbol,
                CAST(:merolagani_data AS JSON),
                CAST(:nepse_alpha_data AS JSON),
                CAST(:combined_data AS JSON),
                :merolagani_fetched_at,
                :nepse_alpha_fetched_at,
                NOW()
            )
            ON CONFLICT (symbol) DO UPDATE SET
                merolagani_data = COALESCE(EXCLUDED.merolagani_data, market_screener_cache.merolagani_data),
                nepse_alpha_data = COALESCE(EXCLUDED.nepse_alpha_data, market_screener_cache.nepse_alpha_data),
                combined_data = COALESCE(EXCLUDED.combined_data, market_screener_cache.combined_data),
                merolagani_fetched_at = COALESCE(EXCLUDED.merolagani_fetched_at, market_screener_cache.merolagani_fetched_at),
                nepse_alpha_fetched_at = COALESCE(EXCLUDED.nepse_alpha_fetched_at, market_screener_cache.nepse_alpha_fetched_at),
                updated_at = NOW()
            """
        ),
        {
            "symbol": symbol.upper(),
            "merolagani_data": _json_dump(merolagani_data) if merolagani_data is not None else None,
            "nepse_alpha_data": _json_dump(nepse_alpha_data) if nepse_alpha_data is not None else None,
            "combined_data": _json_dump(combined_data) if combined_data is not None else None,
            "merolagani_fetched_at": merolagani_fetched_at,
            "nepse_alpha_fetched_at": nepse_alpha_fetched_at,
        },
    )


def load_cached_records(db: Session, symbols: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    ensure_read_session(db)
    if symbols:
        normalized = sorted({str(item).strip().upper() for item in symbols if str(item).strip()})
        if not normalized:
            return []
        placeholders = ", ".join(f":sym_{index}" for index, _ in enumerate(normalized))
        params = {f"sym_{index}": symbol for index, symbol in enumerate(normalized)}
        rows = db.execute(
            text(
                f"""
                SELECT symbol, combined_data, merolagani_data, nepse_alpha_data,
                       merolagani_fetched_at, nepse_alpha_fetched_at, updated_at
                FROM market_screener_cache
                WHERE symbol IN ({placeholders})
                """
            ),
            params,
        ).mappings().all()
    else:
        rows = db.execute(
            text(
                """
                SELECT symbol, combined_data, merolagani_data, nepse_alpha_data,
                       merolagani_fetched_at, nepse_alpha_fetched_at, updated_at
                FROM market_screener_cache
                ORDER BY symbol ASC
                """
            )
        ).mappings().all()

    records: List[Dict[str, Any]] = []
    for row in rows:
        combined = row.get("combined_data") or {}
        if isinstance(combined, str):
            combined = json.loads(combined)
        if not combined:
            continue
        record = dict(combined)
        record["symbol"] = row["symbol"]
        record["cached"] = True
        records.append(expand_legacy_field_aliases(record))
    return records


def get_cache_status(db: Session) -> Dict[str, Any]:
    ensure_read_session(db)
    counts = db.execute(
        text(
            """
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE merolagani_data IS NOT NULL) AS merolagani_count,
                COUNT(*) FILTER (WHERE nepse_alpha_data IS NOT NULL) AS nepse_alpha_count,
                COUNT(*) FILTER (WHERE combined_data IS NOT NULL) AS combined_count,
                MAX(updated_at) AS last_updated
            FROM market_screener_cache
            """
        )
    ).mappings().first()
    latest_snapshot = db.execute(
        text("SELECT snapshot_date, symbol_count, created_at FROM merolagani_daily_snapshots ORDER BY snapshot_date DESC LIMIT 1")
    ).mappings().first()
    return {
        "cache": dict(counts or {}),
        "latest_daily_snapshot": dict(latest_snapshot) if latest_snapshot else None,
        "last_daily_refresh": get_last_refresh(db, "daily_snapshot"),
        "last_merolagani_refresh": get_last_refresh(db, "merolagani_cache"),
        "last_nepse_alpha_refresh": get_last_refresh(db, "nepse_alpha_cache"),
        "last_screener_refresh": get_last_refresh(db, "merolagani_cache"),
    }


def load_table_rows(db: Session, source: str, symbols: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    ensure_read_session(db)
    column_map = {
        "merolagani": "merolagani_data",
        "nepse_alpha": "nepse_alpha_data",
        "combined": "combined_data",
    }
    column = column_map.get(source, "combined_data")
    if symbols:
        normalized = sorted({str(item).strip().upper() for item in symbols if str(item).strip()})
        placeholders = ", ".join(f":sym_{index}" for index, _ in enumerate(normalized))
        params = {f"sym_{index}": symbol for index, symbol in enumerate(normalized)}
        rows = db.execute(
            text(
                f"""
                SELECT symbol, {column} AS payload, updated_at
                FROM market_screener_cache
                WHERE symbol IN ({placeholders})
                ORDER BY symbol ASC
                """
            ),
            params,
        ).mappings().all()
    else:
        rows = db.execute(
            text(
                f"""
                SELECT symbol, {column} AS payload, updated_at
                FROM market_screener_cache
                WHERE {column} IS NOT NULL
                ORDER BY symbol ASC
                """
            )
        ).mappings().all()

    output: List[Dict[str, Any]] = []
    for row in rows:
        payload = row.get("payload") or {}
        if isinstance(payload, str):
            payload = json.loads(payload)
        if source == "merolagani":
            item = canonicalize_merolagani_record(payload if isinstance(payload, dict) else {})
        elif source == "nepse_alpha":
            payload_dict = payload if isinstance(payload, dict) else {}
            if payload_dict.get("statistical_performance"):
                payload_dict = flatten_nepse_alpha_for_screener(payload_dict)
            item = build_combined_record(None, payload_dict)
        else:
            item = dict(payload) if isinstance(payload, dict) else {}
            if item and not item.get("ltp") and not item.get("ml_ltp"):
                item = build_combined_record(item, item)
            elif item and any(key.startswith("ml_") for key in item.keys()):
                item = build_combined_record(item, item)
        item["symbol"] = row["symbol"]
        item["updated_at"] = row.get("updated_at")
        output.append(item)
    return output


def get_table_display_metadata(source: str, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    columns = ordered_columns_for_source(source, rows)
    return {
        "columns": columns,
        "column_labels": {column: get_column_label(column) for column in columns},
    }
