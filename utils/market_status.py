from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

NEPAL_TZ = ZoneInfo("Asia/Kathmandu")
MARKET_OPEN = time(11, 0)
MARKET_CLOSE = time(15, 0)
PRE_OPEN_START = time(10, 30)
PRE_OPEN_CLOSE = time(10, 45)
MARKET_LIVE_POLL_INTERVAL_SECONDS = 3
# NEPSE moved to a Monday–Friday week in April 2026.
TRADING_WEEKDAYS = {0, 1, 2, 3, 4}
# Poll Sunday–Friday during market hours. The exchange response, not this
# calendar, decides whether scanning is allowed.
MARKET_POLL_WEEKDAYS = {0, 1, 2, 3, 4, 6}
MARKET_HOURS_LABEL = "Mon–Fri 11:00 AM–3:00 PM"
MARKET_POLL_HOURS_LABEL = "Sun–Fri 11:00 AM–3:00 PM"
PRE_OPEN_HOURS_LABEL = "Mon–Fri 10:30 AM–10:45 AM"


def get_nepal_now() -> datetime:
    return datetime.now(NEPAL_TZ)


def get_market_hours_status(now: Optional[datetime] = None) -> Dict[str, bool]:
    current = now or get_nepal_now()
    is_trading_day = current.weekday() in TRADING_WEEKDAYS
    current_time = current.time()
    in_continuous = MARKET_OPEN <= current_time <= MARKET_CLOSE
    in_pre_open = PRE_OPEN_START <= current_time <= PRE_OPEN_CLOSE

    return {
        "is_trading_day": is_trading_day,
        "is_pre_open": is_trading_day and in_pre_open,
        "is_continuous": is_trading_day and in_continuous,
        "market_hours_open": is_trading_day and in_continuous,
    }


def format_nepal_datetime(now: Optional[datetime] = None) -> Dict[str, str]:
    from utils.api_time import format_api_timestamp

    payload = format_api_timestamp(now or get_nepal_now())
    if not payload:
        return {
            "utc": "",
            "npt": "",
            "time": "",
            "date": "",
            "display": "",
            "timezone": "Asia/Kathmandu",
        }
    return payload


def get_next_market_poll_start(now: Optional[datetime] = None) -> datetime:
    """Return the next Nepal time when the app should poll TMS market status."""
    current = now or get_nepal_now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=NEPAL_TZ)
    else:
        current = current.astimezone(NEPAL_TZ)

    candidate = current.date()
    while True:
        if candidate.weekday() in MARKET_POLL_WEEKDAYS:
            open_dt = datetime.combine(candidate, MARKET_OPEN, tzinfo=NEPAL_TZ)
            close_dt = datetime.combine(candidate, MARKET_CLOSE, tzinfo=NEPAL_TZ)
            if current <= close_dt:
                return current if current >= open_dt else open_dt
        candidate += timedelta(days=1)


def nepal_date_utc_bounds(nepal_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(nepal_date, time.min, tzinfo=NEPAL_TZ)
    end = start + timedelta(days=1)
    return (
        start.astimezone(timezone.utc).replace(tzinfo=None),
        end.astimezone(timezone.utc).replace(tzinfo=None),
    )


def parse_session_check_response(payload: Dict[str, Any]) -> Dict[str, Any]:
    status = str(payload.get("status", "")).lower()
    message = str(payload.get("message") or "").strip()

    data = payload.get("data")
    dna_status = ""
    if isinstance(data, dict):
        dna_status = str(data.get("dnaStatus") or data.get("dna_status") or "").upper()

    # Match the TMS LED exactly: only status=SUCCESS turns it green.
    session_active = status.upper() == "SUCCESS"

    if session_active:
        session_message = message if message else "DNA logged in"
    else:
        session_message = message if message else "DNA logged off"

    return {
        "session_active": session_active,
        "session_message": session_message,
        "raw_status": payload.get("status"),
        "dna_status": dna_status or None,
        "market_live_from_api": None,
        "session_data": data,
    }


def parse_current_market_session_response(payload: Any) -> Dict[str, Any]:
    """Normalize TMS ``markettypes/currentSession`` into an exchange phase."""
    if not isinstance(payload, dict) or "currentSessions" not in payload:
        return {
            "verified": False,
            "phase": None,
            "market_open": None,
            "is_pre_open": False,
            "current_sessions": [],
        }

    sessions = payload.get("currentSessions")
    if not isinstance(sessions, list):
        sessions = []
    names = [
        str(session.get("sessionName") or "").strip()
        for session in sessions
        if isinstance(session, dict) and session.get("sessionName")
    ]
    normalized_names = {name.lower().replace("_", "").replace("-", "") for name in names}
    active_value = payload.get("activeStatus")
    active_status = active_value is True or (
        isinstance(active_value, str) and active_value.strip().lower() in {"true", "1", "yes", "active"}
    )

    if not active_status:
        phase = "closed"
    elif "continuous" in normalized_names:
        phase = "open"
    elif normalized_names.intersection({"preopen", "specialpreopen"}):
        phase = "pre_open"
    else:
        phase = "closed"

    return {
        "verified": True,
        "phase": phase,
        "market_open": phase == "open",
        "is_pre_open": phase == "pre_open",
        "current_sessions": names,
    }


def is_market_hours_open(now: Optional[datetime] = None) -> bool:
    return get_market_hours_status(now)["market_hours_open"]


def is_market_polling_window(now: Optional[datetime] = None) -> bool:
    current = now or get_nepal_now()
    return bool(
        current.weekday() in MARKET_POLL_WEEKDAYS
        and MARKET_OPEN <= current.time() <= MARKET_CLOSE
    )


def outside_market_hours_message() -> str:
    return f"Outside Nepal market hours ({MARKET_HOURS_LABEL}; pre-open {PRE_OPEN_HOURS_LABEL})"
