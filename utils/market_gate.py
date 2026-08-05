from typing import Dict, Optional

from utils.market_status import (
    MARKET_POLL_HOURS_LABEL,
    format_nepal_datetime,
    get_next_market_poll_start,
    get_nepal_now,
    is_market_polling_window,
)
from utils.market_live_state import get_shared_dna_session
from utils.tms import TmsUser


async def _check_tms_session(
    tms_users_instances: Dict[str, TmsUser],
) -> tuple[bool, str, Optional[bool], Optional[str], dict]:
    if not tms_users_instances:
        return False, "No logged-in TMS clients", None, None, {}

    dna = await get_shared_dna_session(tms_users_instances.values())
    return (
        dna["session_active"],
        dna["session_message"],
        dna["session_active"],
        "open" if dna["session_active"] else "closed",
        dna,
    )


async def resolve_market_gate(tms_users_instances: Optional[Dict[str, TmsUser]] = None) -> dict:
    users = tms_users_instances or {}
    now = get_nepal_now()
    polling_window = is_market_polling_window()

    if not polling_window:
        next_poll = format_nepal_datetime(get_next_market_poll_start(now))["display"]
        return {
            "can_scan": False,
            "can_execute": False,
            "phase": "waiting_hours",
            "message": f"Waiting to poll TMS market status ({MARKET_POLL_HOURS_LABEL})",
            "session_active": False,
            "diagnostic": (
                f"market gate=waiting_hours; Nepal time={format_nepal_datetime(now)['display']}; "
                f"next poll={next_poll}; loaded TMS clients={len(users)}"
            ),
        }

    session_active, session_message, market_live_from_api, exchange_phase, dna = await _check_tms_session(users)
    dna_detail = (
        f"DNA raw_status={dna.get('raw_status')}; dna_status={dna.get('dna_status')}; "
        f"cached={dna.get('cached')}; checked_clients={dna.get('checked_clients') or []}; "
        f"failed_clients={dna.get('failed_clients') or []}"
    )

    if market_live_from_api is not True:
        return {
            "can_scan": False,
            "can_execute": False,
            "phase": "waiting_exchange",
            "message": f"DNA is not SUCCESS — market scanning paused ({session_message})",
            "session_active": session_active,
            "exchange_phase": exchange_phase,
            "diagnostic": (
                f"market gate=waiting_exchange; Nepal time={format_nepal_datetime(now)['display']}; "
                f"loaded TMS clients={len(users)}; DNA={session_message}; {dna_detail}"
            ),
        }

    return {
        "can_scan": True,
        "can_execute": True,
        "phase": "active",
        "message": "Market open — scanning prices",
        "session_active": True,
        "exchange_phase": exchange_phase,
        "diagnostic": (
            f"market gate=active; Nepal time={format_nepal_datetime(now)['display']}; "
            f"loaded TMS clients={len(users)}; DNA={session_message}; {dna_detail}"
        ),
    }
