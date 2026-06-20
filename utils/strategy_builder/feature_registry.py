from __future__ import annotations

from typing import Any, Dict, List, Optional

# Market-depth query fields are not supported for strategy queries (TMS depth is unreliable
# outside live session). Use live quote fields (ltp, volume, high, low) instead.
MARKET_DEPTH_FIELD_KEYS = {
    "market_depth_available",
    "best_bid",
    "best_ask",
    "spread",
    "spread_percent",
    "top_buy_quantity",
    "top_sell_quantity",
    "total_buy_quantity",
    "total_sell_quantity",
    "buy_sell_quantity_ratio",
    "order_book_imbalance",
}

MARKET_DEPTH_FUNCTIONS = {
    "DEPTH_QUANTITY",
    "DEPTH_ORDER_COUNT",
    "DEPTH_IMBALANCE",
    "DEPTH_IMBALANCE_REMAINS_ABOVE",
    "DEPTH_IMBALANCE_REMAINS_BELOW",
    "DEPTH_PRESSURE_TREND",
    "SPREAD_REMAINS_BELOW",
}

RUNTIME_FUNCTIONS = {
    "REFERENCE",
    "PREVIOUS", "CHANGE", "CHANGE_PERCENT", "CONSECUTIVE_DROPS", "CONSECUTIVE_RISES",
    "CROSSES_ABOVE", "CROSSES_BELOW", "REMAINS_ABOVE", "REMAINS_BELOW",
    "TRUE_FOR_SCANS", "MATCHES_IN_LAST", "CHANGED_TO", "CHANGED_FROM_TO",
    "AVERAGE", "MIN_VALUE", "MAX_VALUE", "SUM_VALUE", "STDDEV", "SLOPE", "TREND",
    "SECTOR_POSITION",
    "UNIVERSE_PERCENTILE", "SECTOR_PERCENTILE",
}

PARSER_ONLY_FUNCTIONS: set[str] = set()

# Ranking functions need a multi-symbol universe scan; single-symbol scheduled monitoring cannot supply them.
SCHEDULE_UNSUPPORTED_FUNCTIONS = {
    "UNIVERSE_PERCENTILE",
    "SECTOR_PERCENTILE",
}

UNSUPPORTED_DATA_FIELDS = {"technical_adx", "adx", *MARKET_DEPTH_FIELD_KEYS}


def classify_field(field_name: str) -> str:
    if field_name.lower() in UNSUPPORTED_DATA_FIELDS or field_name in MARKET_DEPTH_FIELD_KEYS:
        return "UNSUPPORTED_DATA"
    return "SUPPORTED_RUNTIME"


def classify_function(name: str) -> str:
    upper = (name or "").upper()
    if upper in MARKET_DEPTH_FUNCTIONS:
        return "UNSUPPORTED_DATA"
    if upper in RUNTIME_FUNCTIONS:
        return "SUPPORTED_RUNTIME"
    if upper in PARSER_ONLY_FUNCTIONS:
        return "SUPPORTED_PARSER_ONLY"
    return "UNSUPPORTED_DATA"
