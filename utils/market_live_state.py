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
    "checked_clients": [],
    "failed_clients": [],
}


def _get_dna_lock() -> asyncio.Lock:
    global _dna_lock
    if _dna_lock is None:
        _dna_lock = asyncio.Lock()
    return _dna_lock


def _dna_fresh(now: float) -> bool:
    return bool(_dna_checked_at and now - _dna_checked_at < MARKET_LIVE_POLL_INTERVAL_SECONDS)


def get_shared_dna_session_snapshot() -> dict[str, Any]:
    """Return the latest market-live decision without making a TMS request."""
    now = time.monotonic()
    return {
        **_dna_state,
        "cached": _dna_fresh(now),
        "cache_age_seconds": round(now - _dna_checked_at, 2) if _dna_checked_at else None,
    }


async def get_shared_dna_session(tms_users: Iterable[Any]) -> dict[str, Any]:
    """Return one DNA result shared by every account for three seconds."""
    global _dna_checked_at, _dna_state

    now = time.monotonic()
    if _dna_fresh(now):
        return {**_dna_state, "cached": True, "cache_age_seconds": round(now - _dna_checked_at, 2)}

    async with _get_dna_lock():
        now = time.monotonic()
        if _dna_fresh(now):
            return {**_dna_state, "cached": True, "cache_age_seconds": round(now - _dna_checked_at, 2)}

        next_state = {
            "session_active": False,
            "session_message": "Unable to check TMS DNA session",
            "raw_status": None,
            "dna_status": None,
            "market_live_from_api": None,
            "session_data": None,
            "checked_clients": [],
            "failed_clients": [],
        }
        for tms_user in tms_users:
            client_id = str(getattr(tms_user, "client_id", "unknown"))
            try:
                payload = await tms_user.check_exchange_session()
                candidate = parse_session_check_response(payload)
                candidate["checked_clients"] = [*next_state["checked_clients"], client_id]
                candidate["failed_clients"] = list(next_state["failed_clients"])
                next_state = candidate
                # DNA is exchange-wide, but one stale account may report logged
                # out. Keep checking the remaining authenticated accounts and
                # allow monitoring when any one of them confirms SUCCESS.
                if candidate["session_active"]:
                    break
            except Exception as exc:
                next_state["failed_clients"] = [
                    *next_state["failed_clients"],
                    f"{client_id}: {type(exc).__name__}: {exc}"[:300],
                ]
                continue

        _dna_state = dict(next_state)
        _dna_checked_at = time.monotonic()
        return {**_dna_state, "cached": False, "cache_age_seconds": 0.0}


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
        "checked_clients": [],
        "failed_clients": [],
    }
