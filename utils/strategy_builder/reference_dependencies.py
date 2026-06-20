from __future__ import annotations

from typing import Any, Dict, Set

from utils.strategy_builder.strategy_fields import resolve_field_name
from utils.strategy_builder.strategy_models import StrategyPlanAST


def _as_dict(node: Any) -> Any:
    if hasattr(node, "model_dump"):
        return node.model_dump()
    return node


def _reference_source_field(arguments: Dict[str, Any]) -> str:
    field_arg = arguments.get("field")
    if isinstance(field_arg, dict) and field_arg.get("type") == "field":
        return str(field_arg.get("name") or "").strip()
    return str(field_arg or "").strip()


def collect_reference_fields(node: Any, names: Set[str] | None = None) -> Set[str]:
    collected = names if names is not None else set()
    node = _as_dict(node)
    if not isinstance(node, dict):
        return collected
    node_type = node.get("type")
    if node_type == "function" and str(node.get("name") or "").upper() == "REFERENCE":
        source = resolve_field_name(_reference_source_field(node.get("arguments") or {}))
        if source:
            collected.add(source)
        return collected
    if node_type == "comparison":
        collect_reference_fields(node.get("left"), collected)
        collect_reference_fields(node.get("right"), collected)
    elif node_type == "group":
        for child in node.get("children") or []:
            collect_reference_fields(child, collected)
    elif node_type == "function":
        for value in (node.get("arguments") or {}).values():
            collect_reference_fields(value, collected)
    elif node_type == "not":
        collect_reference_fields(node.get("child"), collected)
    elif node_type == "arithmetic":
        collect_reference_fields(node.get("left"), collected)
        collect_reference_fields(node.get("right"), collected)
    elif node_type == "availability_check":
        expression = node.get("expression")
        if expression:
            collect_reference_fields(expression, collected)
    return collected


def collect_reference_fields_from_plan(plan: StrategyPlanAST) -> Dict[str, Set[str]]:
    per_rule: Dict[str, Set[str]] = {}
    for rule in plan.rules:
        fields: Set[str] = set()
        for expr in (rule.when, rule.eligibility, rule.signal, rule.require):
            if expr:
                collect_reference_fields(expr, fields)
        for item in rule.score_items or []:
            item_dict = _as_dict(item)
            if isinstance(item_dict, dict) and item_dict.get("condition"):
                collect_reference_fields(item_dict["condition"], fields)
        if fields:
            per_rule[rule.name] = fields
    return per_rule


def plan_uses_reference(plan: StrategyPlanAST) -> bool:
    return bool(collect_reference_fields_from_plan(plan))


def all_reference_fields_from_plan(plan: StrategyPlanAST) -> Set[str]:
    merged: Set[str] = set()
    for fields in collect_reference_fields_from_plan(plan).values():
        merged.update(fields)
    return merged
