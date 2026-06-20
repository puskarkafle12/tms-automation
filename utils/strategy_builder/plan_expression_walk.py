from __future__ import annotations

from typing import Any, Set, Tuple

from utils.strategy_builder.strategy_models import StrategyPlanAST


def _as_dict(node: Any) -> Any:
    if hasattr(node, "model_dump"):
        return node.model_dump()
    return node


def collect_field_names(node: Any, names: Set[str]) -> None:
    node = _as_dict(node)
    if not isinstance(node, dict):
        return
    node_type = node.get("type")
    if node_type == "field":
        name = str(node.get("name") or "").strip()
        if name:
            names.add(name)
    elif node_type == "comparison":
        collect_field_names(node.get("left"), names)
        collect_field_names(node.get("right"), names)
    elif node_type == "group":
        for child in node.get("children") or []:
            collect_field_names(child, names)
    elif node_type == "function":
        name = str(node.get("name") or "").strip().upper()
        args = node.get("arguments") or {}
        if name == "REFERENCE":
            for key, value in args.items():
                if key != "field":
                    collect_field_names(value, names)
        else:
            for value in args.values():
                collect_field_names(value, names)
    elif node_type == "not":
        collect_field_names(node.get("child"), names)
    elif node_type == "arithmetic":
        collect_field_names(node.get("left"), names)
        collect_field_names(node.get("right"), names)
    elif node_type == "availability_check":
        expression = node.get("expression")
        if expression:
            collect_field_names(expression, names)
        else:
            field = str(node.get("field") or "").strip()
            if field:
                names.add(field)


def collect_function_names(node: Any, names: Set[str]) -> None:
    node = _as_dict(node)
    if not isinstance(node, dict):
        return
    node_type = node.get("type")
    if node_type == "function":
        name = str(node.get("name") or "").strip().upper()
        if name:
            names.add(name)
        for value in (node.get("arguments") or {}).values():
            collect_function_names(value, names)
    elif node_type == "comparison":
        collect_function_names(node.get("left"), names)
        collect_function_names(node.get("right"), names)
    elif node_type == "group":
        for child in node.get("children") or []:
            collect_function_names(child, names)
    elif node_type == "not":
        collect_function_names(node.get("child"), names)
    elif node_type == "arithmetic":
        collect_function_names(node.get("left"), names)
        collect_function_names(node.get("right"), names)


def walk_plan_expressions(plan: StrategyPlanAST) -> Tuple[Set[str], Set[str]]:
    fields: Set[str] = set()
    functions: Set[str] = set()
    for rule in plan.rules:
        for expr in (rule.when, rule.eligibility, rule.signal, rule.require):
            if expr:
                collect_field_names(expr, fields)
                collect_function_names(expr, functions)
        for item in rule.score_items or []:
            item_dict = _as_dict(item)
            if isinstance(item_dict, dict):
                collect_field_names(item_dict.get("condition"), fields)
                collect_function_names(item_dict.get("condition"), functions)
    if plan.position_exit:
        for action in plan.position_exit:
            action_dict = _as_dict(action)
            if isinstance(action_dict, dict):
                collect_field_names(action_dict.get("when"), fields)
                collect_function_names(action_dict.get("when"), functions)
    return fields, functions
