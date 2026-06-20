from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, Optional

from utils.market_status import MARKET_OPEN, NEPAL_TZ, TRADING_WEEKDAYS, get_nepal_now


def coerce_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def to_nepal(value: datetime) -> datetime:
    return coerce_utc(value).astimezone(NEPAL_TZ)


def format_api_timestamp(value: Optional[datetime]) -> Optional[Dict[str, str]]:
    if value is None:
        return None
    utc = coerce_utc(value)
    npt = utc.astimezone(NEPAL_TZ)
    utc_text = utc.isoformat().replace("+00:00", "Z")
    return {
        "utc": utc_text,
        "npt": npt.isoformat(),
        "display": npt.strftime("%b %d, %Y, %I:%M:%S %p NPT"),
        "date": npt.strftime("%Y-%m-%d"),
        "time": npt.strftime("%I:%M:%S %p"),
        "timezone": "Asia/Kathmandu",
    }


def format_api_timestamp_display(value: Optional[datetime]) -> str:
    payload = format_api_timestamp(value)
    return payload["display"] if payload else ""


def parse_nepal_datetime_local_to_utc(value: str) -> Optional[datetime]:
    """Parse HTML datetime-local style values as Nepal local time."""
    trimmed = str(value or "").strip()
    if not trimmed:
        return None
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?", trimmed)
    if match:
        year, month, day, hour, minute, second = match.groups()
        local = datetime(
            int(year),
            int(month),
            int(day),
            int(hour),
            int(minute),
            int(second or 0),
            tzinfo=NEPAL_TZ,
        )
        return local.astimezone(timezone.utc).replace(tzinfo=None)
    try:
        parsed = datetime.fromisoformat(trimmed.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=NEPAL_TZ)
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def get_server_time_payload(now: Optional[datetime] = None) -> Dict[str, Any]:
    current = now or get_nepal_now()
    formatted = format_api_timestamp(current)
    assert formatted is not None
    return {
        "now": formatted,
        "today_npt": formatted["date"],
        "timezone": formatted["timezone"],
    }


def _next_trading_day(from_date: date) -> date:
    candidate = from_date + timedelta(days=1)
    while candidate.weekday() not in TRADING_WEEKDAYS:
        candidate += timedelta(days=1)
    return candidate


def seconds_until_market_open(now: Optional[datetime] = None) -> float:
    """Seconds until the next continuous session open (11:00 NPT on a trading day)."""
    current = now or get_nepal_now()
    if current.weekday() in TRADING_WEEKDAYS and MARKET_OPEN <= current.time() <= time(15, 0):
        return 0.0

    if current.weekday() in TRADING_WEEKDAYS and current.time() < MARKET_OPEN:
        open_dt = datetime.combine(current.date(), MARKET_OPEN, tzinfo=NEPAL_TZ)
        return max(0.0, (open_dt - current).total_seconds())

    next_day = _next_trading_day(current.date())
    open_dt = datetime.combine(next_day, MARKET_OPEN, tzinfo=NEPAL_TZ)
    return max(0.0, (open_dt - current).total_seconds())
