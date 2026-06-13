from typing import Dict, Optional

from utils.market_status import MARKET_HOURS_LABEL, is_market_hours_open, parse_session_check_response
from utils.tms import TmsUser


async def _check_tms_session(tms_users_instances: Dict[str, TmsUser]) -> tuple[bool, str]:
    if not tms_users_instances:
        return False, "No logged-in TMS clients"

    for tms_user in tms_users_instances.values():
        try:
            payload = await tms_user.check_exchange_session()
            parsed = parse_session_check_response(payload)
            return parsed["session_active"], parsed["session_message"]
        except Exception:
            continue

    return False, "Unable to check TMS session"


async def resolve_market_gate(tms_users_instances: Optional[Dict[str, TmsUser]] = None) -> dict:
    users = tms_users_instances or {}

    if not is_market_hours_open():
        return {
            "can_scan": False,
            "can_execute": False,
            "phase": "waiting_hours",
            "message": f"Market closed — waiting for trading hours ({MARKET_HOURS_LABEL})",
            "session_active": False,
        }

    session_active, session_message = await _check_tms_session(users)
    if not session_active:
        return {
            "can_scan": False,
            "can_execute": False,
            "phase": "waiting_session",
            "message": f"Waiting for TMS session — {session_message}",
            "session_active": False,
        }

    return {
        "can_scan": True,
        "can_execute": True,
        "phase": "active",
        "message": "Market open — scanning prices",
        "session_active": True,
    }
