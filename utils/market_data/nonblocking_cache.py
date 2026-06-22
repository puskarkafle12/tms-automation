"""Non-blocking market cache warm-up (never scrape on the API event loop)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from database import SessionLocal
from utils.market_data.nepse_alpha_bulk import bootstrap_cache_from_daily_snapshot
from utils.market_data.repository import get_cache_symbol_count

logger = logging.getLogger(__name__)

_bootstrap_task: Optional[asyncio.Task] = None
_bootstrap_lock = asyncio.Lock()


def _read_symbol_count() -> int:
    db = SessionLocal()
    try:
        return get_cache_symbol_count(db)
    finally:
        db.close()


def get_bootstrap_status() -> Dict[str, Any]:
    running = _bootstrap_task is not None and not _bootstrap_task.done()
    return {"running": running}


async def kickoff_cache_bootstrap_if_empty() -> Dict[str, Any]:
    """Fast cache check; heavy bootstrap always runs in a background task."""
    count = await asyncio.to_thread(_read_symbol_count)
    if count > 0:
        return {"status": "ready", "symbol_count": count, "bootstrap_started": False}

    started = await _start_bootstrap_task()
    return {"status": "warming", "symbol_count": 0, "bootstrap_started": started}


async def _start_bootstrap_task() -> bool:
    global _bootstrap_task
    async with _bootstrap_lock:
        if _bootstrap_task is not None and not _bootstrap_task.done():
            return False
        _bootstrap_task = asyncio.create_task(_run_bootstrap_task())
        return True


async def _run_bootstrap_task() -> None:
    def _work() -> Dict[str, Any]:
        db = SessionLocal()
        try:
            return bootstrap_cache_from_daily_snapshot(db)
        finally:
            db.close()

    try:
        result = await asyncio.to_thread(_work)
        logger.info("Background market cache bootstrap finished: %s", result)
    except Exception:
        logger.exception("Background market cache bootstrap failed")
