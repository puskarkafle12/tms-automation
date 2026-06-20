from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from utils.strategy_builder.reference_store import ReferenceRow, ReferenceStore, load_reference_store
from utils.strategy_builder.strategy_fields import resolve_field_name
from utils.strategy_builder.strategy_models import StrategyPlanAST


@dataclass
class ReferenceDisplayValues:
    reference_ltp: Optional[float] = None
    trigger_price: Optional[float] = None
    reference_ltp_captured_at: Optional[datetime] = None


def display_values_for_scheduled_order(db: Session, order) -> ReferenceDisplayValues:
    strategy_config = dict(order.strategy_config or {})
    store = load_reference_store(db, order.order_id)
    if not store.to_rows():
        store = _store_from_strategy_config(strategy_config)
    return display_values_from_strategy_config(
        strategy_config=strategy_config,
        symbol=order.symbol or order.script_name,
        store=store,
    )


def display_values_from_strategy_config(
    *,
    strategy_config: dict,
    symbol: str,
    store: Optional[ReferenceStore] = None,
) -> ReferenceDisplayValues:
    compiled_plan = strategy_config.get("compiled_plan")
    if not compiled_plan:
        return ReferenceDisplayValues()

    try:
        plan = compiled_plan if isinstance(compiled_plan, StrategyPlanAST) else StrategyPlanAST.model_validate(compiled_plan)
    except Exception:
        return ReferenceDisplayValues()

    reference_store = store or _store_from_strategy_config(strategy_config)
    if not reference_store.to_rows():
        return ReferenceDisplayValues()

    symbol_key = str(symbol or "").upper()
    reference_ltp = _lookup_reference_ltp(plan, symbol_key, reference_store)
    trigger_price = _lookup_trigger_price(plan, symbol_key, reference_store)
    captured_at = _lookup_reference_ltp_captured_at(plan, symbol_key, reference_store)
    return ReferenceDisplayValues(
        reference_ltp=reference_ltp,
        trigger_price=trigger_price,
        reference_ltp_captured_at=captured_at,
    )


def _store_from_strategy_config(strategy_config: dict) -> ReferenceStore:
    rows: list[ReferenceRow] = []
    for item in strategy_config.get("field_reference_rows") or []:
        if not isinstance(item, dict):
            continue
        captured_at = _parse_datetime(item.get("captured_at"))
        rows.append(
            ReferenceRow(
                rule_name=str(item.get("rule_name") or ""),
                symbol=str(item.get("symbol") or "").upper(),
                field_key=resolve_field_name(str(item.get("field_key") or "")),
                field_type=str(item.get("field_type") or "decimal"),
                numeric_value=item.get("numeric_value"),
                text_value=item.get("text_value"),
                boolean_value=item.get("boolean_value"),
                captured_at=captured_at,
                source=item.get("source"),
            )
        )
    return ReferenceStore(rows)


def _lookup_reference_ltp(plan: StrategyPlanAST, symbol: str, store: ReferenceStore) -> Optional[float]:
    for rule in _rules_for_symbol(plan, symbol):
        row = store.get_row(rule.name, symbol, "ltp")
        if row and row.numeric_value is not None:
            return float(row.numeric_value)
    return None


def _lookup_reference_ltp_captured_at(plan: StrategyPlanAST, symbol: str, store: ReferenceStore) -> Optional[datetime]:
    for rule in _rules_for_symbol(plan, symbol):
        row = store.get_row(rule.name, symbol, "ltp")
        if row and row.captured_at is not None:
            return row.captured_at
    return None


def _lookup_trigger_price(plan: StrategyPlanAST, symbol: str, store: ReferenceStore) -> Optional[float]:
    for rule in _rules_for_symbol(plan, symbol):
        for expression in (rule.when, rule.signal, rule.eligibility):
            threshold = _find_ltp_threshold(expression, rule.name, symbol, store)
            if threshold is not None:
                return float(threshold)
    return None


def _rules_for_symbol(plan: StrategyPlanAST, symbol: str):
    symbol_key = symbol.upper()
    for rule in plan.rules:
        if symbol_key in {item.upper() for item in rule.symbols}:
            yield rule


def _find_ltp_threshold(node: Any, rule_name: str, symbol: str, store: ReferenceStore) -> Optional[float]:
    node = _node_as_dict(node)
    if not isinstance(node, dict):
        return None
    node_type = node.get("type")
    if node_type == "comparison":
        left = node.get("left")
        right = node.get("right")
        if _is_ltp_field(left):
            return _eval_numeric_expression(right, rule_name, symbol, store)
        if _is_ltp_field(right):
            return _eval_numeric_expression(left, rule_name, symbol, store)
        return None
    if node_type == "group":
        for child in node.get("children") or []:
            threshold = _find_ltp_threshold(child, rule_name, symbol, store)
            if threshold is not None:
                return threshold
    if node_type == "not":
        return _find_ltp_threshold(node.get("child"), rule_name, symbol, store)
    return None


def _eval_numeric_expression(node: Any, rule_name: str, symbol: str, store: ReferenceStore) -> Optional[float]:
    node = _node_as_dict(node)
    if not isinstance(node, dict):
        try:
            return float(node)
        except (TypeError, ValueError):
            return None
    node_type = node.get("type")
    if node_type == "literal":
        try:
            return float(node.get("value"))
        except (TypeError, ValueError):
            return None
    if node_type == "function" and str(node.get("name") or "").upper() == "REFERENCE":
        field_key = _reference_field_key(node.get("arguments") or {})
        try:
            value = store.get_value(rule_name, symbol, field_key)
        except Exception:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    if node_type == "arithmetic":
        left = _eval_numeric_expression(node.get("left"), rule_name, symbol, store)
        right = _eval_numeric_expression(node.get("right"), rule_name, symbol, store)
        if left is None or right is None:
            return None
        operator = node.get("operator")
        if operator == "+":
            return left + right
        if operator == "-":
            return left - right
        if operator == "*":
            return left * right
        if operator == "/" and right != 0:
            return left / right
    return None


def _reference_field_key(arguments: dict) -> str:
    field_arg = arguments.get("field")
    if isinstance(field_arg, dict):
        field_arg = field_arg.get("name") or field_arg.get("value")
    return resolve_field_name(str(field_arg or ""))


def _is_ltp_field(node: Any) -> bool:
    node = _node_as_dict(node)
    return isinstance(node, dict) and node.get("type") == "field" and resolve_field_name(str(node.get("name") or "")) == "ltp"


def _node_as_dict(node: Any) -> Any:
    if hasattr(node, "model_dump"):
        return node.model_dump(mode="python")
    return node


def _parse_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
