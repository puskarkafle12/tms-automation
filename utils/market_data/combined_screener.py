"""Combined Merolagani + Nepse Alpha screener backed by database cache."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from utils.external_data_sources.nepse_alpha.screener import (
    FIELD_CATALOG as NEPSE_FIELD_CATALOG,
    NUMERIC_OPERATORS,
    TEXT_OPERATORS,
    build_field_aliases,
    get_screener_query_spec as get_nepse_query_spec,
    rank_screener_records,
    record_matches_filters,
)
from utils.market_data.canonical_fields import (
    get_field_alias_map,
    get_market_field_catalog,
    resolve_record_field,
)
from utils.market_data.merolagani_fields import MEROLAGANI_FIELD_CATALOG
from utils.market_data.repository import get_cache_status, load_cached_records

DB_CACHE_TTL_SECONDS = 20 * 60
NEPSE_ALPHA_CACHE_TTL_SECONDS = 60 * 60


def get_combined_field_catalog() -> List[Dict[str, Any]]:
    catalog: List[Dict[str, Any]] = []
    seen = set()
    for item in [*get_market_field_catalog(), *NEPSE_FIELD_CATALOG]:
        key = item["key"]
        if key in seen:
            continue
        seen.add(key)
        operators = NUMERIC_OPERATORS if item["type"] == "number" else TEXT_OPERATORS
        catalog.append({**item, "operators": operators})
    return catalog


def get_combined_query_spec() -> Dict[str, Any]:
    catalog = get_combined_field_catalog()
    keys = [item["key"] for item in catalog]
    alias_map = build_field_aliases()
    alias_map.update(get_field_alias_map())
    for item in get_market_field_catalog():
        alias_map.setdefault(item["key"].lower(), item["key"])
        label = item["label"].lower().replace(" ", "_").replace("/", "_")
        alias_map.setdefault(label, item["key"])

    aliases_by_key: Dict[str, List[str]] = {key: [] for key in keys}
    for alias, canonical in sorted(alias_map.items()):
        if canonical in aliases_by_key and alias != canonical.lower():
            aliases_by_key[canonical].append(alias)

    nepse_spec = get_nepse_query_spec()
    unsupported = list(nepse_spec.get("unsupported_user_terms") or [])
    unsupported = [term for term in unsupported if term not in {"market_cap", "marketcap", "market capitalization", "eps", "volume"}]

    return {
        "allowed_filter_keys": keys,
        "result_columns": ["rank", "symbol", *keys],
        "non_filterable_columns": ["rank", "symbol", "cached", "fetched_at", "updated_at"],
        "unsupported_user_terms": unsupported,
        "numeric_operators": list(NUMERIC_OPERATORS),
        "text_operators": list(TEXT_OPERATORS),
        "field_aliases": aliases_by_key,
        "alias_map": alias_map,
        "limit_default": 25,
        "limit_max": 500,
        "default_rank_by": "alpha_annualized",
        "default_rank_direction": "desc",
        "data_source": "database",
        "refresh_interval_seconds": DB_CACHE_TTL_SECONDS,
        "merolagani_refresh_interval_seconds": DB_CACHE_TTL_SECONDS,
        "nepse_alpha_refresh_interval_seconds": NEPSE_ALPHA_CACHE_TTL_SECONDS,
    }


def _record_matches_filters(
    record: Dict[str, Any],
    filters: List[Dict[str, Any]],
    *,
    field_catalog: List[Dict[str, Any]],
) -> bool:
    patched = dict(record)
    for item in filters:
        field = str(item.get("field") or "").strip()
        if not field:
            continue
        value = resolve_record_field(record, field)
        if value is not None:
            patched[field] = value
    return record_matches_filters(patched, filters, field_catalog=field_catalog)


def run_combined_screener_from_db(
    db: Session,
    symbols: List[str],
    filters: List[Dict[str, Any]],
    *,
    rank_by: Optional[str] = None,
    rank_direction: str = "desc",
    limit: int = 50,
) -> Dict[str, Any]:
    catalog = get_combined_field_catalog()
    records = load_cached_records(db, symbols if symbols else None)
    matched = [
        record
        for record in records
        if _record_matches_filters(record, filters, field_catalog=catalog)
    ]
    ranked = rank_screener_records(matched, rank_by=rank_by, direction=rank_direction, limit=limit)
    status = get_cache_status(db)
    return {
        "results": ranked,
        "stats": {
            "requested": len(symbols) if symbols else len(records),
            "loaded": len(records),
            "failed": max(0, (len(symbols) if symbols else len(records)) - len(records)),
            "cache_hits": len(records),
            "matched": len(matched),
            "returned": len(ranked),
            "cache_ttl_seconds": DB_CACHE_TTL_SECONDS,
            "data_source": "database",
        },
        "rank_by": rank_by or "alpha_annualized",
        "rank_direction": rank_direction,
        "cache_status": status,
    }


def parse_combined_screener_query(query: str) -> Dict[str, Any]:
    import utils.external_data_sources.nepse_alpha.query_parser as query_parser

    spec = get_combined_query_spec()
    old_aliases = query_parser.FIELD_ALIASES
    old_valid = query_parser.VALID_FIELDS
    try:
        query_parser.FIELD_ALIASES = spec["alias_map"]
        query_parser.VALID_FIELDS = set(spec["allowed_filter_keys"])
        return query_parser.parse_screener_query(query)
    finally:
        query_parser.FIELD_ALIASES = old_aliases
        query_parser.VALID_FIELDS = old_valid
