from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from utils.strategy_builder.market_normalizer import build_symbol_snapshot_from_parts
from utils.strategy_builder.reference_dependencies import collect_reference_fields_from_plan
from utils.strategy_builder.reference_store import ReferenceRow
from utils.strategy_builder.schedule_preflight import _field_data_source
from utils.strategy_builder.strategy_fields import get_field_metadata
from utils.strategy_builder.strategy_models import StrategyPlanAST
from utils.strategies.normalize import get_script_details, normalize_tms_quote

REFERENCE_CAPTURE_MAX_RETRIES = 3


class ReferenceCaptureError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        symbol: str | None = None,
        field_key: str | None = None,
        expected_type: str | None = None,
        source: str | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.symbol = symbol
        self.field_key = field_key
        self.expected_type = expected_type
        self.source = source


def _field_type_for_key(field_key: str) -> str:
    meta = get_field_metadata(field_key) or {}
    data_type = str(meta.get("data_type") or "decimal").lower()
    if data_type in {"decimal", "number", "float", "integer"}:
        return "decimal"
    if data_type in {"text", "enum", "string"}:
        return "text"
    if data_type in {"boolean", "bool"}:
        return "boolean"
    return "decimal"


def _typed_row_value(field_key: str, raw_value: Any) -> Tuple[str, Optional[float], Optional[str], Optional[bool]]:
    field_type = _field_type_for_key(field_key)
    if raw_value is None or raw_value == "":
        raise ReferenceCaptureError(
            "REFERENCE_VALUE_REQUIRED",
            f"Reference value for {field_key} is null or missing.",
            field_key=field_key,
            expected_type=field_type,
        )
    if field_type == "decimal":
        return field_type, float(raw_value), None, None
    if field_type == "text":
        return field_type, None, str(raw_value), None
    return field_type, None, None, bool(raw_value)


def _source_label(field_key: str) -> str:
    source = _field_data_source(field_key)
    if source in {"tms", "tms_derived"}:
        return "tms_quote"
    if source == "derived_statistical":
        return "derived_statistical"
    if source == "nepse_alpha":
        return "nepse_alpha"
    return source or "runtime"


async def _fetch_symbol_flat(
    tms_user,
    symbol: str,
    *,
    max_attempts: int = REFERENCE_CAPTURE_MAX_RETRIES,
) -> dict:
    normalized = symbol.strip().upper()
    last_error: Optional[ReferenceCaptureError] = None
    for attempt in range(1, max_attempts + 1):
        try:
            security = await tms_user.get_security_id(normalized)
            if not security or not security.get("id"):
                raise ReferenceCaptureError(
                    "REFERENCE_CAPTURE_FAILED",
                    f"{normalized} was not found in TMS.",
                    symbol=normalized,
                )
            quote = await tms_user.get_stock_details_async(
                str(security["id"]),
                max_retries=REFERENCE_CAPTURE_MAX_RETRIES,
                retry_backoff=True,
            )
            if not quote or quote.get("ltp") in (None, 0):
                raise ReferenceCaptureError(
                    "REFERENCE_CAPTURE_FAILED",
                    f"Live TMS quote is unavailable for {normalized}.",
                    symbol=normalized,
                    source="tms_quote",
                )
            details = get_script_details(normalized, force_refresh=True)
            snapshot = normalize_tms_quote(normalized, quote)
            normalized_payload = build_symbol_snapshot_from_parts(normalized, snapshot, details)
            flat = normalized_payload.get("flat") or {}
            if flat.get("ltp") in (None, "", 0):
                raise ReferenceCaptureError(
                    "REFERENCE_CAPTURE_FAILED",
                    f"Reference ltp is unavailable for {normalized}.",
                    symbol=normalized,
                    field_key="ltp",
                    source="tms_quote",
                )
            return flat
        except ReferenceCaptureError as exc:
            last_error = exc
            if attempt < max_attempts:
                await asyncio.sleep(min(0.25 * (2 ** (attempt - 1)), 1.5))
                continue
            raise last_error
    raise last_error or ReferenceCaptureError(
        "REFERENCE_CAPTURE_FAILED",
        f"Could not fetch reference data for {normalized}.",
        symbol=normalized,
    )


def _targets_for_plan(plan: StrategyPlanAST, scheduled_symbol: str) -> List[Tuple[str, str, Set[str]]]:
    scheduled = scheduled_symbol.strip().upper()
    per_rule = collect_reference_fields_from_plan(plan)
    targets: List[Tuple[str, str, Set[str]]] = []
    for rule in plan.rules:
        fields = per_rule.get(rule.name)
        if not fields:
            continue
        for rule_symbol in rule.symbols:
            symbol = rule_symbol.strip().upper()
            if symbol != scheduled:
                continue
            targets.append((rule.name, symbol, set(fields)))
    return targets


async def capture_references_for_plan(
    tms_user,
    *,
    symbol: str,
    plan: StrategyPlanAST,
) -> List[ReferenceRow]:
    rows: List[ReferenceRow] = []
    flat_cache: Dict[str, dict] = {}
    captured_at = datetime.now(timezone.utc)
    for target_rule, target_symbol, fields in _targets_for_plan(plan, symbol):
        if target_symbol not in flat_cache:
            flat_cache[target_symbol] = await _fetch_symbol_flat(tms_user, target_symbol)
        flat = flat_cache[target_symbol]
        for field_key in sorted(fields):
            source = _source_label(field_key)
            raw_value = flat.get(field_key)
            if raw_value in (None, ""):
                if source == "nepse_alpha":
                    details = get_script_details(target_symbol, force_refresh=True)
                    if not getattr(details, "available", False):
                        raise ReferenceCaptureError(
                            "REFERENCE_CAPTURE_FAILED",
                            f"Nepse Alpha data is unavailable for {target_symbol}.",
                            symbol=target_symbol,
                            field_key=field_key,
                            source=source,
                        )
                raise ReferenceCaptureError(
                    "REFERENCE_VALUE_REQUIRED",
                    f"Cannot capture {field_key} for {target_symbol}.",
                    symbol=target_symbol,
                    field_key=field_key,
                    expected_type=_field_type_for_key(field_key),
                    source=source,
                )
            field_type, numeric_value, text_value, boolean_value = _typed_row_value(field_key, raw_value)
            rows.append(
                ReferenceRow(
                    rule_name=target_rule,
                    symbol=target_symbol,
                    field_key=field_key,
                    field_type=field_type,
                    numeric_value=numeric_value,
                    text_value=text_value,
                    boolean_value=boolean_value,
                    captured_at=captured_at,
                    source=source,
                )
            )
    return rows


async def capture_references_for_preview_plan(
    tms_user,
    *,
    plan: StrategyPlanAST,
) -> ReferenceStore:
    from utils.strategy_builder.reference_store import ReferenceStore

    per_rule = collect_reference_fields_from_plan(plan)
    rows: List[ReferenceRow] = []
    flat_cache: Dict[str, dict] = {}
    captured_at = datetime.now(timezone.utc)
    for rule in plan.rules:
        fields = per_rule.get(rule.name)
        if not fields:
            continue
        for rule_symbol in rule.symbols:
            symbol = rule_symbol.strip().upper()
            flat: Optional[dict] = None
            for attempt in range(1, REFERENCE_CAPTURE_MAX_RETRIES + 1):
                try:
                    if symbol not in flat_cache:
                        flat_cache[symbol] = await _fetch_symbol_flat(tms_user, symbol)
                    flat = flat_cache[symbol]
                    break
                except ReferenceCaptureError:
                    flat_cache.pop(symbol, None)
                    if attempt >= REFERENCE_CAPTURE_MAX_RETRIES:
                        flat = None
                    else:
                        await asyncio.sleep(min(0.25 * (2 ** (attempt - 1)), 1.5))
            if flat is None:
                continue
            try:
                for field_key in sorted(fields):
                    source = _source_label(field_key)
                    raw_value = flat.get(field_key)
                    if raw_value in (None, ""):
                        if source == "nepse_alpha":
                            details = get_script_details(symbol, force_refresh=True)
                            if not getattr(details, "available", False):
                                raise ReferenceCaptureError(
                                    "REFERENCE_CAPTURE_FAILED",
                                    f"Nepse Alpha data is unavailable for {symbol}.",
                                    symbol=symbol,
                                    field_key=field_key,
                                    source=source,
                                )
                        raise ReferenceCaptureError(
                            "REFERENCE_VALUE_REQUIRED",
                            f"Cannot capture {field_key} for {symbol}.",
                            symbol=symbol,
                            field_key=field_key,
                            expected_type=_field_type_for_key(field_key),
                            source=source,
                        )
                    field_type, numeric_value, text_value, boolean_value = _typed_row_value(field_key, raw_value)
                    rows.append(
                        ReferenceRow(
                            rule_name=rule.name,
                            symbol=symbol,
                            field_key=field_key,
                            field_type=field_type,
                            numeric_value=numeric_value,
                            text_value=text_value,
                            boolean_value=boolean_value,
                            captured_at=captured_at,
                            source=source,
                        )
                    )
            except ReferenceCaptureError:
                continue
    return ReferenceStore.from_rows(rows)


async def capture_references_for_order(
    db,
    client_id: str,
    symbol: str,
    plan: StrategyPlanAST,
    *,
    rule_name: str | None = None,
) -> List[ReferenceRow]:
    from utils.tms_client_resolver import get_tms_user_for_client

    tms_user = await get_tms_user_for_client(client_id, db)
    rows = await capture_references_for_plan(tms_user, symbol=symbol, plan=plan)
    if rule_name:
        rows = [row for row in rows if row.rule_name == rule_name]
    return rows


async def capture_references_preview(
    tms_user,
    *,
    symbol: str,
    plan: StrategyPlanAST,
) -> Dict[str, Dict[str, Any]]:
    preview: Dict[str, Dict[str, Any]] = {}
    rows = await capture_references_for_plan(tms_user, symbol=symbol, plan=plan)
    for row in rows:
        preview.setdefault(row.symbol, {})[row.field_key] = {
            "rule_name": row.rule_name,
            "field_type": row.field_type,
            "numeric_value": row.numeric_value,
            "text_value": row.text_value,
            "boolean_value": row.boolean_value,
            "source": row.source,
        }
    return preview
