from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, List, Optional

from utils.strategies.types import MarketSnapshot, ScannerMemory


def safe_number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value) if value == value else None
    text = str(value).strip()
    if not text or text.lower() in {"-", "n/a", "na"}:
        return None
    cleaned = re.sub(r"[^0-9.\-+]", "", text.replace(",", ""))
    if not cleaned or cleaned in {".", "-", "+", "-.", "+."}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def percent_change(from_value: float, to_value: float) -> float:
    if not from_value:
        return 0.0
    return ((to_value - from_value) / from_value) * 100.0


def has_enough_scans(memory: ScannerMemory, min_count: int = 3) -> bool:
    return len(memory.last_prices) >= min_count


def is_rising(last_prices: List[float], count: int = 3) -> bool:
    if len(last_prices) < count:
        return False
    window = last_prices[-count:]
    return all(window[index] > window[index - 1] for index in range(1, len(window)))


def is_falling(last_prices: List[float], count: int = 3) -> bool:
    if len(last_prices) < count:
        return False
    window = last_prices[-count:]
    return all(window[index] < window[index - 1] for index in range(1, len(window)))


def range_position(snapshot: MarketSnapshot) -> float:
    low = snapshot.low
    high = snapshot.high
    if low is None or high is None:
        return 0.5
    span = max(high - low, 1.0)
    return (snapshot.ltp - low) / span


def is_volume_increasing(snapshot: MarketSnapshot, memory: ScannerMemory) -> bool:
    if snapshot.volume is None or memory.previous_volume is None:
        return False
    return snapshot.volume >= memory.previous_volume


def is_market_depth_available(snapshot: MarketSnapshot) -> bool:
    return bool(snapshot.top_buy_orders or snapshot.top_sell_orders)


def get_buy_pressure(snapshot: MarketSnapshot) -> Optional[float]:
    if not is_market_depth_available(snapshot):
        return None
    buy_qty = sum(level.quantity for level in snapshot.top_buy_orders[:5])
    sell_qty = sum(level.quantity for level in snapshot.top_sell_orders[:5])
    total = buy_qty + sell_qty
    if total <= 0:
        return None
    return buy_qty / total


def parse_last_traded_time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M:%S"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00").split("+")[0])
    except ValueError:
        return None


def is_fresh_trade(snapshot: MarketSnapshot, max_age_minutes: int = 15) -> bool:
    traded_at = parse_last_traded_time(snapshot.last_traded_time)
    if traded_at is None:
        return False
    return datetime.utcnow() - traded_at <= timedelta(minutes=max_age_minutes)


def append_scan_value(values: Optional[List[float]], value: Optional[float], limit: int = 10) -> List[float]:
    history = list(values or [])
    if value is not None:
        history.append(float(value))
    return history[-limit:]
