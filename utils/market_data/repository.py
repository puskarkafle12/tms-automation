"""Database helpers for market snapshots and screener cache."""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from database import ensure_read_session
from utils.market_data.merolagani_fields import extract_symbol
from utils.market_data.canonical_fields import (
    build_combined_record,
    canonicalize_merolagani_record,
    expand_legacy_field_aliases,
    get_column_label,
    ordered_columns_for_source,
)
from utils.external_data_sources.nepse_alpha.screener import flatten_nepse_alpha_for_screener

_EXCLUDED_NEW_SYMBOL_SECTOR_HINTS = (
    "mutual fund",
    "corporate debenture",
    "debenture",
    "bond",
    "bonds",
    "promotor share",
    "promoter share",
)

_EQUITY_SECTOR_HINTS = (
    "commercial bank",
    "development bank",
    "finance",
    "hydro power",
    "hydropower",
    "hotel",
    "insurance",
    "investment",
    "life insurance",
    "microfinance",
    "manufacturing",
    "non life insurance",
    "others",
    "trading",
)

_NON_EQUITY_SYMBOL_SUFFIXES = (
    "PO",
    "LP",
    "BP",
    "SP",
    "CP",
    "B",
    "IP",
)


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
    max_age_days = max(1, days)
    cutoff = date.today() - timedelta(days=max_age_days)
    latest_rows = {
        extract_symbol(row): row
        for row in load_latest_daily_stock_rows(db)
        if extract_symbol(row)
    }
    rows = db.execute(
        text(
            """
            SELECT symbol, first_seen_date, last_seen_date, is_watchlist
            FROM market_symbol_registry
            WHERE COALESCE(is_watchlist, TRUE) = TRUE
            ORDER BY first_seen_date DESC, symbol ASC
            """
        ),
        {},
    ).mappings().all()
    output: List[Dict[str, Any]] = []
    for row in rows:
        symbol = str(row["symbol"]).strip().upper()
        snapshot_row = latest_rows.get(symbol, {})
        sector = _extract_text_value(snapshot_row, {"ml_sector", "sector", "Sector"})
        security_type = _extract_text_value(snapshot_row, {"security_type"})
        listing_date = _parse_listing_date(
            _extract_text_value(snapshot_row, {"ml_listing_date", "listing_date", "Listing Date"})
        )
        listing_age = _extract_numeric_value(snapshot_row, {"listing_age_days"})
        volume = _extract_numeric_value(snapshot_row, {"ml_quantity", "Qty.", "qty", "volume"})
        if security_type and security_type != "ordinary_share":
            continue
        if listing_date is None:
            continue
        if listing_age is not None:
            if listing_age > max_age_days:
                continue
        elif listing_date < cutoff:
            continue
        if _should_include_new_symbol(symbol=symbol, sector=sector, cutoff=cutoff):
            payload = dict(row)
            payload["listing_date"] = listing_date.isoformat()
            payload["listing_age_days"] = int(listing_age) if listing_age is not None else max(0, (date.today() - listing_date).days)
            if sector:
                payload["sector"] = sector
            if volume is not None:
                payload["volume"] = volume
            output.append(payload)
    return output


def _extract_text_value(row: Dict[str, Any], keys: set[str]) -> str:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        text_value = str(value).strip()
        if text_value:
            return text_value
    return ""


def _extract_numeric_value(row: Dict[str, Any], keys: set[str]) -> Optional[float]:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return float(value)
        text_value = str(value).strip().replace(",", "")
        if not text_value or text_value in {"-", "N/A", "n/a"}:
            continue
        try:
            return float(text_value)
        except ValueError:
            continue
    return None


def _parse_listing_date(value: str) -> Optional[date]:
    text = str(value or "").strip()
    if not text or text in {"-", "N/A", "n/a"}:
        return None
    for fmt in (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%d %b %Y",
        "%d %B %Y",
    ):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def _sector_looks_like_equity(sector: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(sector or "").strip().lower())
    if not normalized:
        return False
    if any(hint in normalized for hint in _EXCLUDED_NEW_SYMBOL_SECTOR_HINTS):
        return False
    return any(hint in normalized for hint in _EQUITY_SECTOR_HINTS)


def _symbol_looks_like_equity(symbol: str) -> bool:
    normalized = re.sub(r"\s+", "", str(symbol or "").strip().upper())
    if not normalized:
        return False
    if any(char.isdigit() for char in normalized):
        return False
    if any(normalized.endswith(suffix) for suffix in _NON_EQUITY_SYMBOL_SUFFIXES):
        return False
    if len(normalized) < 3:
        return False
    return True


def _should_include_new_symbol(*, symbol: str, sector: str, cutoff: date) -> bool:
    if sector:
        return _sector_looks_like_equity(sector)
    return _symbol_looks_like_equity(symbol)


def set_new_symbol_watchlist_status(db: Session, symbols: List[str], *, is_watchlist: bool) -> int:
    normalized_symbols = sorted({str(symbol or "").strip().upper() for symbol in symbols if str(symbol or "").strip()})
    if not normalized_symbols:
        return 0
    result = db.execute(
        text(
            """
            UPDATE market_symbol_registry
            SET is_watchlist = :is_watchlist,
                updated_at = CURRENT_TIMESTAMP
            WHERE symbol IN :symbols
            """
        ).bindparams(bindparam("symbols", expanding=True)),
        {"is_watchlist": is_watchlist, "symbols": normalized_symbols},
    )
    return int(result.rowcount or 0)


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
