from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

from utils.strategies.helpers import parse_nepse_stat_number, safe_number


def _parse_week_range(raw: Any) -> Tuple[Optional[float], Optional[float]]:
    if raw is None:
        return None, None
    text = str(raw).strip()
    if not text:
        return None, None
    numbers = re.findall(r"\d[\d,]*(?:\.\d+)?", text)
    values = [safe_number(item) for item in numbers]
    values = [item for item in values if item is not None]
    if len(values) >= 2:
        high = float(values[0])
        low = float(values[1])
        if high < low:
            high, low = low, high
        return high, low
    if len(values) == 1:
        return float(values[0]), None
    return None, None


def extract_week_range_from_stats(stats: Optional[Dict[str, Any]]) -> Tuple[Optional[float], Optional[float]]:
    """Extract 52-week high/low from Nepse Alpha statistical_performance keys."""
    if not stats:
        return None, None
    preferred_keys = (
        "52_weeks_high_low",
        "52_week_high_low",
    )
    for key in preferred_keys:
        high, low = _parse_week_range(stats.get(key))
        if high is not None and low is not None:
            return high, low
    for key, raw in stats.items():
        normalized_key = str(key or "").lower()
        if "52" not in normalized_key or "week" not in normalized_key:
            continue
        high, low = _parse_week_range(raw)
        if high is not None and low is not None:
            return high, low
    return None, None


def extract_price_stat_from_stats(stats: Optional[Dict[str, Any]], *preferred_keys: str) -> Optional[float]:
    """Resolve a Nepse Alpha statistical price field with exact and fuzzy key matching."""
    if not stats:
        return None
    for key in preferred_keys:
        if key in stats and stats[key] not in (None, ""):
            value = parse_nepse_stat_number(stats[key])
            if value is not None:
                return value
    wanted = {key.lower() for key in preferred_keys}
    for key, raw in stats.items():
        normalized_key = str(key or "").lower()
        if normalized_key in wanted:
            value = parse_nepse_stat_number(raw)
            if value is not None:
                return value
        for preferred in preferred_keys:
            parts = [part for part in preferred.lower().split("_") if part]
            if parts and all(part in normalized_key for part in parts):
                value = parse_nepse_stat_number(raw)
                if value is not None:
                    return value
    return None
