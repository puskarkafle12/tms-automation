"""Background scheduler for daily snapshots and market-hours cache refresh."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from database import SessionLocal
from utils.market_data.daily_snapshot import run_daily_merolagani_snapshot
from utils.market_data.executor import MarketDataJobBusy, run_market_blocking
from utils.market_data.nonblocking_cache import kickoff_cache_bootstrap_if_empty
from utils.market_data.nepse_alpha_bulk import (
    MEROLAGANI_REFRESH_INTERVAL_SECONDS,
    NEPSE_ALPHA_REFRESH_INTERVAL_SECONDS,
    bootstrap_cache_from_daily_snapshot,
    refresh_merolagani_cache,
    refresh_nepse_alpha_cache,
)
from utils.market_data.repository import get_cache_symbol_count, get_last_refresh
from utils.market_status import MARKET_HOURS_LABEL, get_nepal_now, is_market_hours_open

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 60
_daily_lock = asyncio.Lock()
_merolagani_lock = asyncio.Lock()
_nepse_alpha_lock = asyncio.Lock()
_cache_bootstrap_lock = asyncio.Lock()
_scheduler_started_at: Optional[datetime] = None


def _should_refresh(last_refresh: datetime | None, interval_seconds: int) -> bool:
    if last_refresh is None:
        return True
    return datetime.utcnow() - last_refresh >= timedelta(seconds=interval_seconds)


def _seconds_until_next_refresh(last_refresh: datetime | None, interval_seconds: int) -> int:
    if last_refresh is None:
        return 0
    elapsed = (datetime.utcnow() - last_refresh).total_seconds()
    remaining = interval_seconds - elapsed
    return max(0, int(remaining))


def _log_background_task_exception(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc:
        logger.error(
            "Market data scheduler background task failed",
            exc_info=(type(exc), exc, exc.__traceback__),
        )


def get_market_data_scheduler_status(db: Session) -> Dict[str, Any]:
    """Expose scheduler timing for UI and ops checks."""
    market_open = is_market_hours_open(get_nepal_now())
    last_daily = get_last_refresh(db, "daily_snapshot")
    last_merolagani = get_last_refresh(db, "merolagani_cache")
    last_nepse = get_last_refresh(db, "nepse_alpha_cache")

    return {
        "running": True,
        "started_at": _scheduler_started_at.isoformat() if _scheduler_started_at else None,
        "check_interval_seconds": CHECK_INTERVAL_SECONDS,
        "market_hours_open": market_open,
        "market_hours_label": MARKET_HOURS_LABEL,
        "merolagani_refresh_interval_seconds": MEROLAGANI_REFRESH_INTERVAL_SECONDS,
        "nepse_alpha_refresh_interval_seconds": NEPSE_ALPHA_REFRESH_INTERVAL_SECONDS,
        "last_daily_snapshot": last_daily.isoformat() if last_daily else None,
        "last_merolagani_refresh": last_merolagani.isoformat() if last_merolagani else None,
        "last_nepse_alpha_refresh": last_nepse.isoformat() if last_nepse else None,
        "next_merolagani_refresh_in_seconds": _seconds_until_next_refresh(
            last_merolagani,
            MEROLAGANI_REFRESH_INTERVAL_SECONDS,
        ),
        "next_nepse_alpha_refresh_in_seconds": _seconds_until_next_refresh(
            last_nepse,
            NEPSE_ALPHA_REFRESH_INTERVAL_SECONDS,
        )
        if market_open
        else None,
        "merolagani_mode": "live_scrape" if market_open else "daily_snapshot_enrich",
        "nepse_alpha_mode": "live_scrape" if market_open else "paused_outside_market_hours",
    }


async def _run_daily_snapshot_if_needed() -> None:
    if _daily_lock.locked():
        return
    async with _daily_lock:
        db = SessionLocal()
        try:
            result = await run_market_blocking(
                run_daily_merolagani_snapshot,
                db,
                exclusive=True,
                skip_if_busy=True,
            )
            if result.get("status") == "ok":
                logger.info(
                    "Daily Merolagani snapshot saved (%s symbols)",
                    result.get("symbol_count"),
                )
        except MarketDataJobBusy:
            logger.info("Daily Merolagani snapshot skipped because another market job is running")
        finally:
            db.close()


async def _ensure_cache_bootstrapped() -> None:
    if _cache_bootstrap_lock.locked():
        return
    async with _cache_bootstrap_lock:
        await kickoff_cache_bootstrap_if_empty()


async def _run_merolagani_refresh_if_needed() -> None:
    market_open = is_market_hours_open(get_nepal_now())
    db = SessionLocal()
    try:
        cache_count = get_cache_symbol_count(db)
        if cache_count == 0:
            await kickoff_cache_bootstrap_if_empty()
        last_refresh = get_last_refresh(db, "merolagani_cache")
        last_daily = get_last_refresh(db, "daily_snapshot")
        if not market_open and cache_count > 0 and last_daily and last_refresh and last_refresh >= last_daily:
            return
        should_refresh = _should_refresh(last_refresh, MEROLAGANI_REFRESH_INTERVAL_SECONDS)
    finally:
        db.close()

    if not should_refresh:
        return
    if _merolagani_lock.locked():
        return

    async with _merolagani_lock:
        db = SessionLocal()
        try:
            result = await refresh_merolagani_cache(db, require_market_open=True)
            logger.info("Merolagani scheduler refresh: %s", result.get("status"))
        finally:
            db.close()


async def _run_nepse_alpha_refresh_if_needed() -> None:
    if not is_market_hours_open(get_nepal_now()):
        return
    if _nepse_alpha_lock.locked():
        return

    db = SessionLocal()
    try:
        if get_cache_symbol_count(db) == 0:
            await kickoff_cache_bootstrap_if_empty()
        last_refresh = get_last_refresh(db, "nepse_alpha_cache")
        should_refresh = _should_refresh(last_refresh, NEPSE_ALPHA_REFRESH_INTERVAL_SECONDS)
    finally:
        db.close()

    if not should_refresh:
        return

    async with _nepse_alpha_lock:
        db = SessionLocal()
        try:
            result = await refresh_nepse_alpha_cache(db, require_market_open=True)
            logger.info(
                "Nepse Alpha scheduler refresh: %s (loaded=%s failed=%s)",
                result.get("status"),
                result.get("nepse_alpha_loaded"),
                result.get("nepse_alpha_failed"),
            )
        finally:
            db.close()


async def market_data_scheduler_loop() -> None:
    global _scheduler_started_at
    _scheduler_started_at = datetime.utcnow()
    logger.info(
        "Market data scheduler started (check=%ss, merolagani=%ss, nepse=%ss)",
        CHECK_INTERVAL_SECONDS,
        MEROLAGANI_REFRESH_INTERVAL_SECONDS,
        NEPSE_ALPHA_REFRESH_INTERVAL_SECONDS,
    )
    await kickoff_cache_bootstrap_if_empty()
    await asyncio.sleep(CHECK_INTERVAL_SECONDS)

    while True:
        try:
            tasks = [
                asyncio.create_task(_run_daily_snapshot_if_needed()),
                asyncio.create_task(_ensure_cache_bootstrapped()),
                asyncio.create_task(_run_merolagani_refresh_if_needed()),
                asyncio.create_task(_run_nepse_alpha_refresh_if_needed()),
            ]
            for task in tasks:
                task.add_done_callback(_log_background_task_exception)
        except Exception:
            logger.exception("Market data scheduler iteration failed")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
