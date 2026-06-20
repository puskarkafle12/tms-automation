from __future__ import annotations

from typing import Any, List

from utils.strategy_builder.strategy_models import ValidationIssue


def _comparison_bounds(node: dict) -> List[tuple]:
    bounds: List[tuple] = []
    if node.get("type") != "comparison":
        return bounds
    left = node.get("left") or {}
    right = node.get("right") or {}
    if left.get("type") == "field" and left.get("name") == "technical_rsi_14":
        op = node.get("operator")
        if right.get("type") == "literal" and isinstance(right.get("value"), (int, float)):
            bounds.append((op, float(right["value"])))
    return bounds


def lint_rule_expression(node: Any, warnings: List[ValidationIssue], suggestions: List[ValidationIssue]) -> None:
    if not isinstance(node, dict):
        return
    node_type = node.get("type")
    if node_type == "group" and node.get("logic") == "AND":
        rsi_bounds = []
        for child in node.get("children") or []:
            lint_rule_expression(child, warnings, suggestions)
            if isinstance(child, dict):
                rsi_bounds.extend(_comparison_bounds(child))
        gt_values = [value for op, value in rsi_bounds if op in {"gt", "gte"}]
        lt_values = [value for op, value in rsi_bounds if op in {"lt", "lte"}]
        if gt_values and lt_values and max(gt_values) >= min(lt_values):
            warnings.append(
                ValidationIssue(
                    code="CONTRADICTORY_CONDITIONS",
                    message="This AND group can never match because RSI bounds contradict each other.",
                )
            )
        if len(gt_values) >= 2 and max(gt_values) != min(gt_values):
            suggestions.append(
                ValidationIssue(
                    code="REDUNDANT_CONDITION",
                    message="Multiple RSI lower bounds are present; only the strictest bound matters.",
                )
            )
    elif node_type == "comparison":
        left = node.get("left") or {}
        right = node.get("right") or {}
        if left.get("name") == "technical_rsi_14" and node.get("operator") in {"gt", "gte"}:
            value = right.get("value")
            if isinstance(value, (int, float)) and value <= 0:
                warnings.append(
                    ValidationIssue(
                        code="BROAD_CONDITION",
                        message="RSI normally falls within the 0-100 range. This condition may match most valid RSI observations.",
                    )
                )
    elif node_type == "group":
        for child in node.get("children") or []:
            lint_rule_expression(child, warnings, suggestions)
    elif node_type == "not":
        lint_rule_expression(node.get("child"), warnings, suggestions)
