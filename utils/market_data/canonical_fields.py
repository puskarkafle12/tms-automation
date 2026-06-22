"""Trader-friendly canonical market fields with alias merge and display order."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from utils.market_data.merolagani_fields import normalize_merolagani_record


def _normalize_field_key(key: str) -> str:
    import re

    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", str(key or "").strip()).strip("_").lower()
    return cleaned

# canonical_key -> (label, type, aliases newest-last for merge)
CANONICAL_FIELD_SPECS: Dict[str, Dict[str, Any]] = {
    "symbol": {"label": "Symbol", "type": "text", "aliases": ["Symbol", "symbol"]},
    "ltp": {"label": "LTP", "type": "number", "aliases": ["ml_ltp", "ltp"]},
    "percent_change": {"label": "% Change", "type": "number", "aliases": ["ml_percent_change", "percent_change"]},
    "qty": {"label": "Qty", "type": "number", "aliases": ["ml_quantity", "qty", "quantity"]},
    "open": {"label": "Open", "type": "number", "aliases": ["ml_open", "open"]},
    "high": {"label": "High", "type": "number", "aliases": ["ml_high", "high"]},
    "low": {"label": "Low", "type": "number", "aliases": ["ml_low", "low"]},
    "pe_ratio": {
        "label": "P/E",
        "type": "number",
        "aliases": ["ml_pe_ratio", "fundamental_pe_ttm", "pe_ratio"],
    },
    "pbv": {"label": "P/BV", "type": "number", "aliases": ["ml_pbv", "fundamental_pbv", "pbv"]},
    "eps": {"label": "EPS", "type": "number", "aliases": ["ml_eps", "eps"]},
    "market_cap": {"label": "Mkt Cap", "type": "number", "aliases": ["ml_market_cap", "market_cap"]},
    "one_year_yield": {
        "label": "1Y Yield",
        "type": "number",
        "aliases": ["ml_one_year_yield", "one_year_yield"],
    },
    "avg_volume_30d": {
        "label": "30D Avg Vol",
        "type": "number",
        "aliases": ["ml_avg_volume_30d", "avg_volume_30d"],
    },
    "shares_outstanding": {
        "label": "Shares Out",
        "type": "number",
        "aliases": ["ml_shares_outstanding", "shares_outstanding"],
    },
    "avg_120d": {"label": "120D Avg", "type": "number", "aliases": ["ml_avg_120d", "avg_120d"]},
    "avg_180d": {"label": "180D Avg", "type": "number", "aliases": ["ml_avg_180d", "avg_180d"]},
    "book_value": {"label": "Book Value", "type": "number", "aliases": ["ml_book_value", "book_value"]},
    "market_price": {"label": "Mkt Price", "type": "number", "aliases": ["ml_market_price", "market_price"]},
    "sector": {"label": "Sector", "type": "text", "aliases": ["ml_sector", "sector"]},
    "listing_date": {"label": "Listed", "type": "text", "aliases": ["ml_listing_date", "listing_date"]},
    "last_traded_on": {
        "label": "Last Trade",
        "type": "text",
        "aliases": ["ml_last_traded_on", "last_traded_on"],
    },
}

MEROLAGANI_DISPLAY_ORDER: List[str] = [
    "symbol",
    "ltp",
    "percent_change",
    "qty",
    "open",
    "high",
    "low",
    "pe_ratio",
    "pbv",
    "eps",
    "market_cap",
    "one_year_yield",
    "avg_volume_30d",
    "shares_outstanding",
    "avg_120d",
    "avg_180d",
    "book_value",
    "market_price",
    "sector",
    "listing_date",
    "last_traded_on",
]

NEPSE_DISPLAY_ORDER: List[str] = [
    "symbol",
    "ltp",
    "percent_change",
    "alpha_annualized",
    "beta_3_month",
    "sharpe_ratio_annualized",
    "one_year_yield",
    "pe_ratio",
    "pbv",
    "fundamental_roe_ttm",
    "technical_rsi_14",
    "technical_macd",
    "fifty_two_week_high",
    "fifty_two_week_low",
    "volatility_50d",
    "daily_var_95",
]

COMBINED_DISPLAY_ORDER: List[str] = [
    "symbol",
    "ltp",
    "percent_change",
    "qty",
    "open",
    "high",
    "low",
    "pe_ratio",
    "pbv",
    "eps",
    "market_cap",
    "alpha_annualized",
    "beta_3_month",
    "sharpe_ratio_annualized",
    "one_year_yield",
    "fundamental_roe_ttm",
    "technical_rsi_14",
    "technical_macd",
    "fifty_two_week_high",
    "fifty_two_week_low",
    "avg_volume_30d",
    "sector",
    "updated_at",
]

NEPSE_ONLY_KEYS = {
    "alpha_annualized",
    "beta_3_month",
    "sharpe_ratio_annualized",
    "daily_var_95",
    "volatility_50d",
    "fifty_two_week_high",
    "fifty_two_week_low",
    "all_time_high",
    "all_time_low",
    "fundamental_roe_ttm",
    "fundamental_ps_ttm",
    "fundamental_peg_3_5_yrs",
    "fundamental_roa_ttm",
    "fundamental_dividend_yield",
    "fundamental_payout_ratio",
    "fundamental_qoq_earnings_growth",
    "fundamental_yoy_earnings_growth",
    "fundamental_distance_from_graham_number",
    "fundamental_debt_to_equity",
    "technical_rsi_14",
    "technical_mfi_14",
    "technical_price_relative_strength",
    "technical_percent_b",
    "technical_stochastic_14",
    "technical_macd",
    "technical_sma_10",
    "technical_sma_20",
    "technical_sma_50",
    "technical_sma_200",
    "technical_volume_trend",
    "technical_3m_price_tend",
    "fetched_at",
}

COLUMN_LABELS: Dict[str, str] = {key: spec["label"] for key, spec in CANONICAL_FIELD_SPECS.items()}
COLUMN_LABELS.update(
    {
        "alpha_annualized": "Alpha",
        "beta_3_month": "Beta (3M)",
        "sharpe_ratio_annualized": "Sharpe",
        "daily_var_95": "VaR 95%",
        "volatility_50d": "50D Vol",
        "fifty_two_week_high": "52W High",
        "fifty_two_week_low": "52W Low",
        "all_time_high": "ATH",
        "all_time_low": "ATL",
        "fundamental_roe_ttm": "ROE",
        "fundamental_ps_ttm": "P/S",
        "fundamental_peg_3_5_yrs": "PEG",
        "fundamental_roa_ttm": "ROA",
        "fundamental_dividend_yield": "Div Yield",
        "fundamental_payout_ratio": "Payout",
        "fundamental_qoq_earnings_growth": "QOQ EPS",
        "fundamental_yoy_earnings_growth": "YOY EPS",
        "fundamental_distance_from_graham_number": "Graham Gap",
        "fundamental_debt_to_equity": "D/E",
        "technical_rsi_14": "RSI",
        "technical_mfi_14": "MFI",
        "technical_price_relative_strength": "Rel Strength",
        "technical_percent_b": "%B",
        "technical_stochastic_14": "Stoch",
        "technical_macd": "MACD",
        "technical_sma_10": "SMA 10",
        "technical_sma_20": "SMA 20",
        "technical_sma_50": "SMA 50",
        "technical_sma_200": "SMA 200",
        "technical_volume_trend": "Vol Trend",
        "technical_3m_price_tend": "3M Trend",
        "updated_at": "Updated",
        "is_watchlist": "Watchlist",
    }
)

_ALIAS_TO_CANONICAL: Dict[str, str] = {}
for canonical, spec in CANONICAL_FIELD_SPECS.items():
    _ALIAS_TO_CANONICAL[canonical] = canonical
    for alias in spec.get("aliases") or []:
        _ALIAS_TO_CANONICAL[str(alias)] = canonical


def get_column_label(key: str) -> str:
    return COLUMN_LABELS.get(key) or key.replace("_", " ").title()


def get_market_field_catalog() -> List[Dict[str, Any]]:
    catalog: List[Dict[str, Any]] = []
    for key in MEROLAGANI_DISPLAY_ORDER:
        if key == "symbol":
            continue
        spec = CANONICAL_FIELD_SPECS[key]
        catalog.append(
            {
                "key": key,
                "label": spec["label"],
                "category": "Market",
                "type": spec["type"],
            }
        )
    return catalog


def _coalesce_from_sources(
    sources: Sequence[Mapping[str, Any]],
    aliases: Iterable[str],
) -> Any:
    value = None
    for source in sources:
        for alias in aliases:
            if alias not in source:
                continue
            candidate = source.get(alias)
            if candidate is None:
                continue
            if isinstance(candidate, str) and not candidate.strip():
                continue
            value = candidate
    return value


def canonicalize_record(*sources: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Merge source payloads into one canonical record; later sources win per field."""
    normalized_sources: List[Dict[str, Any]] = []
    for source in sources:
        if not source:
            continue
        payload = dict(source)
        if any(key.startswith("ml_") for key in payload.keys()) or "LTP" in payload:
            payload = normalize_merolagani_record(payload)
        normalized_sources.append(payload)

    record: Dict[str, Any] = {}
    symbol = _coalesce_from_sources(normalized_sources, ("symbol", "Symbol"))
    if symbol:
        record["symbol"] = str(symbol).strip().upper()

    for canonical, spec in CANONICAL_FIELD_SPECS.items():
        if canonical == "symbol":
            continue
        aliases = [canonical, *(spec.get("aliases") or [])]
        value = _coalesce_from_sources(normalized_sources, aliases)
        if value is not None:
            record[canonical] = value

    extras: Dict[str, Any] = {}
    for source in normalized_sources:
        for key, value in source.items():
            if _is_empty_cell(value):
                continue
            if key in CANONICAL_FIELD_SPECS or key in _ALIAS_TO_CANONICAL:
                continue
            norm_key = _normalize_field_key(key)
            if norm_key in CANONICAL_FIELD_SPECS:
                continue
            extras[norm_key] = value
    record.update(extras)

    return record


def build_combined_record(*sources: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Merge one or more source payloads; later sources win on duplicate keys."""
    return canonicalize_record(*sources)


def canonicalize_merolagani_record(record: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    return canonicalize_record(record)


def expand_legacy_field_aliases(record: Mapping[str, Any]) -> Dict[str, Any]:
    """Expose legacy ml_* / nepse duplicate keys for screener filters."""
    expanded = dict(record)
    for canonical, spec in CANONICAL_FIELD_SPECS.items():
        value = record.get(canonical)
        if value is None:
            value = _coalesce_from_sources([record], [canonical, *(spec.get("aliases") or [])])
        if value is None:
            continue
        expanded[canonical] = value
        for alias in spec.get("aliases") or []:
            if alias != canonical:
                expanded.setdefault(alias, value)
    return expanded


def resolve_record_field(
    record: Mapping[str, Any],
    field: str,
    alias_map: Optional[Mapping[str, str]] = None,
) -> Any:
    lookup = alias_map or get_field_alias_map()
    canonical = lookup.get(str(field).lower(), _ALIAS_TO_CANONICAL.get(field, field))
    if canonical in record and record.get(canonical) is not None:
        return record.get(canonical)
    spec = CANONICAL_FIELD_SPECS.get(canonical)
    if spec:
        return _coalesce_from_sources([record], [canonical, *(spec.get("aliases") or [])])
    return record.get(canonical, record.get(field))


METADATA_COLUMNS = frozenset({"updated_at", "fetched_at"})


def _is_empty_cell(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return False
    text = str(value).strip()
    return not text or text in {"-", "--", "—", "N/A", "n/a", "null", "None"}


def _column_has_any_value(rows: Sequence[Mapping[str, Any]], column: str) -> bool:
    return any(not _is_empty_cell(row.get(column)) for row in rows)


def ordered_columns_for_source(source: str, rows: Sequence[Mapping[str, Any]]) -> List[str]:
    if source == "merolagani":
        preferred = MEROLAGANI_DISPLAY_ORDER
    elif source == "nepse_alpha":
        preferred = NEPSE_DISPLAY_ORDER
    else:
        preferred = COMBINED_DISPLAY_ORDER

    present = set()
    for row in rows:
        for key in row.keys():
            if key in {"color", "sortValues", "rowKey"}:
                continue
            present.add(key)

    ordered = [key for key in preferred if key in present]
    extras = sorted(key for key in present if key not in ordered and key != "symbol")
    if "symbol" in present:
        all_columns = ["symbol", *[key for key in ordered if key != "symbol"], *extras]
    else:
        all_columns = [*ordered, *extras]

    with_data = [column for column in all_columns if _column_has_any_value(rows, column)]
    without_data = [column for column in all_columns if column not in with_data]
    ordered = with_data + without_data
    metadata = [column for column in ordered if column in METADATA_COLUMNS]
    body = [column for column in ordered if column not in METADATA_COLUMNS]
    return body + metadata


def get_field_alias_map() -> Dict[str, str]:
    aliases: Dict[str, str] = {}
    for canonical, spec in CANONICAL_FIELD_SPECS.items():
        aliases[canonical.lower()] = canonical
        for alias in spec.get("aliases") or []:
            aliases[str(alias).lower()] = canonical
    return aliases


def row_color_for_percent_change(percent_change: Any) -> Optional[str]:
    try:
        value = float(percent_change)
    except (TypeError, ValueError):
        return None
    if value > 0:
        return "lightgreen"
    if value < 0:
        return "red"
    return "lightyellow"
