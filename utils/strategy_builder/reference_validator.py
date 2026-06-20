from __future__ import annotations

from typing import Any, Dict, List, Set

from utils.strategy_builder.feature_registry import MARKET_DEPTH_FIELD_KEYS, UNSUPPORTED_DATA_FIELDS
from utils.strategy_builder.reference_dependencies import collect_reference_fields
from utils.strategy_builder.strategy_fields import get_field_metadata, is_known_field, resolve_field_name
from utils.strategy_builder.strategy_models import StrategyPlanAST, ValidationIssue

REFERENCE_BLOCKED_FIELDS = {
    "symbol",
    "last_traded_at",
    *MARKET_DEPTH_FIELD_KEYS,
    *UNSUPPORTED_DATA_FIELDS,
}

TEMPORAL_FUNCTIONS = {
    "PREVIOUS",
    "CHANGE",
    "CHANGE_PERCENT",
    "CONSECUTIVE_DROPS",
    "CONSECUTIVE_RISES",
    "AVERAGE",
    "MIN_VALUE",
    "MAX_VALUE",
    "SUM_VALUE",
    "STDDEV",
    "SLOPE",
    "TREND",
    "TRUE_FOR_SCANS",
    "MATCHES_IN_LAST",
}

NUMERIC_DATA_TYPES = {"decimal", "number", "float", "integer"}
TEXT_DATA_TYPES = {"text", "enum", "string"}
BOOLEAN_DATA_TYPES = {"boolean", "bool"}


class ReferenceValidationError(ValueError):
    def __init__(self, code: str, message: str, *, field_key: str | None = None, symbol: str | None = None):
        super().__init__(message)
        self.code = code
        self.field_key = field_key
        self.symbol = symbol


def _as_dict(node: Any) -> Any:
    if hasattr(node, "model_dump"):
        return node.model_dump()
    return node


def _reference_source_field(arguments: Dict[str, Any]) -> str | None:
    field_arg = arguments.get("field")
    if field_arg is None:
        return None
    if isinstance(field_arg, dict) and field_arg.get("type") == "field":
        return resolve_field_name(str(field_arg.get("name") or ""))
    if isinstance(field_arg, dict) and field_arg.get("type") == "function":
        return None
    return resolve_field_name(str(field_arg))


def _field_data_type(field_key: str) -> str:
    meta = get_field_metadata(field_key) or {}
    return str(meta.get("data_type") or "decimal").lower()


def _validate_reference_source(field_key: str | None, errors: List[ValidationIssue], path: str = "") -> str | None:
    if not field_key:
        errors.append(
            ValidationIssue(
                code="REFERENCE_FIELD_UNKNOWN",
                message="REFERENCE(field=...) requires a registered field name.",
            )
        )
        return None
    if not is_known_field(field_key):
        errors.append(
            ValidationIssue(
                code="REFERENCE_FIELD_UNKNOWN",
                message=f"Unknown reference source field: {field_key}",
            )
        )
        return None
    if field_key in REFERENCE_BLOCKED_FIELDS:
        errors.append(
            ValidationIssue(
                code="REFERENCE_FIELD_NOT_ALLOWED",
                message=f"Field {field_key} cannot be used in REFERENCE(field=...).",
            )
        )
        return None
    meta = get_field_metadata(field_key) or {}
    if str(meta.get("category") or "").lower() == "position":
        errors.append(
            ValidationIssue(
                code="REFERENCE_FIELD_NOT_ALLOWED",
                message=f"Position field {field_key} is not available at schedule time.",
            )
        )
        return None
    return field_key


def _validate_reference_node(node: dict, errors: List[ValidationIssue], *, parent_is_arithmetic: bool = False) -> str | None:
    if node.get("type") != "function" or str(node.get("name") or "").upper() != "REFERENCE":
        return None
    field_key = _validate_reference_source(_reference_source_field(node.get("arguments") or {}), errors)
    if not field_key:
        return None
    data_type = _field_data_type(field_key)
    if parent_is_arithmetic and data_type not in NUMERIC_DATA_TYPES:
        errors.append(
            ValidationIssue(
                code="REFERENCE_TYPE_MISMATCH",
                message=f"REFERENCE(field={field_key}) cannot be used in numeric arithmetic.",
            )
        )
    return field_key


def _validate_expression(node: Any, errors: List[ValidationIssue], *, parent_is_arithmetic: bool = False) -> None:
    node = _as_dict(node)
    if not isinstance(node, dict):
        return
    node_type = node.get("type")
    if node_type == "function":
        name = str(node.get("name") or "").upper()
        args = node.get("arguments") or {}
        if name == "REFERENCE":
            _validate_reference_node(node, errors, parent_is_arithmetic=parent_is_arithmetic)
            return
        if name in TEMPORAL_FUNCTIONS:
            field_arg = args.get("field")
            if isinstance(field_arg, dict) and field_arg.get("type") == "function":
                if str(field_arg.get("name") or "").upper() == "REFERENCE":
                    errors.append(
                        ValidationIssue(
                            code="REFERENCE_TEMPORAL_USE_INVALID",
                            message=f"{name} cannot use REFERENCE(field=...) as its field argument.",
                        )
                    )
            for value in args.values():
                _validate_expression(value, errors, parent_is_arithmetic=False)
            return
        for value in args.values():
            _validate_expression(value, errors, parent_is_arithmetic=False)
    elif node_type == "arithmetic":
        left = node.get("left")
        right = node.get("right")
        if isinstance(left, dict):
            _validate_reference_node(left, errors, parent_is_arithmetic=True)
            _validate_expression(left, errors, parent_is_arithmetic=True)
        if isinstance(right, dict):
            _validate_reference_node(right, errors, parent_is_arithmetic=True)
            _validate_expression(right, errors, parent_is_arithmetic=True)
    elif node_type == "comparison":
        _validate_expression(node.get("left"), errors)
        _validate_expression(node.get("right"), errors)
    elif node_type == "group":
        for child in node.get("children") or []:
            _validate_expression(child, errors)
    elif node_type == "not":
        _validate_expression(node.get("child"), errors)
    elif node_type == "availability_check":
        expression = node.get("expression")
        if expression:
            expr_dict = _as_dict(expression)
            if not (
                isinstance(expr_dict, dict)
                and expr_dict.get("type") == "function"
                and str(expr_dict.get("name") or "").upper() == "REFERENCE"
            ):
                errors.append(
                    ValidationIssue(
                        code="REFERENCE_TYPE_MISMATCH",
                        message="Availability checks on references must use REFERENCE(field=...).",
                    )
                )
            else:
                _validate_reference_node(expr_dict, errors)
        field = node.get("field")
        if field and not expression:
            pass


def validate_reference_expressions(plan: StrategyPlanAST) -> List[ValidationIssue]:
    errors: List[ValidationIssue] = []
    for rule in plan.rules:
        for expr in (rule.when, rule.eligibility, rule.signal, rule.require):
            if expr:
                _validate_expression(expr, errors)
        for item in rule.score_items or []:
            item_dict = _as_dict(item)
            if isinstance(item_dict, dict) and item_dict.get("condition"):
                _validate_expression(item_dict["condition"], errors)
    return errors
