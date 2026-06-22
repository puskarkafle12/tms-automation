"""Background market-data refresh jobs (non-blocking API)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from database import SessionLocal
from utils.market_data.combined_screener import invalidate_combined_catalog_cache
from utils.market_data.daily_snapshot import run_daily_merolagani_snapshot
from utils.market_data.nepse_alpha_bulk import (
    enrich_merolagani_from_daily_snapshot,
    refresh_screener_cache,
)
from utils.market_data.repository import get_cache_status

logger = logging.getLogger(__name__)

_refresh_task: Optional[asyncio.Task] = None
_refresh_state: Dict[str, Any] = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "last_result": None,
    "error": None,
}


def get_market_refresh_status() -> Dict[str, Any]:
    running = _refresh_task is not None and not _refresh_task.done()
    return {
        "running": running,
        "started_at": _refresh_state.get("started_at"),
        "finished_at": _refresh_state.get("finished_at"),
        "last_result": _refresh_state.get("last_result"),
        "error": _refresh_state.get("error"),
    }


def start_market_refresh_background() -> bool:
    global _refresh_task
    if _refresh_task is not None and not _refresh_task.done():
        return False
    _refresh_task = asyncio.create_task(_run_market_refresh())
    return True


async def _run_market_refresh() -> None:
    started_at = datetime.utcnow()
    _refresh_state.update(
        {
            "running": True,
            "started_at": started_at.isoformat(),
            "finished_at": None,
            "error": None,
        }
    )
    db = SessionLocal()
    try:
        daily_result = await asyncio.to_thread(run_daily_merolagani_snapshot, db)
        enrich_result = await asyncio.to_thread(enrich_merolagani_from_daily_snapshot, db)
        screener_result = await refresh_screener_cache(db, force=True, require_market_open=False)
        invalidate_combined_catalog_cache()
        payload = {
            "daily_snapshot": daily_result,
            "merolagani_enrich": enrich_result,
            "screener_cache": screener_result,
            "cache_status": get_cache_status(db),
        }
        _refresh_state["last_result"] = payload
        logger.info(
            "Background market refresh finished (symbols=%s)",
            payload.get("cache_status", {}).get("symbol_count"),
        )
    except Exception as exc:
        _refresh_state["error"] = str(exc)
        logger.exception("Background market refresh failed")
    finally:
        _refresh_state["running"] = False
        _refresh_state["finished_at"] = datetime.utcnow().isoformat()
        db.close()
