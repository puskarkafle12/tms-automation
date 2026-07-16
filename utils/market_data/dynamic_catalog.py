"""Build screener field catalog dynamically from combined cache columns."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from database import ensure_read_session

from utils.external_data_sources.nepse_alpha.screener import (
    COLLOQUIAL_FIELD_ALIASES,
    FIELD_CATALOG as NEPSE_FIELD_CATALOG,
    NUMERIC_OPERATORS,
    TEXT_OPERATORS,
    build_field_aliases,
)
from utils.market_data.canonical_fields import (
    CANONICAL_FIELD_SPECS,
    COLUMN_LABELS,
    get_column_label,
    get_field_alias_map,
)
from utils.strategies.helpers import safe_number

NON_FILTERABLE_FIELDS = frozenset(
    {
        "rank",
        "symbol",
        "cached",
        "fetched_at",
        "updated_at",
        "rowKey",
        "color",
        "sortValues",
    }
)

TEXT_FIELD_HINTS = frozenset(
    {
        "sector",
        "company_name",
        "listing_date",
        "market_data_date",
        "market_data_source",
        "security_type",
        "last_traded_on",
        "technical_macd",
        "technical_sma_10",
        "technical_sma_20",
        "technical_sma_50",
        "technical_sma_200",
        "technical_volume_trend",
        "technical_3m_price_tend",
    }
)

PREFERRED_RANK_FIELDS = (
    "ltp",
    "alpha_annualized",
    "percent_change",
    "market_cap",
    "fundamental_pe_ttm",
    "pe_ratio",
    "sharpe_ratio_annualized",
)

MARKET_FIELD_KEYS = frozenset(
    {
        "avg_120d",
        "avg_180d",
        "avg_volume_30d",
        "book_value",
        "eps",
        "high",
        "last_traded_on",
        "low",
        "ltp",
        "market_cap",
        "market_price",
        "one_year_yield",
        "open",
        "pbv",
        "pe_ratio",
        "percent_change",
        "qty",
        "sector",
        "shares_outstanding",
        "promoter_shares",
        "public_shares",
        "promoter_share_percent",
        "public_share_percent",
        "paid_up_value",
        "paid_up_capital",
        "listing_date",
        "listing_age_days",
    }
)

TRADER_DISPLAY_COLUMNS = (
    "symbol",
    "sector",
    "ltp",
    "percent_change",
    "qty",
    "avg_volume_30d",
    "open",
    "high",
    "low",
)

INVESTOR_DISPLAY_COLUMNS = (
    "symbol",
    "sector",
    "ltp",
    "market_cap",
    "paid_up_capital",
    "shares_outstanding",
    "listing_date",
    "pe_ratio",
    "pbv",
    "eps",
    "percent_change",
)

STATIC_FIELD_REGISTRY: Dict[str, Dict[str, Any]] = {}
for key, spec in CANONICAL_FIELD_SPECS.items():
    STATIC_FIELD_REGISTRY[key] = {
        "key": key,
        "label": spec["label"],
        "category": "Market",
        "type": spec["type"],
    }
for item in NEPSE_FIELD_CATALOG:
    STATIC_FIELD_REGISTRY.setdefault(
        item["key"],
        {
            "key": item["key"],
            "label": item["label"],
            "category": item["category"],
            "type": item["type"],
        },
    )

REGISTERED_SOURCE_ALIASES: Dict[str, str] = {}


def register_source_field_aliases(mapping: Mapping[str, str]) -> None:
    """Register aliases when onboarding a new data source (alias -> canonical key)."""
    for alias, canonical in mapping.items():
        alias_key = str(alias).strip()
        canonical_key = str(canonical).strip()
        if alias_key and canonical_key:
            REGISTERED_SOURCE_ALIASES[alias_key] = canonical_key
            REGISTERED_SOURCE_ALIASES[alias_key.lower()] = canonical_key


def _normalize_field_key(key: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", str(key or "").strip()).strip("_").lower()
    return cleaned


def _is_empty_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return False
    text = str(value).strip()
    return not text or text in {"-", "--", "N/A", "n/a", "null", "None"}


def _looks_numeric(value: Any) -> bool:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return True
    if not isinstance(value, str):
        return False
    text = value.strip().replace(",", "").replace("%", "")
    return safe_number(text) is not None and bool(re.match(r"^-?[\d.]+%?$", value.strip()))


def infer_field_type(key: str, sample_values: Sequence[Any]) -> str:
    if key in TEXT_FIELD_HINTS or key.startswith("technical_sma_"):
        return "text"
    numeric = 0
    text = 0
    for value in sample_values:
        if _is_empty_value(value):
            continue
        if _looks_numeric(value):
            numeric += 1
        else:
            text += 1
    if text > numeric:
        return "text"
    if numeric > 0:
        return "number"
    registry = STATIC_FIELD_REGISTRY.get(key)
    if registry:
        return registry["type"]
    return "number"


def _field_category(key: str) -> str:
    registry = STATIC_FIELD_REGISTRY.get(key)
    if registry:
        return registry["category"]
    if key in MARKET_FIELD_KEYS:
        return "Market"
    if key.startswith("fundamental_"):
        return "Fundamental"
    if key.startswith("technical_"):
        return "Technical"
    if key.startswith(("alpha_", "beta_", "sharpe_", "volatility_", "daily_", "all_time_", "fifty_two_week_")):
        return "Statistical"
    return "Market"


def _rollback_db(db: Session) -> None:
    ensure_read_session(db)


def _discover_keys_from_rows(rows: Sequence[Any]) -> Set[str]:
    keys: Set[str] = set()
    for payload in rows:
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                continue
        if isinstance(payload, dict):
            keys.update(payload.keys())
    return keys


def discover_combined_field_keys(db: Session) -> List[str]:
    """Discover column keys by reading cached JSON rows (simple SELECT, no lateral/json SQL)."""
    ensure_read_session(db)
    try:
        rows = db.execute(
            text(
                """
                SELECT combined_data
                FROM market_screener_cache
                WHERE combined_data IS NOT NULL
                LIMIT 200
                """
            )
        ).scalars().all()
        keys = _discover_keys_from_rows(rows)
    except Exception:
        _rollback_db(db)
        return []

    return sorted(key for key in keys if key not in NON_FILTERABLE_FIELDS)


def sample_field_values(db: Session, field_keys: Sequence[str], *, limit: int = 120) -> Dict[str, List[Any]]:
    samples: Dict[str, List[Any]] = {key: [] for key in field_keys}
    ensure_read_session(db)
    try:
        rows = db.execute(
            text(
                """
                SELECT combined_data
                FROM market_screener_cache
                WHERE combined_data IS NOT NULL
                LIMIT :limit
                """
            ),
            {"limit": limit},
        ).scalars().all()
    except Exception:
        _rollback_db(db)
        return samples

    for payload in rows:
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                continue
        if not isinstance(payload, dict):
            continue
        for key in field_keys:
            if len(samples[key]) >= 12:
                continue
            value = payload.get(key)
            if not _is_empty_value(value):
                samples[key].append(value)
    return samples


def build_dynamic_alias_map(field_keys: Sequence[str]) -> Dict[str, str]:
    alias_map = build_field_aliases()
    alias_map.update(get_field_alias_map())
    alias_map.update(REGISTERED_SOURCE_ALIASES)

    for key in field_keys:
        alias_map.setdefault(key.lower(), key)
        label_slug = re.sub(r"[^a-z0-9]+", "_", get_column_label(key).lower()).strip("_")
        if label_slug:
            alias_map.setdefault(label_slug, key)

    for alias, canonical in COLLOQUIAL_FIELD_ALIASES.items():
        if canonical in field_keys:
            alias_map.setdefault(alias.lower(), canonical)

    return alias_map


def build_dynamic_field_catalog(
    db: Optional[Session] = None,
    *,
    records: Optional[Sequence[Mapping[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Catalog is driven by combined table columns; static registry supplies labels/types."""
    field_keys: List[str] = []
    samples: Dict[str, List[Any]] = {}

    if db is not None:
        ensure_read_session(db)
        field_keys = discover_combined_field_keys(db)
        if field_keys:
            samples = sample_field_values(db, field_keys)
    elif records:
        discovered: Set[str] = set()
        for record in records:
            discovered.update(record.keys())
        field_keys = sorted(key for key in discovered if key not in NON_FILTERABLE_FIELDS)
        samples = {key: [] for key in field_keys}
        for record in records[:120]:
            for key in field_keys:
                if len(samples[key]) >= 12:
                    continue
                value = record.get(key)
                if not _is_empty_value(value):
                    samples[key].append(value)

    if not field_keys:
        field_keys = sorted(STATIC_FIELD_REGISTRY.keys())

    catalog: List[Dict[str, Any]] = []
    seen = set()
    for key in field_keys:
        if key in seen or key in NON_FILTERABLE_FIELDS:
            continue
        seen.add(key)
        registry = STATIC_FIELD_REGISTRY.get(key, {})
        field_type = registry.get("type") or infer_field_type(key, samples.get(key, []))
        operators = NUMERIC_OPERATORS if field_type == "number" else TEXT_OPERATORS
        catalog.append(
            {
                "key": key,
                "label": registry.get("label") or get_column_label(key),
                "category": registry.get("category") or _field_category(key),
                "type": field_type,
                "operators": operators,
            }
        )
    return catalog


def choose_default_rank_field(field_keys: Sequence[str]) -> str:
    for candidate in PREFERRED_RANK_FIELDS:
        if candidate in field_keys:
            return candidate
    for key in field_keys:
        registry = STATIC_FIELD_REGISTRY.get(key)
        if registry and registry.get("type") == "number":
            return key
    return field_keys[0] if field_keys else "ltp"


def build_dynamic_query_spec(
    db: Optional[Session] = None,
    *,
    records: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    catalog = build_dynamic_field_catalog(db, records=records)
    keys = [item["key"] for item in catalog]
    alias_map = build_dynamic_alias_map(keys)

    aliases_by_key: Dict[str, List[str]] = {key: [] for key in keys}
    for alias, canonical in sorted(alias_map.items()):
        if canonical in aliases_by_key and alias != canonical.lower():
            aliases_by_key[canonical].append(alias)

    default_rank_by = choose_default_rank_field(keys)

    return {
        "allowed_filter_keys": keys,
        "result_columns": ["rank", "symbol", *keys],
        "non_filterable_columns": sorted(NON_FILTERABLE_FIELDS),
        "unsupported_user_terms": [],
        "numeric_operators": list(NUMERIC_OPERATORS),
        "text_operators": list(TEXT_OPERATORS),
        "field_aliases": aliases_by_key,
        "alias_map": alias_map,
        "limit_default": 25,
        "limit_max": 500,
        "default_rank_by": default_rank_by,
        "default_rank_direction": "desc",
        "data_source": "database_combined",
        "dynamic": True,
        "field_count": len(keys),
    }


# user phrases -> preferred field (only emitted when field exists in cache)
SEMANTIC_INTENT_HINTS: List[Tuple[str, str, str]] = [
    ("market_cap", "low cap, small cap, micro cap, market capitalization", "filter/sort on market_cap"),
    ("shares_outstanding", "listed shares, listed share count, shares outstanding, share count", "use shares_outstanding"),
    ("paid_up_capital", "paid up capital, paid-up capital, paidup capital", "use paid_up_capital"),
    ("paid_up_value", "paid up value, paid-up value, face value", "use paid_up_value"),
    ("promoter_shares", "promoter shares, promoter holdings", "use promoter_shares"),
    ("public_shares", "public shares, public holdings, public float", "use public_shares"),
    ("promoter_share_percent", "promoter share percentage, promoter ownership", "use promoter_share_percent"),
    ("public_share_percent", "public share percentage, public ownership", "use public_share_percent"),
    ("listing_date", "listing date, listed date, newly listed", "use listing_date and listing_age_days"),
    ("listing_age_days", "listing age, newly listed stocks, new stocks", "filter/sort on listing_age_days"),
    ("security_type", "ordinary shares, ordinary stocks, security type", "use security_type = 'ordinary_share'"),
    ("pe_ratio", "low pe, cheap valuation, value stocks", "use pe_ratio or fundamental_pe_ttm"),
    ("fundamental_pe_ttm", "pe ratio, price to earnings", "use fundamental_pe_ttm or pe_ratio"),
    ("ltp", "share price, last price, cheap stocks by price", "use ltp (not a cap substitute if market_cap exists)"),
    ("alpha_annualized", "alpha, risk-adjusted return", "use alpha_annualized"),
    ("technical_rsi_14", "oversold, oversold and slowly recovering, rsi", "use technical_rsi_14 BETWEEN 28 AND 45 with percent_change > 0 for recovery"),
    ("fundamental_roe_ttm", "roe, return on equity", "use fundamental_roe_ttm"),
    ("fundamental_debt_to_equity", "debt, leverage", "use fundamental_debt_to_equity"),
    ("sector", "sector, industry", "use sector with = or CONTAINS"),
]


def _pick_existing(keys: Set[str], *candidates: str) -> Optional[str]:
    for candidate in candidates:
        if candidate in keys:
            return candidate
    return None


def build_column_labels_for_keys(keys: Sequence[str]) -> Dict[str, str]:
    return {key: get_column_label(key) for key in keys if key}


DEFAULT_AI_SYSTEM_PROMPT_MAX_CHARS = 12_000
GROQ_AI_SYSTEM_PROMPT_MAX_CHARS = int(os.getenv("GROQ_MAX_SYSTEM_PROMPT_CHARS", "4500"))


def resolve_ai_system_prompt_max_chars() -> int:
    """Character budget for the screener system prompt (full detail for non-Groq providers)."""
    return int(
        os.getenv("AI_SYSTEM_PROMPT_MAX_CHARS", str(DEFAULT_AI_SYSTEM_PROMPT_MAX_CHARS)),
    )


def _format_grouped_column_catalog(
    catalog: List[Dict[str, Any]],
    *,
    include_labels: bool = True,
) -> str:
    groups: Dict[str, List[str]] = {}
    for item in catalog:
        category = str(item.get("category") or "Data")
        if include_labels:
            label = str(item.get("label") or item["key"])
            entry = f"{item['key']} ({label})"
        else:
            entry = str(item["key"])
        groups.setdefault(category, []).append(entry)
    lines: List[str] = []
    for category in ("Market", "Statistical", "Technical", "Fundamental", "Data"):
        items = groups.get(category)
        if not items:
            continue
        lines.append(f"{category} ({len(items)}):")
        lines.append(", ".join(sorted(items)))
    for category, items in sorted(groups.items()):
        if category in {"Market", "Statistical", "Technical", "Fundamental", "Data"}:
            continue
        lines.append(f"{category} ({len(items)}):")
        lines.append(", ".join(sorted(items)))
    return "\n".join(lines)


def _build_column_selection_rules(keys: Set[str]) -> str:
    trader = [col for col in TRADER_DISPLAY_COLUMNS if col in keys]
    investor = [col for col in INVESTOR_DISPLAY_COLUMNS if col in keys]
    basics = [col for col in ("symbol", "company_name", "sector", "ltp") if col in keys]
    return f"""COLUMN SELECTION (never use SELECT *):
- Always query FROM market_combined (or v_nepse_stock_screen for presets).
- Always list explicit columns in SELECT — pick 8 to 14 columns max for a readable table.
- MANDATORY in every SELECT: {", ".join(basics) or "symbol"}. Add percent_change and qty only when useful and available.
- Never return sector-only rows; symbol identifies each stock. Add sector after the mandatory columns if useful.
- Trader-style requests: start with symbol, ltp, percent_change, qty, then {", ".join(trader) or "technical_macd, technical_rsi_14"} when relevant.
- Investor-style requests: start with symbol, ltp, percent_change, qty, then {", ".join(investor) or "pe_ratio, market_cap"} when relevant.
- Include every column used in WHERE or ORDER BY.
- Add 2-5 extra context columns that help a trader/investor interpret the screen (do not dump all {len(keys)} columns).
- Omit sector_high/sector_low columns unless the user asks for sector comparison."""


def _format_field_index(catalog: List[Dict[str, Any]]) -> str:
    by_category: Dict[str, List[str]] = {}
    for item in catalog:
        by_category.setdefault(str(item["category"]), []).append(str(item["key"]))
    lines: List[str] = []
    for category in sorted(by_category):
        keys = ", ".join(sorted(by_category[category]))
        lines.append(f"{category}: {keys}")
    return "\n".join(lines)


def _build_semantic_hints(keys: Set[str]) -> str:
    lines: List[str] = []
    for field_key, user_phrases, usage in SEMANTIC_INTENT_HINTS:
        if field_key in keys:
            lines.append(f"- \"{user_phrases}\" -> `{field_key}` ({usage})")
    return "\n".join(lines) or "- Map user terms to the closest ALLOWED key by name or alias."


def _build_dynamic_examples(
    keys: Set[str],
    spec: Dict[str, Any],
    *,
    max_examples: int = 3,
) -> str:
    limit = int(spec.get("limit_default") or 25)
    examples: List[str] = []

    market_cap = _pick_existing(keys, "market_cap")
    pe = _pick_existing(keys, "pe_ratio", "fundamental_pe_ttm")
    rsi = _pick_existing(keys, "technical_rsi_14")
    alpha = _pick_existing(keys, "alpha_annualized")
    rank_default = str(spec.get("default_rank_by") or "ltp")

    paid_up_capital = _pick_existing(keys, "paid_up_capital")
    shares_outstanding = _pick_existing(keys, "shares_outstanding")
    listing_age_days = _pick_existing(keys, "listing_age_days")
    if paid_up_capital and shares_outstanding:
        examples.append(
            "Highest paid-up capital (fundamentals):\n"
            f"SELECT symbol, company_name, sector, ltp, {paid_up_capital}, {shares_outstanding}, listing_date\n"
            "FROM market_combined\nWHERE security_type = 'ordinary_share'\n"
            f"ORDER BY {paid_up_capital} DESC\nLIMIT {limit}"
        )
    if listing_age_days:
        examples.append(
            "Newly listed ordinary shares:\n"
            "SELECT symbol, company_name, sector, ltp, listing_date, listing_age_days, shares_outstanding\n"
            "FROM market_combined\nWHERE security_type = 'ordinary_share' AND listing_age_days <= 15\n"
            f"ORDER BY listing_age_days ASC\nLIMIT {limit}"
        )

    if market_cap:
        examples.append(
            f"Low market cap (investor):\nSELECT symbol, sector, ltp, market_cap, pe_ratio, pbv, eps, percent_change\nFROM market_combined\nWHERE {market_cap} <= 5000000000\nORDER BY {market_cap} ASC\nLIMIT {limit}"
        )
    if pe and alpha:
        examples.append(
            f"Value + momentum (investor/trader):\nSELECT symbol, sector, ltp, percent_change, qty, {pe}, {alpha}, technical_macd, technical_rsi_14\nFROM market_combined\nWHERE {pe} <= 25\nORDER BY {alpha} DESC\nLIMIT {limit}"
        )
    elif pe:
        examples.append(
            f"Low PE (investor):\nSELECT symbol, sector, ltp, pe_ratio, pbv, eps, market_cap, percent_change\nFROM market_combined\nWHERE {pe} <= 20\nORDER BY {pe} ASC\nLIMIT {limit}"
        )
    if rsi:
        macd = _pick_existing(keys, "technical_macd")
        stoch = _pick_existing(keys, "technical_stochastic_14")
        cols = f"symbol, sector, ltp, percent_change, qty, {rsi}"
        if stoch:
            cols += f", {stoch}"
        if macd:
            cols += f", {macd}"
        examples.append(
            "Oversold slowly recovering (trader):\n"
            f"SELECT {cols}\nFROM market_combined\n"
            f"WHERE {rsi} BETWEEN 28 AND 45\n"
            "  AND percent_change > 0\n"
            "ORDER BY percent_change DESC\n"
            f"LIMIT {limit}"
        )

    if not examples:
        examples.append(
            f"Generic:\nSELECT symbol, sector, ltp, percent_change, qty, {rank_default}\nFROM market_combined\nWHERE {rank_default} >= 0\nORDER BY {rank_default} DESC\nLIMIT {limit}"
        )
    return "\n\n".join(examples[: max(1, max_examples)])


def _render_dynamic_ai_prompt(
    catalog: List[Dict[str, Any]],
    spec: Dict[str, Any],
    *,
    include_labels: bool = True,
    alias_limit: int = 50,
    max_examples: int = 3,
    include_type_lists: bool = True,
) -> str:
    keys = set(spec["allowed_filter_keys"])
    numeric_keys = [item["key"] for item in catalog if item["type"] == "number"]
    text_keys = [item["key"] for item in catalog if item["type"] == "text"]
    grouped_catalog = _format_grouped_column_catalog(catalog, include_labels=include_labels)
    semantic_hints = _build_semantic_hints(keys)
    examples = _build_dynamic_examples(keys, spec, max_examples=max_examples)
    column_rules = _build_column_selection_rules(keys)

    alias_pairs: List[str] = []
    for canonical, aliases in sorted(spec["field_aliases"].items()):
        if aliases:
            alias_pairs.append(f"{canonical}={','.join(aliases[:3])}")

    type_section = ""
    if include_type_lists:
        type_section = (
            f"\nNUMERIC_COLUMNS: {', '.join(numeric_keys)}\n"
            f"TEXT_COLUMNS: {', '.join(text_keys)}\n"
        )

    return f"""You are a NEPSE market screener SQL generator for traders and investors.

DATA SOURCE: PostgreSQL table `market_combined` — virtual view over cached combined_data ({len(keys)} columns). Columns grow automatically when new scrapers are added; use ONLY keys listed below.

GOAL: Return one valid SELECT query in a single pass. Prefer STATUS: OK.

{column_rules}

QUERY RULES:
1. Shape: SELECT col1, col2, ... FROM market_combined [WHERE ...] ORDER BY ... LIMIT ...
2. NEVER use SELECT * — pick the most important 8-14 columns for the user's intent.
3. Use ONLY column names from ALL_COLUMNS. Exact snake_case. No JOIN, subqueries, UNION, or symbol filters.
4. Numeric: > >= < <= = != BETWEEN. Text: = != IN (...) ILIKE.
5. Always include ORDER BY and LIMIT (default {spec['limit_default']}, max {spec['limit_max']}).
6. Map user concepts via SEMANTIC MAP. Do NOT substitute ltp for market_cap when market_cap exists.
7. Use practical thresholds for useful first-attempt results.
8. Unless the user explicitly requests funds, debentures, bonds, promoter shares, or preference shares, filter `security_type = 'ordinary_share'` when that column exists.

SEMANTIC MAP:
{semantic_hints}

ALL_COLUMNS BY GROUP ({len(catalog)} total — auto-discovered from combined cache):
{grouped_catalog}
{type_section}ALIASES: {"; ".join(alias_pairs[:alias_limit]) or "none"}

EXAMPLE SQL (explicit columns — adapt to user intent):
{examples}

RESPONSE:

STATUS: OK
Summary:
- 2-3 bullets: what the screen finds, sort order, and which columns you chose to display
- Limitation: (only if needed)
Query:
```sql
SELECT symbol, sector, ltp, percent_change, qty, market_cap
FROM market_combined
WHERE market_cap < 5000000000
ORDER BY market_cap ASC
LIMIT {spec['limit_default']}
```

STATUS: ERROR
Reason:
- one bullet when no valid query is possible
"""


def _fit_dynamic_ai_prompt(
    catalog: List[Dict[str, Any]],
    spec: Dict[str, Any],
    max_chars: int,
) -> str:
    """Shrink prompt progressively while keeping rules, semantic map, keys, and examples."""
    tiers = (
        {"include_labels": True, "alias_limit": 50, "max_examples": 3, "include_type_lists": True},
        {"include_labels": False, "alias_limit": 35, "max_examples": 2, "include_type_lists": True},
        {"include_labels": False, "alias_limit": 20, "max_examples": 1, "include_type_lists": True},
        {"include_labels": False, "alias_limit": 10, "max_examples": 1, "include_type_lists": False},
    )
    best = tiers[-1]
    for tier in tiers:
        prompt = _render_dynamic_ai_prompt(catalog, spec, **tier)
        best = prompt
        if len(prompt) <= max_chars:
            return prompt

    # Last resort: keep full key list via compact index, drop grouped section bulk.
    keys = set(spec["allowed_filter_keys"])
    field_index = _format_field_index(catalog)
    semantic_hints = _build_semantic_hints(keys)
    column_rules = _build_column_selection_rules(keys)
    examples = _build_dynamic_examples(keys, spec, max_examples=1)
    minimal = f"""You are a NEPSE market screener SQL generator for traders and investors.

DATA SOURCE: PostgreSQL table `market_combined` ({len(keys)} columns). Use ONLY keys below.

GOAL: Return one valid SELECT query in a single pass. Prefer STATUS: OK.

{column_rules}

QUERY RULES:
1. SELECT explicit columns FROM market_combined [WHERE ...] ORDER BY ... LIMIT ...
2. NEVER use SELECT *. MANDATORY columns: symbol, ltp, percent_change, qty (in that order).
3. Use ONLY listed keys. Exact snake_case. No JOIN, subqueries, UNION, or symbol filters.
4. Numeric: > >= < <= = != BETWEEN. Text: = != IN (...) ILIKE.
5. Always ORDER BY and LIMIT (default {spec['limit_default']}, max {spec['limit_max']}).
6. Map user concepts via SEMANTIC MAP.

SEMANTIC MAP:
{semantic_hints}

ALL_COLUMNS ({len(catalog)} keys by category):
{field_index}

EXAMPLE:
{examples}

RESPONSE: STATUS: OK with Summary bullets + ```sql ... ``` block, or STATUS: ERROR with Reason."""
    return minimal if len(minimal) <= max_chars else best[:max_chars]


def build_dynamic_ai_system_prompt_from_records(
    records: Sequence[Mapping[str, Any]],
    *,
    max_chars: Optional[int] = None,
) -> str:
    catalog = build_dynamic_field_catalog(None, records=records)
    spec = build_dynamic_query_spec(None, records=records)
    budget = max_chars if max_chars is not None else resolve_ai_system_prompt_max_chars()
    return _fit_dynamic_ai_prompt(catalog, spec, budget)


def build_dynamic_ai_system_prompt(
    db: Session,
    *,
    max_chars: Optional[int] = None,
) -> str:
    """Build AI screener prompt from live combined-table columns (no hardcoded script list)."""
    full_prompt, _compact = build_dynamic_ai_system_prompts(db, max_chars=max_chars)
    return full_prompt


def build_dynamic_ai_system_prompts(
    db: Session,
    *,
    max_chars: Optional[int] = None,
    groq_max_chars: Optional[int] = None,
) -> Tuple[str, str]:
    """Return (full_prompt, groq_compact_prompt) for multi-provider LLM routing."""
    catalog = build_dynamic_field_catalog(db)
    spec = build_dynamic_query_spec(db)
    full_budget = max_chars if max_chars is not None else resolve_ai_system_prompt_max_chars()
    groq_budget = groq_max_chars if groq_max_chars is not None else GROQ_AI_SYSTEM_PROMPT_MAX_CHARS
    full_prompt = _fit_dynamic_ai_prompt(catalog, spec, full_budget)
    compact_prompt = _fit_dynamic_ai_prompt(catalog, spec, groq_budget)
    return full_prompt, compact_prompt
