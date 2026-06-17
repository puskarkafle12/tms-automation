"""Parse SQL-like screener queries into filter payloads."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from utils.external_data_sources.nepse_alpha.screener import FIELD_CATALOG
from utils.strategies.helpers import safe_number

VALID_FIELDS = {item["key"] for item in FIELD_CATALOG}
FIELD_ALIASES = {item["key"].lower(): item["key"] for item in FIELD_CATALOG}
for item in FIELD_CATALOG:
    label = re.sub(r"[^a-z0-9]+", "_", item["label"].lower()).strip("_")
    FIELD_ALIASES.setdefault(label, item["key"])


class ScreenerQueryError(ValueError):
    """Raised when a screener query cannot be parsed."""


def _normalize_query(text: str) -> str:
    cleaned = re.sub(r"--[^\n]*", "", text or "")
    cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.DOTALL)
    return re.sub(r"\s+", " ", cleaned).strip()


def _resolve_field(name: str) -> str:
    key = (name or "").strip().lower()
    if not key:
        raise ScreenerQueryError("Filter field name is required")
    resolved = FIELD_ALIASES.get(key)
    if not resolved:
        raise ScreenerQueryError(f"Unknown field: {name}")
    return resolved


def _parse_value(raw: str) -> Any:
    token = raw.strip()
    if not token:
        raise ScreenerQueryError("Filter value is required")
    if (token.startswith("'") and token.endswith("'")) or (token.startswith('"') and token.endswith('"')):
        return token[1:-1]
    numeric = safe_number(token)
    if numeric is not None:
        return numeric
    return token


def _split_and_clauses(clause: str) -> List[str]:
    protected = clause
    placeholders: Dict[str, str] = {}
    index = 0
    for match in re.finditer(
        r"([a-zA-Z0-9_]+)\s+BETWEEN\s+(.+?)\s+AND\s+(.+?)(?=\s+AND\s+|\s*$)",
        clause,
        flags=re.IGNORECASE,
    ):
        key = f"__between_{index}__"
        placeholders[key] = match.group(0).strip()
        protected = protected.replace(match.group(0), key, 1)
        index += 1

    parts: List[str] = []
    for chunk in re.split(r"\s+AND\s+", protected, flags=re.IGNORECASE):
        token = chunk.strip()
        if not token:
            continue
        parts.append(placeholders.get(token, token))
    return parts


def _parse_condition(condition: str) -> Dict[str, Any]:
    text = condition.strip()
    if not text:
        raise ScreenerQueryError("Empty filter condition")

    between_match = re.match(
        r"^([a-zA-Z0-9_]+)\s+BETWEEN\s+(.+?)\s+AND\s+(.+?)$",
        text,
        flags=re.IGNORECASE,
    )
    if between_match:
        field = _resolve_field(between_match.group(1))
        low = _parse_value(between_match.group(2))
        high = _parse_value(between_match.group(3))
        return {"field": field, "operator": "between", "value": [low, high]}

    in_match = re.match(r"^([a-zA-Z0-9_]+)\s+IN\s*\((.+)\)$", text, flags=re.IGNORECASE)
    if in_match:
        field = _resolve_field(in_match.group(1))
        raw_values = in_match.group(2)
        values = [_parse_value(item) for item in raw_values.split(",") if item.strip()]
        if not values:
            raise ScreenerQueryError(f"IN list is empty for {field}")
        return {"field": field, "operator": "in", "value": values}

    contains_match = re.match(
        r"^([a-zA-Z0-9_]+)\s+(?:CONTAINS|LIKE)\s+(.+)$",
        text,
        flags=re.IGNORECASE,
    )
    if contains_match:
        field = _resolve_field(contains_match.group(1))
        return {"field": field, "operator": "contains", "value": _parse_value(contains_match.group(2))}

    for pattern, operator in (
        (r"^([a-zA-Z0-9_]+)\s*>=\s*(.+)$", "gte"),
        (r"^([a-zA-Z0-9_]+)\s*<=\s*(.+)$", "lte"),
        (r"^([a-zA-Z0-9_]+)\s*!=\s*(.+)$", "neq"),
        (r"^([a-zA-Z0-9_]+)\s*<>\s*(.+)$", "neq"),
        (r"^([a-zA-Z0-9_]+)\s*>\s*(.+)$", "gt"),
        (r"^([a-zA-Z0-9_]+)\s*<\s*(.+)$", "lt"),
        (r"^([a-zA-Z0-9_]+)\s*=\s*(.+)$", "eq"),
    ):
        match = re.match(pattern, text, flags=re.IGNORECASE)
        if match:
            field = _resolve_field(match.group(1))
            return {"field": field, "operator": operator, "value": _parse_value(match.group(2))}

    raise ScreenerQueryError(f"Could not parse condition: {condition}")


def _extract_tail_clause(query: str, keyword: str) -> Tuple[str, Optional[str]]:
    pattern = re.compile(rf"\b{keyword}\b", flags=re.IGNORECASE)
    match = None
    for candidate in pattern.finditer(query):
        match = candidate
    if not match:
        return query, None
    start = match.start()
    end = match.end()
    return query[:start].strip(), query[end:].strip()


def parse_screener_query(query: str) -> Dict[str, Any]:
    """
    Parse a SQL-like screener query.

    Example:
        WHERE technical_rsi_14 BETWEEN 30 AND 45
          AND fundamental_pe_ttm <= 30
          AND technical_macd = 'Bullish'
        ORDER BY alpha_annualized DESC
        LIMIT 25
    """
    normalized = _normalize_query(query)
    if not normalized:
        raise ScreenerQueryError("Query is empty")

    working = normalized
    if working.upper().startswith("SELECT"):
        where_idx = re.search(r"\bWHERE\b", working, flags=re.IGNORECASE)
        if where_idx:
            working = working[where_idx.end() :].strip()
        else:
            order_idx = re.search(r"\bORDER BY\b", working, flags=re.IGNORECASE)
            working = working[order_idx.start() :].strip() if order_idx else ""

    limit = 50
    working, limit_clause = _extract_tail_clause(working, "LIMIT")
    if limit_clause:
        limit_value = safe_number(limit_clause.split()[0])
        if limit_value is None:
            raise ScreenerQueryError("LIMIT must be a number")
        limit = max(1, min(int(limit_value), 500))

    rank_by: Optional[str] = None
    rank_direction = "desc"
    working, order_clause = _extract_tail_clause(working, "ORDER BY")
    if order_clause:
        order_parts = order_clause.split()
        if not order_parts:
            raise ScreenerQueryError("ORDER BY requires a field")
        rank_by = _resolve_field(order_parts[0])
        if len(order_parts) > 1:
            direction = order_parts[1].lower()
            if direction not in {"asc", "desc"}:
                raise ScreenerQueryError("ORDER BY direction must be ASC or DESC")
            rank_direction = direction

    where_clause = working
    if where_clause.upper().startswith("WHERE"):
        where_clause = where_clause[5:].strip()

    filters = [_parse_condition(item) for item in _split_and_clauses(where_clause)] if where_clause else []

    return {
        "filters": filters,
        "rank_by": rank_by or "alpha_annualized",
        "rank_direction": rank_direction,
        "limit": limit,
    }
