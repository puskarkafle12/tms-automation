"""Merolagani + Nepse Alpha cache refresh with bootstrap from daily snapshots."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from utils.external_data_sources.nepse_alpha.client import get_nepse_alpha_signals_async
from utils.external_data_sources.nepse_alpha.screener import flatten_nepse_alpha_for_screener
from utils.market_data.canonical_fields import (
    build_combined_record,
    canonicalize_merolagani_record,
)
from utils.market_data.merolagani_fields import (
    extract_symbol,
    flatten_merolagani_row,
    merge_merolagani_records,
    normalize_merolagani_record,
)
from utils.market_data.repository import (
    get_cache_symbol_count,
    load_latest_daily_stock_rows,
    log_refresh,
    upsert_screener_cache_row,
)
from utils.market_status import is_market_hours_open

logger = logging.getLogger(__name__)

MAX_CONCURRENT_FETCHES = 6
MEROLAGANI_REFRESH_INTERVAL_SECONDS = 10 * 60
NEPSE_ALPHA_REFRESH_INTERVAL_SECONDS = 10 * 60

# Backward-compatible alias used by older imports/tests.
SCREENER_REFRESH_INTERVAL_SECONDS = MEROLAGANI_REFRESH_INTERVAL_SECONDS


def _combine_records(
    symbol: str,
    merolagani_record: Optional[Dict[str, Any]],
    nepse_record: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    combined = build_combined_record(merolagani_record, nepse_record)
    combined["symbol"] = symbol.upper()
    return combined


def _store_merolagani_record(record: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return canonicalize_merolagani_record(record or {})


def _load_cached_merolagani_map(db: Session) -> Dict[str, Dict[str, Any]]:
    rows = db.execute(
        text("SELECT symbol, merolagani_data, combined_data FROM market_screener_cache")
    ).mappings().all()
    result: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        symbol = str(row["symbol"] or "").upper()
        payload = row.get("merolagani_data") or row.get("combined_data") or {}
        if isinstance(payload, str):
            payload = json.loads(payload)
        if symbol and isinstance(payload, dict):
            result[symbol] = payload
    return result


def _daily_rows_by_symbol(db: Session) -> Dict[str, Dict[str, Any]]:
    return {
        extract_symbol(row): row
        for row in load_latest_daily_stock_rows(db)
        if extract_symbol(row)
    }


def _load_existing_merolagani(db: Session, symbol: str) -> Dict[str, Any]:
    row = db.execute(
        text("SELECT merolagani_data FROM market_screener_cache WHERE symbol = :symbol"),
        {"symbol": symbol.upper()},
    ).scalar()
    if not row:
        return {}
    if isinstance(row, str):
        row = json.loads(row)
    return normalize_merolagani_record(row if isinstance(row, dict) else {})


def enrich_merolagani_from_daily_snapshot(db: Session) -> Dict[str, Any]:
    """Backfill full Merolagani detail from the latest daily snapshot into cache rows."""
    daily_by_symbol = _daily_rows_by_symbol(db)
    if not daily_by_symbol:
        return {"status": "skipped", "reason": "no_daily_snapshot"}

    symbols = [
        str(item).upper()
        for item in db.execute(text("SELECT symbol FROM market_screener_cache ORDER BY symbol")).scalars().all()
        if str(item).strip()
    ]
    if not symbols:
        return bootstrap_cache_from_daily_snapshot(db)

    updated = 0
    now = datetime.utcnow()
    for symbol in symbols:
        daily_row = daily_by_symbol.get(symbol)
        existing = _load_existing_merolagani(db, symbol)
        merged = merge_merolagani_records(
            flatten_merolagani_row(daily_row) if daily_row else None,
            existing,
        )
        if not merged:
            continue
        nepse_row = db.execute(
            text("SELECT nepse_alpha_data FROM market_screener_cache WHERE symbol = :symbol"),
            {"symbol": symbol},
        ).scalar()
        nepse_flat = None
        if nepse_row:
            if isinstance(nepse_row, str):
                nepse_row = json.loads(nepse_row)
            if isinstance(nepse_row, dict):
                nepse_flat = flatten_nepse_alpha_for_screener(nepse_row)
        stored_merolagani = _store_merolagani_record(merged)
        upsert_screener_cache_row(
            db,
            symbol=symbol,
            merolagani_data=stored_merolagani,
            combined_data=_combine_records(symbol, stored_merolagani, nepse_flat),
            merolagani_fetched_at=now,
        )
        updated += 1

    db.commit()
    if updated > 0:
        log_refresh(
            db,
            refresh_type="merolagani_cache",
            status="ok",
            symbol_count=updated,
            message=f"Enriched cache from daily snapshot ({updated} symbols)",
            started_at=now,
        )
        db.commit()
    return {"status": "ok", "symbol_count": updated, "source": "daily_snapshot_enrich"}


def bootstrap_cache_from_daily_snapshot(db: Session) -> Dict[str, Any]:
    """Seed market_screener_cache from daily snapshot or live market table."""
    if get_cache_symbol_count(db) > 0:
        return {"status": "skipped", "reason": "cache_not_empty"}

    rows = load_latest_daily_stock_rows(db)
    source = "daily_snapshot"
    if not rows:
        try:
            from services.stock_data_scrapper.scrapper import get_latest_market_rows

            rows = get_latest_market_rows()
            source = "live_market_table"
        except Exception as exc:
            logger.warning("Bootstrap live market fallback failed: %s", exc)
            return {"status": "skipped", "reason": "no_daily_snapshot"}

    if not rows:
        return {"status": "skipped", "reason": "no_daily_snapshot"}

    started_at = datetime.utcnow()
    now = datetime.utcnow()
    count = 0
    for row in rows:
        symbol = extract_symbol(row)
        if not symbol:
            continue
        record = _store_merolagani_record(flatten_merolagani_row(row))
        if not record:
            continue
        upsert_screener_cache_row(
            db,
            symbol=symbol,
            merolagani_data=record,
            combined_data=_combine_records(symbol, record, None),
            merolagani_fetched_at=now,
        )
        count += 1

    db.commit()
    log_refresh(
        db,
        refresh_type="merolagani_cache",
        status="ok",
        symbol_count=count,
        message=f"Bootstrapped cache from {source} ({count} symbols)",
        started_at=started_at,
    )
    db.commit()
    logger.info("Bootstrapped market cache from %s (%s symbols)", source, count)
    return {"status": "ok", "symbol_count": count, "source": source}


def ensure_market_cache_ready(db: Session) -> Dict[str, Any]:
    """Fast cache probe only — never scrape or enrich on the request path."""
    count = get_cache_symbol_count(db)
    if count > 0:
        return {"status": "ok", "reason": "cache_ready", "symbol_count": count}
    return {"status": "empty", "reason": "cache_empty", "symbol_count": 0}


async def _fetch_nepse_alpha_record(
    symbol: str,
    semaphore: asyncio.Semaphore,
) -> Tuple[str, Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    async with semaphore:
        try:
            payload = await get_nepse_alpha_signals_async(symbol)
            flat = flatten_nepse_alpha_for_screener(payload)
            return symbol, flat, payload
        except Exception as exc:
            logger.debug("Nepse Alpha fetch failed for %s: %s", symbol, exc)
            return symbol, None, None


async def refresh_merolagani_cache(
    db: Session,
    *,
    require_market_open: bool = True,
) -> Dict[str, Any]:
    """Refresh Merolagani live table into cache (market hours by default)."""
    if require_market_open and not is_market_hours_open():
        started_at = datetime.utcnow()
        if get_cache_symbol_count(db) == 0:
            bootstrap = bootstrap_cache_from_daily_snapshot(db)
            if bootstrap.get("status") == "ok":
                return {**bootstrap, "reason": "market_closed_used_daily_snapshot"}
        enrich = enrich_merolagani_from_daily_snapshot(db)
        if enrich.get("status") == "ok":
            return {**enrich, "reason": "market_closed_daily_enrich"}
        return {"status": "skipped", "reason": "market_closed", "detail": enrich}

    from services.stock_data_scrapper.scrapper import get_latest_market_rows

    started_at = datetime.utcnow()
    try:
        market_rows = await asyncio.to_thread(get_latest_market_rows)
        merolagani_by_symbol: Dict[str, Dict[str, Any]] = {}
        for row in market_rows:
            symbol = extract_symbol(row)
            if not symbol:
                continue
            merolagani_by_symbol[symbol] = flatten_merolagani_row(row)

        symbols = sorted(merolagani_by_symbol.keys())
        if not symbols:
            bootstrap = bootstrap_cache_from_daily_snapshot(db)
            if bootstrap.get("status") == "ok":
                return bootstrap
            raise RuntimeError("No Merolagani symbols found on latest market page")

        daily_by_symbol = _daily_rows_by_symbol(db)
        now = datetime.utcnow()
        for symbol, live_row in merolagani_by_symbol.items():
            daily_row = daily_by_symbol.get(symbol)
            existing = _load_existing_merolagani(db, symbol)
            merged = merge_merolagani_records(
                flatten_merolagani_row(daily_row) if daily_row else None,
                existing,
                live_row,
            )
            record = _store_merolagani_record(merged)
            nepse_row = db.execute(
                text("SELECT nepse_alpha_data FROM market_screener_cache WHERE symbol = :symbol"),
                {"symbol": symbol},
            ).scalar()
            nepse_flat = None
            if nepse_row:
                if isinstance(nepse_row, str):
                    nepse_row = json.loads(nepse_row)
                if isinstance(nepse_row, dict):
                    nepse_flat = flatten_nepse_alpha_for_screener(nepse_row)

            upsert_screener_cache_row(
                db,
                symbol=symbol,
                merolagani_data=record,
                combined_data=_combine_records(symbol, record, nepse_flat),
                merolagani_fetched_at=now,
            )

        db.commit()
        log_refresh(
            db,
            refresh_type="merolagani_cache",
            status="ok",
            symbol_count=len(symbols),
            message=f"Live Merolagani refresh ({len(symbols)} symbols)",
            started_at=started_at,
        )
        db.commit()
        return {"status": "ok", "symbol_count": len(symbols), "source": "live_market"}
    except Exception as exc:
        db.rollback()
        bootstrap = bootstrap_cache_from_daily_snapshot(db)
        if bootstrap.get("status") == "ok":
            return {**bootstrap, "fallback": True, "live_error": str(exc)}
        log_refresh(
            db,
            refresh_type="merolagani_cache",
            status="error",
            message=str(exc),
            started_at=started_at,
        )
        db.commit()
        logger.exception("Merolagani cache refresh failed")
        return {"status": "error", "message": str(exc)}


async def refresh_nepse_alpha_cache(
    db: Session,
    *,
    require_market_open: bool = True,
) -> Dict[str, Any]:
    """Refresh Nepse Alpha data for all cached Merolagani symbols."""
    if require_market_open and not is_market_hours_open():
        return {"status": "skipped", "reason": "market_closed"}

    bootstrap_cache_from_daily_snapshot(db)
    symbols = [
        str(item).upper()
        for item in db.execute(text("SELECT symbol FROM market_screener_cache ORDER BY symbol")).scalars().all()
        if str(item).strip()
    ]
    if not symbols:
        return {"status": "skipped", "reason": "no_symbols_in_cache"}

    started_at = datetime.utcnow()
    merolagani_by_symbol = _load_cached_merolagani_map(db)
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)
    tasks = [_fetch_nepse_alpha_record(symbol, semaphore) for symbol in symbols]
    results = await asyncio.gather(*tasks)

    loaded = 0
    failed = 0
    now = datetime.utcnow()
    for symbol, nepse_flat, nepse_raw in results:
        merolagani_record = merolagani_by_symbol.get(symbol)
        if nepse_flat is None:
            failed += 1
            if merolagani_record:
                upsert_screener_cache_row(
                    db,
                    symbol=symbol,
                    combined_data=_combine_records(symbol, merolagani_record, None),
                )
            continue
        loaded += 1
        upsert_screener_cache_row(
            db,
            symbol=symbol,
            nepse_alpha_data=nepse_raw,
            combined_data=_combine_records(symbol, merolagani_record, nepse_flat),
            nepse_alpha_fetched_at=now,
        )

    db.commit()
    log_refresh(
        db,
        refresh_type="nepse_alpha_cache",
        status="ok",
        symbol_count=len(symbols),
        message=f"Nepse Alpha loaded={loaded} failed={failed}",
        started_at=started_at,
    )
    db.commit()
    return {
        "status": "ok",
        "symbol_count": len(symbols),
        "nepse_alpha_loaded": loaded,
        "nepse_alpha_failed": failed,
    }


async def refresh_screener_cache(
    db: Session,
    *,
    force: bool = False,
    require_market_open: bool = True,
) -> Dict[str, Any]:
    """Run Merolagani then Nepse Alpha refresh (used by manual refresh endpoint)."""
    bootstrap = bootstrap_cache_from_daily_snapshot(db)
    merolagani_result = await refresh_merolagani_cache(db, require_market_open=require_market_open)
    nepse_result = await refresh_nepse_alpha_cache(db, require_market_open=require_market_open)
    return {
        "bootstrap": bootstrap,
        "merolagani": merolagani_result,
        "nepse_alpha": nepse_result,
        "force": force,
    }

