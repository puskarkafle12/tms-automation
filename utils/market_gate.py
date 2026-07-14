from typing import Dict, Optional

from utils.market_status import (
    MARKET_POLL_HOURS_LABEL,
    is_market_polling_window,
)
from utils.market_live_state import get_shared_dna_session
from utils.tms import TmsUser


async def _check_tms_session(
    tms_users_instances: Dict[str, TmsUser],
) -> tuple[bool, str, Optional[bool], Optional[str]]:
    if not tms_users_instances:
        return False, "No logged-in TMS clients", None, None

    dna = await get_shared_dna_session(tms_users_instances.values())
    return (
        dna["session_active"],
        dna["session_message"],
        dna["session_active"],
        "open" if dna["session_active"] else "closed",
    )


async def resolve_market_gate(tms_users_instances: Optional[Dict[str, TmsUser]] = None) -> dict:
    users = tms_users_instances or {}
    polling_window = is_market_polling_window()

    if not polling_window:
        return {
            "can_scan": False,
            "can_execute": False,
            "phase": "waiting_hours",
            "message": f"Waiting to poll TMS market status ({MARKET_POLL_HOURS_LABEL})",
            "session_active": False,
        }

    session_active, session_message, market_live_from_api, exchange_phase = await _check_tms_session(users)

    if market_live_from_api is not True:
        return {
            "can_scan": False,
            "can_execute": False,
            "phase": "waiting_exchange",
            "message": f"DNA is not SUCCESS — market scanning paused ({session_message})",
            "session_active": session_active,
            "exchange_phase": exchange_phase,
        }

    return {
        "can_scan": True,
        "can_execute": True,
        "phase": "active",
        "message": "Market open — scanning prices",
        "session_active": True,
        "exchange_phase": exchange_phase,
    }
