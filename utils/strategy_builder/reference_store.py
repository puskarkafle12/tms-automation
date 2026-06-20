from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from sqlalchemy.orm import Session

from models.scheduled_field_reference import ScheduledFieldReference


class ReferenceEvaluationError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        rule_name: str | None = None,
        symbol: str | None = None,
        field_key: str | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.rule_name = rule_name
        self.symbol = symbol
        self.field_key = field_key


@dataclass
class ReferenceRow:
    rule_name: str
    symbol: str
    field_key: str
    field_type: str
    numeric_value: Optional[float] = None
    text_value: Optional[str] = None
    boolean_value: Optional[bool] = None
    captured_at: Optional[datetime] = None
    source: Optional[str] = None
    refreshed_at: Optional[datetime] = None
    refresh_count: int = 0


class ReferenceStore:
    def __init__(self, rows: Optional[list[ReferenceRow]] = None) -> None:
        self._rows: Dict[Tuple[str, str, str], ReferenceRow] = {}
        if rows:
            for row in rows:
                self._rows[(row.rule_name, row.symbol.upper(), row.field_key)] = row

    @classmethod
    def from_rows(cls, rows: list[ReferenceRow]) -> "ReferenceStore":
        return cls(rows)

    def get_row(self, rule_name: str, symbol: str, field_key: str) -> Optional[ReferenceRow]:
        return self._rows.get((rule_name, symbol.upper(), field_key))

    def get(self, rule_name: str, symbol: str, field_key: str) -> Any:
        return self.get_value(rule_name, symbol, field_key)

    def get_value(self, rule_name: str, symbol: str, field_key: str) -> Any:
        row = self.get_row(rule_name, symbol, field_key)
        if row is None:
            raise ReferenceEvaluationError(
                "REFERENCE_NOT_FOUND",
                f"Missing schedule reference for {field_key} ({rule_name}, {symbol}).",
                rule_name=rule_name,
                symbol=symbol.upper(),
                field_key=field_key,
            )
        if row.field_type in {"decimal", "number", "float", "integer"}:
            if row.numeric_value is None:
                raise ReferenceEvaluationError(
                    "REFERENCE_NOT_FOUND",
                    f"Reference value for {field_key} is missing.",
                    rule_name=rule_name,
                    symbol=symbol.upper(),
                    field_key=field_key,
                )
            return row.numeric_value
        if row.field_type in {"text", "enum", "string"}:
            if row.text_value is None:
                raise ReferenceEvaluationError(
                    "REFERENCE_NOT_FOUND",
                    f"Reference value for {field_key} is missing.",
                    rule_name=rule_name,
                    symbol=symbol.upper(),
                    field_key=field_key,
                )
            return row.text_value
        if row.field_type in {"boolean", "bool"}:
            if row.boolean_value is None:
                raise ReferenceEvaluationError(
                    "REFERENCE_NOT_FOUND",
                    f"Reference value for {field_key} is missing.",
                    rule_name=rule_name,
                    symbol=symbol.upper(),
                    field_key=field_key,
                )
            return row.boolean_value
        if row.numeric_value is not None:
            return row.numeric_value
        if row.text_value is not None:
            return row.text_value
        if row.boolean_value is not None:
            return row.boolean_value
        raise ReferenceEvaluationError(
            "REFERENCE_NOT_FOUND",
            f"Reference value for {field_key} is missing.",
            rule_name=rule_name,
            symbol=symbol.upper(),
            field_key=field_key,
        )

    def is_reference_available(self, rule_name: str, symbol: str, field_key: str) -> bool:
        row = self.get_row(rule_name, symbol, field_key)
        if row is None:
            return False
        if row.field_type in {"decimal", "number", "float", "integer"}:
            return row.numeric_value is not None
        if row.field_type in {"text", "enum", "string"}:
            return row.text_value is not None
        if row.field_type in {"boolean", "bool"}:
            return row.boolean_value is not None
        return any(value is not None for value in (row.numeric_value, row.text_value, row.boolean_value))

    def to_rows(self) -> list[ReferenceRow]:
        return list(self._rows.values())

    def fill_missing_from(self, other: Optional["ReferenceStore"]) -> "ReferenceStore":
        if other is None:
            return self
        merged = dict(self._rows)
        for key, row in other._rows.items():
            merged.setdefault(key, row)
        return ReferenceStore(list(merged.values()))

    def summary(self) -> Dict[str, Dict[str, Dict[str, Any]]]:
        grouped: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for row in self._rows.values():
            grouped.setdefault(row.symbol.upper(), {}).setdefault(row.field_key, {})
            grouped[row.symbol.upper()][row.field_key] = {
                "rule_name": row.rule_name,
                "field_type": row.field_type,
                "numeric_value": row.numeric_value,
                "text_value": row.text_value,
                "boolean_value": row.boolean_value,
                "captured_at": row.captured_at.isoformat() if row.captured_at else None,
                "source": row.source,
            }
        return grouped


def _row_from_model(model: ScheduledFieldReference) -> ReferenceRow:
    return ReferenceRow(
        rule_name=model.rule_name,
        symbol=model.symbol.upper(),
        field_key=model.field_key,
        field_type=model.field_type,
        numeric_value=model.numeric_value,
        text_value=model.text_value,
        boolean_value=model.boolean_value,
        captured_at=model.captured_at,
        source=model.source,
        refreshed_at=model.refreshed_at,
        refresh_count=int(model.refresh_count or 0),
    )


def load_reference_store(db: Session, order_id: int) -> ReferenceStore:
    rows = (
        db.query(ScheduledFieldReference)
        .filter(ScheduledFieldReference.scheduled_order_id == order_id)
        .all()
    )
    return ReferenceStore.from_rows([_row_from_model(row) for row in rows])


def build_preview_reference_store(
    plan,
    preview_refs: Dict[str, Dict[str, Any]],
) -> ReferenceStore:
    from utils.strategy_builder.reference_dependencies import collect_reference_fields_from_plan
    from utils.strategy_builder.strategy_fields import resolve_field_name

    rows: list[ReferenceRow] = []
    per_rule = collect_reference_fields_from_plan(plan)
    for rule in plan.rules:
        fields = per_rule.get(rule.name) or set()
        if not fields:
            continue
        for rule_symbol in rule.symbols:
            symbol = rule_symbol.strip().upper()
            symbol_refs = preview_refs.get(symbol) or preview_refs.get(rule_symbol) or {}
            for field_key in sorted(fields):
                raw = symbol_refs.get(field_key)
                if raw is None:
                    raise ReferenceEvaluationError(
                        "REFERENCE_VALUE_REQUIRED",
                        f"Preview input missing reference value for {field_key} ({symbol}).",
                        rule_name=rule.name,
                        symbol=symbol,
                        field_key=field_key,
                    )
                if isinstance(raw, dict):
                    field_type = str(raw.get("field_type") or "decimal")
                    numeric_value = raw.get("numeric_value")
                    text_value = raw.get("text_value")
                    boolean_value = raw.get("boolean_value")
                else:
                    from utils.strategy_builder.reference_capture import _field_type_for_key, _typed_row_value

                    field_type, numeric_value, text_value, boolean_value = _typed_row_value(
                        resolve_field_name(field_key),
                        raw,
                    )
                rows.append(
                    ReferenceRow(
                        rule_name=rule.name,
                        symbol=symbol,
                        field_key=resolve_field_name(field_key),
                        field_type=field_type,
                        numeric_value=numeric_value,
                        text_value=text_value,
                        boolean_value=boolean_value,
                    )
                )
    return ReferenceStore.from_rows(rows)


def hydrate_strategy_config_references(db: Session, order_id: int, strategy_config: dict) -> dict:
    config = dict(strategy_config or {})
    if not config.get("uses_field_references"):
        return config
    if config.get("field_reference_rows"):
        return config
    store = load_reference_store(db, order_id)
    if not store.to_rows():
        return config
    from utils.strategy_builder.reference_schedule import serialize_reference_rows

    config["field_reference_rows"] = serialize_reference_rows(store.to_rows())
    return config


def persist_reference_rows(db: Session, order_id: int, rows: list[ReferenceRow]) -> None:
    db.query(ScheduledFieldReference).filter(
        ScheduledFieldReference.scheduled_order_id == order_id
    ).delete(synchronize_session=False)
    for row in rows:
        db.add(
            ScheduledFieldReference(
                scheduled_order_id=order_id,
                rule_name=row.rule_name,
                symbol=row.symbol.upper(),
                field_key=row.field_key,
                field_type=row.field_type,
                numeric_value=row.numeric_value,
                text_value=row.text_value,
                boolean_value=row.boolean_value,
                captured_at=row.captured_at,
                source=row.source,
                refreshed_at=row.refreshed_at,
                refresh_count=row.refresh_count or 0,
            )
        )


def build_preview_reference_store(plan, preview_references: Dict[str, Dict[str, Any]]) -> ReferenceStore:
    from utils.strategy_builder.reference_dependencies import collect_reference_fields_from_plan

    rows: list[ReferenceRow] = []
    per_rule = collect_reference_fields_from_plan(plan)
    for rule in plan.rules:
        fields = per_rule.get(rule.name) or set()
        for symbol in rule.symbols:
            symbol_key = symbol.upper()
            symbol_refs = preview_references.get(symbol_key) or preview_references.get(symbol) or {}
            for field_key in fields:
                payload = symbol_refs.get(field_key)
                if not isinstance(payload, dict):
                    continue
                rows.append(
                    ReferenceRow(
                        rule_name=rule.name,
                        symbol=symbol_key,
                        field_key=field_key,
                        field_type=str(payload.get("field_type") or "decimal"),
                        numeric_value=payload.get("numeric_value"),
                        text_value=payload.get("text_value"),
                        boolean_value=payload.get("boolean_value"),
                        source=payload.get("source"),
                    )
                )
    return ReferenceStore(rows)
