"""Flatten Merolagani rows into screener-friendly field keys."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from utils.strategies.helpers import safe_number

MEROLAGANI_FIELD_MAP = {
    "Symbol": "symbol",
    "LTP": "ml_ltp",
    "% Change": "ml_percent_change",
    "Open": "ml_open",
    "High": "ml_high",
    "Low": "ml_low",
    "Qty.": "ml_quantity",
    "Shares Outstanding": "ml_shares_outstanding",
    "Market Price": "ml_market_price",
    "180 Day Average": "ml_avg_180d",
    "120 Day Average": "ml_avg_120d",
    "1 Year Yield": "ml_one_year_yield",
    "EPS": "ml_eps",
    "P/E Ratio": "ml_pe_ratio",
    "Book Value": "ml_book_value",
    "PBV": "ml_pbv",
    "30-Day Avg Volume": "ml_avg_volume_30d",
    "Market Capitalization": "ml_market_cap",
    "Last Traded On": "ml_last_traded_on",
    "Sector": "ml_sector",
    "Listing Date": "ml_listing_date",
}

MEROLAGANI_NUMERIC_KEYS = {
    "ml_ltp",
    "ml_percent_change",
    "ml_open",
    "ml_high",
    "ml_low",
    "ml_quantity",
    "ml_shares_outstanding",
    "ml_market_price",
    "ml_avg_180d",
    "ml_avg_120d",
    "ml_one_year_yield",
    "ml_eps",
    "ml_pe_ratio",
    "ml_book_value",
    "ml_pbv",
    "ml_avg_volume_30d",
    "ml_market_cap",
}

MEROLAGANI_FIELD_CATALOG: List[Dict[str, Any]] = [
    {"key": "ml_ltp", "label": "LTP (Merolagani)", "category": "Merolagani", "type": "number"},
    {"key": "ml_percent_change", "label": "% Change (Merolagani)", "category": "Merolagani", "type": "number"},
    {"key": "ml_open", "label": "Open (Merolagani)", "category": "Merolagani", "type": "number"},
    {"key": "ml_high", "label": "High (Merolagani)", "category": "Merolagani", "type": "number"},
    {"key": "ml_low", "label": "Low (Merolagani)", "category": "Merolagani", "type": "number"},
    {"key": "ml_quantity", "label": "Quantity (Merolagani)", "category": "Merolagani", "type": "number"},
    {"key": "ml_shares_outstanding", "label": "Shares Outstanding", "category": "Merolagani", "type": "number"},
    {"key": "ml_market_price", "label": "Market Price", "category": "Merolagani", "type": "number"},
    {"key": "ml_avg_180d", "label": "180 Day Average", "category": "Merolagani", "type": "number"},
    {"key": "ml_avg_120d", "label": "120 Day Average", "category": "Merolagani", "type": "number"},
    {"key": "ml_one_year_yield", "label": "1 Year Yield (Merolagani)", "category": "Merolagani", "type": "number"},
    {"key": "ml_eps", "label": "EPS (Merolagani)", "category": "Merolagani", "type": "number"},
    {"key": "ml_pe_ratio", "label": "P/E Ratio (Merolagani)", "category": "Merolagani", "type": "number"},
    {"key": "ml_book_value", "label": "Book Value", "category": "Merolagani", "type": "number"},
    {"key": "ml_pbv", "label": "PBV (Merolagani)", "category": "Merolagani", "type": "number"},
    {"key": "ml_avg_volume_30d", "label": "30-Day Avg Volume", "category": "Merolagani", "type": "number"},
    {"key": "ml_market_cap", "label": "Market Capitalization", "category": "Merolagani", "type": "number"},
    {"key": "ml_sector", "label": "Sector", "category": "Merolagani", "type": "text"},
    {"key": "ml_listing_date", "label": "Listing Date", "category": "Merolagani", "type": "text"},
    {"key": "ml_last_traded_on", "label": "Last Traded On", "category": "Merolagani", "type": "text"},
]


def _parse_numeric(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text in {"-", "N/A", "n/a"}:
        return None
    cleaned = text.replace("%", "").replace(",", "")
    return safe_number(cleaned)


MEROLAGANI_DISPLAY_COLUMNS = ["symbol", *[item["key"] for item in MEROLAGANI_FIELD_CATALOG]]

_RAW_MEROLAGANI_SOURCE_KEYS = {
    "Symbol",
    "LTP",
    "% Change",
    "Open",
    "High",
    "Low",
    "Qty.",
}

_LIVE_MEROLAGANI_KEYS = {
    "ml_ltp",
    "ml_percent_change",
    "ml_open",
    "ml_high",
    "ml_low",
    "ml_quantity",
}


def normalize_merolagani_record(record: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not record:
        return {}
    if _RAW_MEROLAGANI_SOURCE_KEYS.intersection(record.keys()):
        return flatten_merolagani_row(record)
    normalized = dict(record)
    symbol = extract_symbol(normalized)
    if symbol:
        normalized["symbol"] = symbol
    return normalized


def merge_merolagani_records(*records: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge daily detail + cached + live rows. Live price fields win on conflict."""
    merged: Dict[str, Any] = {}
    for record in records:
        if not record:
            continue
        normalized = normalize_merolagani_record(record)
        for key, value in normalized.items():
            if value is None:
                continue
            if key == "symbol":
                merged["symbol"] = value
                continue
            if key in _LIVE_MEROLAGANI_KEYS or key not in merged:
                merged[key] = value
    return merged


def extract_symbol(row: Dict[str, Any]) -> str:
    symbol = str(row.get("Symbol") or row.get("symbol") or "").strip().upper()
    if symbol:
        return symbol
    for key, value in row.items():
        if str(key).lower() == "symbol":
            return str(value or "").strip().upper()
    return ""


def flatten_merolagani_row(row: Dict[str, Any]) -> Dict[str, Any]:
    record: Dict[str, Any] = {"symbol": extract_symbol(row)}
    for source_key, target_key in MEROLAGANI_FIELD_MAP.items():
        if source_key not in row:
            continue
        raw = row.get(source_key)
        if target_key in MEROLAGANI_NUMERIC_KEYS:
            numeric = _parse_numeric(raw)
            if numeric is not None:
                record[target_key] = numeric
        elif raw is not None and str(raw).strip():
            record[target_key] = str(raw).strip()

    eps_match = re.search(r"([-+]?\d*\.\d+|\d+)", str(row.get("EPS") or ""))
    if eps_match and "ml_eps" not in record:
        record["ml_eps"] = safe_number(eps_match.group())

    record["symbol"] = extract_symbol(row)
    return record
