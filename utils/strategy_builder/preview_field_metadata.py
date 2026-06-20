from __future__ import annotations

from typing import Any, Dict, Optional

from utils.strategy_builder.strategy_fields import ENUM_VALUES, get_field_metadata

DIRECT_PRICE_FIELDS = frozenset(
    {
        "ltp",
        "open",
        "high",
        "low",
        "previous_close",
        "best_bid",
        "best_ask",
        "entry_price",
        "effective_stop_price",
        "fixed_stop_loss_price",
        "current_trailing_stop",
        "highest_price_since_entry",
        "fifty_two_week_high",
        "fifty_two_week_low",
        "all_time_high",
        "all_time_low",
    }
)

PRICE_CONVERSION_BY_FIELD = {
    "position_in_52_week_range_percent": "52_week_position",
    "distance_from_52_week_high_percent": "distance_from_52w_high",
    "distance_from_52_week_low_percent": "distance_from_52w_low",
    "position_in_intraday_range_percent": "intraday_position",
    "distance_from_day_high_percent": "distance_from_day_high",
    "distance_from_day_low_percent": "distance_from_day_low",
}


def infer_formatter(field_key: str, meta: Optional[Dict[str, Any]] = None) -> str:
    meta = meta or get_field_metadata(field_key) or {}
    data_type = str(meta.get("data_type") or "decimal")
    if field_key in DIRECT_PRICE_FIELDS or field_key in {"reference_ltp", "trigger_price"}:
        return "price"
    if field_key in ENUM_VALUES or data_type == "text" and field_key.startswith("technical_"):
        if field_key in ENUM_VALUES:
            return "enum"
        return "text"
    if data_type == "boolean":
        return "boolean"
    if field_key.endswith("_percent") or "percent" in field_key:
        return "percentage"
    if field_key in {"volume", "top_buy_quantity", "top_sell_quantity", "total_buy_quantity", "total_sell_quantity", "depth_supported_quantity"}:
        return "integer"
    return "decimal"


def infer_unit(field_key: str, meta: Optional[Dict[str, Any]] = None) -> str:
    formatter = infer_formatter(field_key, meta)
    if formatter == "price":
        return "npr"
    if formatter == "percentage":
        return "percent"
    if formatter == "integer":
        return "shares"
    if formatter == "enum":
        return "enum"
    if formatter == "boolean":
        return "boolean"
    if formatter == "text":
        return "text"
    return "indicator"


def infer_price_conversion(field_key: str) -> Optional[str]:
    if field_key in DIRECT_PRICE_FIELDS:
        return "direct"
    return PRICE_CONVERSION_BY_FIELD.get(field_key)


def field_display_name(field_key: str) -> str:
    meta = get_field_metadata(field_key) or {}
    return str(meta.get("label") or field_key.replace("_", " ").title())


def operator_display(operator: str) -> str:
    mapping = {
        "eq": "=",
        "neq": "≠",
        "gt": ">",
        "gte": "≥",
        "lt": "<",
        "lte": "≤",
        "between": "between",
        "not_between": "not between",
        "in": "in",
        "not_in": "not in",
        "contains": "contains",
        "not_contains": "not contains",
        "changed_to": "changes to",
        "changed_from_to": "changes from",
    }
    return mapping.get(str(operator or "").lower(), str(operator or ""))
