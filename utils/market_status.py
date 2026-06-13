from datetime import datetime, time
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

NEPAL_TZ = ZoneInfo("Asia/Kathmandu")
MARKET_OPEN = time(9, 0)
MARKET_CLOSE = time(15, 0)
PRE_OPEN_START = time(9, 0)
# Sunday (6) through Friday (4) in Python weekday(); Saturday (5) is closed.
TRADING_WEEKDAYS = {6, 0, 1, 2, 3, 4}
MARKET_HOURS_LABEL = "Sun–Fri 9:00 AM–3:00 PM NPT"


def get_nepal_now() -> datetime:
    return datetime.now(NEPAL_TZ)


def get_market_hours_status(now: Optional[datetime] = None) -> Dict[str, bool]:
    current = now or get_nepal_now()
    is_trading_day = current.weekday() in TRADING_WEEKDAYS
    current_time = current.time()
    in_continuous = MARKET_OPEN <= current_time <= MARKET_CLOSE
    in_pre_open = PRE_OPEN_START <= current_time < MARKET_OPEN

    return {
        "is_trading_day": is_trading_day,
        "is_pre_open": is_trading_day and in_pre_open,
        "is_continuous": is_trading_day and in_continuous,
        "market_hours_open": is_trading_day and (in_continuous or in_pre_open),
    }


def format_nepal_datetime(now: Optional[datetime] = None) -> Dict[str, str]:
    current = now or get_nepal_now()
    return {
        "iso": current.isoformat(),
        "time": current.strftime("%I:%M:%S %p"),
        "date": current.strftime("%a, %d %b %Y"),
        "timezone": "Asia/Kathmandu",
    }


def parse_session_check_response(payload: Dict[str, Any]) -> Dict[str, Any]:
    status = str(payload.get("status", "")).lower()
    message = str(payload.get("message") or "").strip()
    message_lower = message.lower()
    data = payload.get("data")

    logged_off = status == "failed" or "logged off" in message_lower
    logged_in = "logged in" in message_lower
    session_active = logged_in or (not logged_off and status in {"success", "ok", "active", "open"})

    if logged_off:
        session_active = False

    if session_active:
        session_message = message if message else "DNA logged in"
    else:
        session_message = message if message else "DNA logged off"

    market_live_from_api = None
    if isinstance(data, dict):
        for key in ("marketOpen", "market_open", "isMarketOpen", "sessionActive", "isOpen"):
            if key in data:
                market_live_from_api = bool(data[key])
                break

    return {
        "session_active": session_active,
        "session_message": session_message,
        "raw_status": payload.get("status"),
        "market_live_from_api": market_live_from_api,
        "session_data": data,
    }


def is_market_hours_open(now: Optional[datetime] = None) -> bool:
    return get_market_hours_status(now)["market_hours_open"]


def is_market_live(hours: Optional[Dict[str, bool]] = None, session_active: bool = False) -> bool:
    status = hours or get_market_hours_status()
    return bool(status["market_hours_open"] and session_active)


def outside_market_hours_message() -> str:
    return f"Outside Nepal market hours ({MARKET_HOURS_LABEL})"

