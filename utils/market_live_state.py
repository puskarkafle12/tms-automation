from __future__ import annotations

import asyncio
import time
from typing import Any, Iterable, Optional

from utils.market_status import (
    MARKET_LIVE_POLL_INTERVAL_SECONDS,
    parse_session_check_response,
)

_dna_lock: Optional[asyncio.Lock] = None
_dna_checked_at = 0.0
_dna_state: dict[str, Any] = {
    "session_active": False,
    "session_message": "Unable to check TMS DNA session",
    "raw_status": None,
    "dna_status": None,
    "market_live_from_api": None,
    "session_data": None,
}


def _get_dna_lock() -> asyncio.Lock:
    global _dna_lock
    if _dna_lock is None:
        _dna_lock = asyncio.Lock()
    return _dna_lock


def _dna_fresh(now: float) -> bool:
    return bool(_dna_checked_at and now - _dna_checked_at < MARKET_LIVE_POLL_INTERVAL_SECONDS)


async def get_shared_dna_session(tms_users: Iterable[Any]) -> dict[str, Any]:
    """Return one DNA result shared by every account for three seconds."""
    global _dna_checked_at, _dna_state

    now = time.monotonic()
    if _dna_fresh(now):
        return dict(_dna_state)

    async with _get_dna_lock():
        now = time.monotonic()
        if _dna_fresh(now):
            return dict(_dna_state)

        next_state = {
            "session_active": False,
            "session_message": "Unable to check TMS DNA session",
            "raw_status": None,
            "dna_status": None,
            "market_live_from_api": None,
            "session_data": None,
        }
        for tms_user in tms_users:
            try:
                payload = await tms_user.check_exchange_session()
                next_state = parse_session_check_response(payload)
                break
            except Exception:
                continue

        _dna_state = dict(next_state)
        _dna_checked_at = time.monotonic()
        return dict(_dna_state)


def reset_shared_market_session() -> None:
    """Clear shared state for tests and process lifecycle resets."""
    global _dna_checked_at, _dna_state, _dna_lock
    _dna_checked_at = 0.0
    _dna_lock = None
    _dna_state = {
        "session_active": False,
        "session_message": "Unable to check TMS DNA session",
        "raw_status": None,
        "dna_status": None,
        "market_live_from_api": None,
        "session_data": None,
    }
