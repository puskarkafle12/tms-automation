"""Nepse Alpha stock screener: flatten signals, cache, and apply dynamic filters."""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from utils.external_data_sources.nepse_alpha.client import get_nepse_alpha_signals_async
from utils.strategies.helpers import safe_number

SCREENER_CACHE_TTL_SECONDS = 5 * 60
_MAX_CONCURRENT_FETCHES = 6

_screener_cache: Dict[str, Dict[str, Any]] = {}


def _slug_indicator(label: str) -> str:
    cleaned = re.sub(r"\s+", " ", (label or "").strip()).lower()
    cleaned = cleaned.replace("%b", "percent_b")
    cleaned = re.sub(r"[^a-z0-9]+", "_", cleaned)
    return cleaned.strip("_")


def _parse_sma_status(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    lowered = value.lower()
    if "below" in lowered:
        return "below"
    if "above" in lowered:
        return "above"
    return value.strip() or None


def _parse_stat_number(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    text = re.sub(r"^(npr\.?|rs\.?)\s*", "", text, flags=re.IGNORECASE)
    return safe_number(text)


def _week_range_parts(raw: Optional[str]) -> Tuple[Optional[float], Optional[float]]:
    if not raw:
        return None, None
    parts = re.split(r"[/]", str(raw))
    if len(parts) < 2:
        return _parse_stat_number(raw), None
    return _parse_stat_number(parts[0]), _parse_stat_number(parts[1])


def flatten_nepse_alpha_for_screener(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Convert parsed Nepse Alpha payload into a flat filterable record."""
    symbol = str(payload.get("symbol") or "").upper()
    stats = payload.get("statistical_performance") or {}
    week_high, week_low = _week_range_parts(stats.get("52_weeks_high_low") or stats.get("52_week_high_low"))

    record: Dict[str, Any] = {
        "symbol": symbol,
        "fetched_at": payload.get("fetched_at"),
        "alpha_annualized": safe_number(stats.get("alpha_anualized") or stats.get("alpha_annualized")),
        "beta_3_month": safe_number(stats.get("beta_3_month")),
        "sharpe_ratio_annualized": safe_number(stats.get("sharpe_ratio_anualized") or stats.get("sharpe_ratio_annualized")),
        "daily_var_95": safe_number(stats.get("daily_var_95_ci") or stats.get("daily_var_95")),
        "volatility_50d": _parse_stat_number(stats.get("50d")),
        "one_year_yield": safe_number(stats.get("1_year_yield")),
        "fifty_two_week_high": week_high,
        "fifty_two_week_low": week_low,
        "ltp": _parse_stat_number(stats.get("ltp")),
        "all_time_high": _parse_stat_number(stats.get("all_time_high")),
        "all_time_low": _parse_stat_number(stats.get("all_time_low")),
    }

    for section_key in ("fundamental_signals", "technical_signals"):
        section_prefix = "fundamental" if section_key == "fundamental_signals" else "technical"
        for row in payload.get(section_key) or []:
            indicator = str(row.get("indicator") or "").strip()
            if not indicator:
                continue
            slug = _slug_indicator(indicator)
            prefix = f"{section_prefix}_{slug}"

            if row.get("signal") is not None:
                signal = str(row.get("signal") or "").strip()
                if "sma" in slug:
                    record[prefix] = _parse_sma_status(signal)
                elif slug == "macd":
                    record[prefix] = signal
                else:
                    record[prefix] = signal
                continue

            symbol_value = row.get("symbol_value")
            if symbol_value is not None:
                numeric = safe_number(symbol_value)
                record[prefix] = numeric if numeric is not None else str(symbol_value).strip()

            sector_high = row.get("sector_high") or {}
            sector_low = row.get("sector_low") or {}
            if isinstance(sector_high, dict):
                high_val = safe_number(sector_high.get("value"))
                if high_val is not None:
                    record[f"{prefix}_sector_high"] = high_val
            if isinstance(sector_low, dict):
                low_val = safe_number(sector_low.get("value"))
                if low_val is not None:
                    record[f"{prefix}_sector_low"] = low_val

    return record


FIELD_CATALOG: List[Dict[str, Any]] = [
    {"key": "alpha_annualized", "label": "Alpha Annualized (%)", "category": "Statistical", "type": "number"},
    {"key": "beta_3_month", "label": "Beta 3 Month", "category": "Statistical", "type": "number"},
    {"key": "sharpe_ratio_annualized", "label": "Sharpe Ratio Annualized", "category": "Statistical", "type": "number"},
    {"key": "daily_var_95", "label": "Daily VAR @95%CI (%)", "category": "Statistical", "type": "number"},
    {"key": "volatility_50d", "label": "50D Volatility", "category": "Statistical", "type": "number"},
    {"key": "one_year_yield", "label": "1 Year Yield (%)", "category": "Statistical", "type": "number"},
    {"key": "fifty_two_week_high", "label": "52 Week High", "category": "Statistical", "type": "number"},
    {"key": "fifty_two_week_low", "label": "52 Week Low", "category": "Statistical", "type": "number"},
    {"key": "ltp", "label": "LTP", "category": "Statistical", "type": "number"},
    {"key": "all_time_high", "label": "All Time High", "category": "Statistical", "type": "number"},
    {"key": "all_time_low", "label": "All Time Low", "category": "Statistical", "type": "number"},
    {"key": "fundamental_pe_ttm", "label": "PE TTM", "category": "Fundamental", "type": "number"},
    {"key": "fundamental_pbv", "label": "PBV", "category": "Fundamental", "type": "number"},
    {"key": "fundamental_roe_ttm", "label": "ROE TTM (%)", "category": "Fundamental", "type": "number"},
    {"key": "fundamental_ps_ttm", "label": "PS TTM", "category": "Fundamental", "type": "number"},
    {"key": "fundamental_peg_3_5_yrs", "label": "PEG (3-5 yrs)", "category": "Fundamental", "type": "number"},
    {"key": "fundamental_roa_ttm", "label": "ROA TTM (%)", "category": "Fundamental", "type": "number"},
    {"key": "fundamental_dividend_yield", "label": "Dividend Yield (%)", "category": "Fundamental", "type": "number"},
    {"key": "fundamental_payout_ratio", "label": "Payout Ratio (%)", "category": "Fundamental", "type": "number"},
    {"key": "fundamental_qoq_earnings_growth", "label": "QOQ Earnings Growth (%)", "category": "Fundamental", "type": "number"},
    {"key": "fundamental_yoy_earnings_growth", "label": "YOY Earnings Growth (%)", "category": "Fundamental", "type": "number"},
    {"key": "fundamental_distance_from_graham_number", "label": "Distance From Graham Number (%)", "category": "Fundamental", "type": "number"},
    {"key": "fundamental_debt_to_equity", "label": "Debt to Equity", "category": "Fundamental", "type": "number"},
    {"key": "technical_rsi_14", "label": "RSI 14", "category": "Technical", "type": "number"},
    {"key": "technical_mfi_14", "label": "MFI 14", "category": "Technical", "type": "number"},
    {"key": "technical_price_relative_strength", "label": "Price Relative Strength (%)", "category": "Technical", "type": "number"},
    {"key": "technical_percent_b", "label": "%B", "category": "Technical", "type": "number"},
    {"key": "technical_stochastic_14", "label": "Stochastic 14", "category": "Technical", "type": "number"},
    {"key": "technical_macd", "label": "MACD", "category": "Technical", "type": "text"},
    {"key": "technical_sma_10", "label": "SMA 10", "category": "Technical", "type": "text"},
    {"key": "technical_sma_20", "label": "SMA 20", "category": "Technical", "type": "text"},
    {"key": "technical_sma_50", "label": "SMA 50", "category": "Technical", "type": "text"},
    {"key": "technical_sma_200", "label": "SMA 200", "category": "Technical", "type": "text"},
    {"key": "technical_volume_trend", "label": "Volume Trend", "category": "Technical", "type": "text"},
    {"key": "technical_3m_price_tend", "label": "3M Price Trend", "category": "Technical", "type": "text"},
]

NUMERIC_OPERATORS = ["gt", "gte", "lt", "lte", "eq", "neq", "between"]
TEXT_OPERATORS = ["eq", "neq", "contains", "in"]

# Colloquial names users/AI may use — mapped only when the canonical key exists in FIELD_CATALOG.
COLLOQUIAL_FIELD_ALIASES: Dict[str, str] = {
    "pe": "fundamental_pe_ttm",
    "pe_ratio": "fundamental_pe_ttm",
    "pbv": "fundamental_pbv",
    "pb_ratio": "fundamental_pbv",
    "roe": "fundamental_roe_ttm",
    "roa": "fundamental_roa_ttm",
    "rsi": "technical_rsi_14",
    "mfi": "technical_mfi_14",
    "macd": "technical_macd",
    "beta": "beta_3_month",
    "sharpe": "sharpe_ratio_annualized",
    "sharpe_ratio": "sharpe_ratio_annualized",
    "alpha": "alpha_annualized",
    "volatility": "volatility_50d",
    "ltp_price": "ltp",
    "price": "ltp",
    "dividend_yield": "fundamental_dividend_yield",
    "debt_equity": "fundamental_debt_to_equity",
    "peg": "fundamental_peg_3_5_yrs",
}

VALID_FILTER_KEYS = {item["key"] for item in FIELD_CATALOG}
NON_FILTERABLE_RESULT_COLUMNS = ["rank", "symbol", "cached", "fetched_at"]

# Finance terms that are NOT available in the Nepse Alpha screener API (reject if user asks).
UNSUPPORTED_USER_TERMS = [
    "market_cap",
    "marketcap",
    "market capitalization",
    "sector",
    "sector_high",
    "sector_low",
    "eps",
    "earnings_per_share",
    "company_name",
    "name",
    "ticker",
    "volume",
    "turnover",
    "open",
    "high",
    "low",
    "close",
    "ohlc",
    "news",
    "float",
    "shares_outstanding",
]


def build_field_aliases() -> Dict[str, str]:
    """Lowercase alias -> canonical field key (used by query parser and AI prompt)."""
    aliases: Dict[str, str] = {}
    for item in FIELD_CATALOG:
        key = item["key"]
        aliases[key.lower()] = key
        label = re.sub(r"[^a-z0-9]+", "_", item["label"].lower()).strip("_")
        if label:
            aliases.setdefault(label, key)
    for alias, key in COLLOQUIAL_FIELD_ALIASES.items():
        if key in VALID_FILTER_KEYS:
            aliases.setdefault(alias.lower(), key)
    return aliases


def get_field_catalog() -> List[Dict[str, Any]]:
    catalog = [dict(item, operators=NUMERIC_OPERATORS if item["type"] == "number" else TEXT_OPERATORS) for item in FIELD_CATALOG]
    return catalog


def get_screener_query_spec() -> Dict[str, Any]:
    """Metadata for SQL-like query UI and ChatGPT prompt generation."""
    catalog = get_field_catalog()
    keys = [item["key"] for item in catalog]
    alias_map = build_field_aliases()
    aliases_by_key: Dict[str, List[str]] = {key: [] for key in keys}
    for alias, canonical in sorted(alias_map.items()):
        if canonical in aliases_by_key and alias != canonical.lower():
            aliases_by_key[canonical].append(alias)

    return {
        "allowed_filter_keys": keys,
        "result_columns": ["rank", "symbol", *keys],
        "non_filterable_columns": list(NON_FILTERABLE_RESULT_COLUMNS),
        "unsupported_user_terms": list(UNSUPPORTED_USER_TERMS),
        "numeric_operators": list(NUMERIC_OPERATORS),
        "text_operators": list(TEXT_OPERATORS),
        "field_aliases": aliases_by_key,
        "alias_map": alias_map,
        "limit_default": 25,
        "limit_max": 500,
        "default_rank_by": "alpha_annualized",
        "default_rank_direction": "desc",
    }


def _coerce_filter_value(raw: Any) -> Any:
    if isinstance(raw, list):
        return [safe_number(item) if safe_number(item) is not None else item for item in raw]
    numeric = safe_number(raw)
    return numeric if numeric is not None else raw


def _match_numeric(actual: Any, operator: str, expected: Any) -> bool:
    value = safe_number(actual)
    if value is None:
        return False
    op = (operator or "gte").lower()
    if op == "between":
        bounds = expected if isinstance(expected, list) else []
        if len(bounds) < 2:
            return False
        low = safe_number(bounds[0])
        high = safe_number(bounds[1])
        if low is None or high is None:
            return False
        return low <= value <= high
    target = safe_number(expected)
    if target is None:
        return False
    if op == "gt":
        return value > target
    if op == "gte":
        return value >= target
    if op == "lt":
        return value < target
    if op == "lte":
        return value <= target
    if op == "eq":
        return value == target
    if op == "neq":
        return value != target
    return False


def _match_text(actual: Any, operator: str, expected: Any) -> bool:
    if actual is None:
        return False
    actual_text = str(actual).strip().lower()
    op = (operator or "eq").lower()
    if op == "in":
        options = expected if isinstance(expected, list) else [expected]
        normalized = {str(item).strip().lower() for item in options}
        return actual_text in normalized
    expected_text = str(expected or "").strip().lower()
    if op == "eq":
        return actual_text == expected_text
    if op == "neq":
        return actual_text != expected_text
    if op == "contains":
        return expected_text in actual_text
    return False


def record_matches_filters(record: Dict[str, Any], filters: List[Dict[str, Any]]) -> bool:
    if not filters:
        return True
    for item in filters:
        field = str(item.get("field") or "").strip()
        if not field:
            continue
        operator = str(item.get("operator") or "gte")
        expected = item.get("value")
        actual = record.get(field)
        field_type = next((entry["type"] for entry in FIELD_CATALOG if entry["key"] == field), "number")
        if field_type == "number":
            if not _match_numeric(actual, operator, _coerce_filter_value(expected)):
                return False
        elif not _match_text(actual, operator, expected):
            return False
    return True


def _cache_get(symbol: str) -> Optional[Dict[str, Any]]:
    cached = _screener_cache.get(symbol.upper())
    if not cached:
        return None
    if time.time() >= float(cached.get("expires_at") or 0):
        _screener_cache.pop(symbol.upper(), None)
        return None
    return cached.get("record")


def _cache_set(symbol: str, record: Dict[str, Any]) -> None:
    _screener_cache[symbol.upper()] = {
        "record": record,
        "expires_at": time.time() + SCREENER_CACHE_TTL_SECONDS,
    }


async def fetch_screener_record(symbol: str, *, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
    normalized = symbol.strip().upper()
    if not normalized:
        return None
    if not force_refresh:
        cached = _cache_get(normalized)
        if cached is not None:
            return {**cached, "cached": True}

    try:
        payload = await get_nepse_alpha_signals_async(normalized)
        record = flatten_nepse_alpha_for_screener(payload)
        record["cached"] = False
        _cache_set(normalized, record)
        return record
    except Exception:
        return None


async def load_screener_records(
    symbols: List[str],
    *,
    force_refresh: bool = False,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    unique_symbols = []
    seen = set()
    for symbol in symbols:
        normalized = symbol.strip().upper()
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique_symbols.append(normalized)

    semaphore = asyncio.Semaphore(_MAX_CONCURRENT_FETCHES)
    stats = {"requested": len(unique_symbols), "loaded": 0, "failed": 0, "cache_hits": 0}

    async def _load_one(sym: str) -> Optional[Dict[str, Any]]:
        if not force_refresh:
            cached = _cache_get(sym)
            if cached is not None:
                stats["cache_hits"] += 1
                return {**cached, "cached": True}
        async with semaphore:
            record = await fetch_screener_record(sym, force_refresh=force_refresh)
        return record

    results = await asyncio.gather(*[_load_one(sym) for sym in unique_symbols])
    records: List[Dict[str, Any]] = []
    for record in results:
        if record:
            stats["loaded"] += 1
            records.append(record)
        else:
            stats["failed"] += 1
    return records, stats


def rank_screener_records(
    records: List[Dict[str, Any]],
    *,
    rank_by: Optional[str],
    direction: str = "desc",
    limit: int = 50,
) -> List[Dict[str, Any]]:
    if not records:
        return []

    key = rank_by or "alpha_annualized"
    reverse = direction.lower() != "asc"

    def sort_key(record: Dict[str, Any]) -> Tuple[int, float]:
        value = record.get(key)
        numeric = safe_number(value)
        if numeric is None:
            return (1, 0.0)
        return (0, numeric)

    ranked = sorted(records, key=sort_key, reverse=reverse)
    capped = ranked[: max(1, min(limit, 500))]
    for index, record in enumerate(capped, start=1):
        record["rank"] = index
    return capped


async def run_stock_screener(
    symbols: List[str],
    filters: List[Dict[str, Any]],
    *,
    rank_by: Optional[str] = None,
    rank_direction: str = "desc",
    limit: int = 50,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    records, stats = await load_screener_records(symbols, force_refresh=force_refresh)
    matched = [record for record in records if record_matches_filters(record, filters)]
    ranked = rank_screener_records(matched, rank_by=rank_by, direction=rank_direction, limit=limit)
    return {
        "results": ranked,
        "stats": {
            **stats,
            "matched": len(matched),
            "returned": len(ranked),
            "cache_ttl_seconds": SCREENER_CACHE_TTL_SECONDS,
        },
        "rank_by": rank_by or "alpha_annualized",
        "rank_direction": rank_direction,
    }
