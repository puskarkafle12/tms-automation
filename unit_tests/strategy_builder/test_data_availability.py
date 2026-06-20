"""Ensure strategy queries only reference fields and functions we can supply at runtime."""

import unittest
from typing import Any, List, Set

from utils.strategy_builder.feature_registry import (
    RUNTIME_FUNCTIONS,
    UNSUPPORTED_DATA_FIELDS,
    classify_field,
    classify_function,
)
from utils.strategy_builder.strategy_fields import FIELD_REGISTRY, is_known_field
from utils.strategy_builder.strategy_parser import parse_strategy_query
from utils.strategy_builder.strategy_validator import validate_strategy_plan


SCENARIO_QUERIES: List[str] = [
    """
STRATEGY_VERSION 1
SIDE BUY
RULE "Simple LTP" FOR SYMBOL "CZBIL" {
    WHEN ltp <= 200
    ORDER QUANTITY 100
    EXECUTE ONCE
}
""",
    """
STRATEGY_VERSION 1
SIDE BUY
RULE "RSI Confirm" FOR SYMBOL "CZBIL" {
    WHEN technical_rsi_14 > 30
    CONFIRM TRUE_FOR 2 SCANS
    ORDER QUANTITY 100
    EXECUTE ONCE
}
""",
    """
STRATEGY_VERSION 1
SIDE BUY
RULE "Eligibility" FOR SYMBOL "CZBIL" {
    ELIGIBILITY volume > 1000
    SIGNAL technical_rsi_14 < 70
    ORDER QUANTITY 10
    EXECUTE ONCE
}
""",
    """
STRATEGY_VERSION 1
SIDE SELL
POSITION_EXIT {
    SELL PERCENT_OF_HOLDING 50 WHEN profit_percent >= 5
}
RULE "Exit" FOR SYMBOL "CZBIL" {
    WHEN ltp > 0
    ORDER QUANTITY 10
    EXECUTE ONCE
}
""",
]


def _as_dict(node: Any) -> Any:
    if hasattr(node, "model_dump"):
        return node.model_dump()
    return node


def _collect_field_names(node: Any, names: Set[str]) -> None:
    node = _as_dict(node)
    if not isinstance(node, dict):
        return
    node_type = node.get("type")
    if node_type == "field":
        names.add(str(node.get("name") or ""))
    elif node_type == "comparison":
        _collect_field_names(node.get("left"), names)
        _collect_field_names(node.get("right"), names)
    elif node_type == "group":
        for child in node.get("children") or []:
            _collect_field_names(child, names)
    elif node_type == "function":
        for value in (node.get("arguments") or {}).values():
            _collect_field_names(value, names)
    elif node_type == "not":
        _collect_field_names(node.get("child"), names)
    elif node_type == "arithmetic":
        _collect_field_names(node.get("left"), names)
        _collect_field_names(node.get("right"), names)


def _collect_function_names(node: Any, names: Set[str]) -> None:
    node = _as_dict(node)
    if not isinstance(node, dict):
        return
    node_type = node.get("type")
    if node_type == "function":
        names.add(str(node.get("name") or "").upper())
        for value in (node.get("arguments") or {}).values():
            _collect_function_names(value, names)
    elif node_type == "comparison":
        _collect_function_names(node.get("left"), names)
        _collect_function_names(node.get("right"), names)
    elif node_type == "group":
        for child in node.get("children") or []:
            _collect_function_names(child, names)
    elif node_type == "not":
        _collect_function_names(node.get("child"), names)
    elif node_type == "arithmetic":
        _collect_function_names(node.get("left"), names)
        _collect_function_names(node.get("right"), names)


def _walk_plan_expressions(plan) -> tuple[Set[str], Set[str]]:
    fields: Set[str] = set()
    functions: Set[str] = set()
    for rule in plan.rules:
        for expr in (rule.when, rule.eligibility, rule.signal, rule.require):
            if expr:
                _collect_field_names(expr, fields)
                _collect_function_names(expr, functions)
        for item in rule.score_items or []:
            item_dict = _as_dict(item)
            if isinstance(item_dict, dict):
                _collect_field_names(item_dict.get("condition"), fields)
                _collect_function_names(item_dict.get("condition"), functions)
    if plan.position_exit:
        for action in plan.position_exit:
            action_dict = _as_dict(action)
            if isinstance(action_dict, dict):
                _collect_field_names(action_dict.get("when"), fields)
                _collect_function_names(action_dict.get("when"), functions)
    return fields, functions


class DataAvailabilityTest(unittest.TestCase):
    def test_unsupported_adx_field_classified(self):
        self.assertEqual(classify_field("technical_adx"), "UNSUPPORTED_DATA")
        self.assertEqual(classify_field("adx"), "UNSUPPORTED_DATA")

    def test_runtime_functions_in_feature_registry(self):
        for name in RUNTIME_FUNCTIONS:
            self.assertEqual(classify_function(name), "SUPPORTED_RUNTIME")

    def test_adx_query_rejected_by_validator(self):
        query = """
STRATEGY_VERSION 1
SIDE BUY
RULE "ADX" FOR SYMBOL "CZBIL" {
    WHEN technical_adx > 25
    ORDER QUANTITY 10
    EXECUTE ONCE
}
"""
        plan = parse_strategy_query(query)
        result = validate_strategy_plan(plan, strategy_type="Technical Buy", form_symbol="CZBIL")
        self.assertFalse(result.valid)
        self.assertEqual(result.status, "unsupported_data")
        unknown = [issue for issue in result.errors if issue.code == "UNKNOWN_FIELD"]
        self.assertTrue(any("technical_adx" in issue.message for issue in unknown))

    def test_unknown_function_rejected(self):
        query = """
STRATEGY_VERSION 1
SIDE BUY
RULE "BadFn" FOR SYMBOL "CZBIL" {
    WHEN FAKE_INDICATOR(ltp) > 1
    ORDER QUANTITY 10
    EXECUTE ONCE
}
"""
        plan = parse_strategy_query(query)
        result = validate_strategy_plan(plan, strategy_type="Technical Buy", form_symbol="CZBIL")
        self.assertFalse(result.valid)
        fn_errors = [
            issue
            for issue in result.errors
            if issue.code in {"UNKNOWN_FUNCTION", "UNSUPPORTED_FUNCTION"}
        ]
        self.assertTrue(fn_errors)

    def test_scenario_catalog_uses_only_known_fields(self):
        for query in SCENARIO_QUERIES:
            plan = parse_strategy_query(query)
            fields, functions = _walk_plan_expressions(plan)
            for field_name in fields:
                if not field_name:
                    continue
                self.assertTrue(
                    is_known_field(field_name),
                    f"Scenario uses unknown field {field_name!r}",
                )
                self.assertNotIn(
                    field_name.lower(),
                    UNSUPPORTED_DATA_FIELDS,
                    f"Scenario uses unsupported field {field_name!r}",
                )
            for fn_name in functions:
                self.assertIn(
                    fn_name,
                    RUNTIME_FUNCTIONS,
                    f"Scenario uses unsupported function {fn_name!r}",
                )

    def test_position_fields_exist_in_registry(self):
        for key in ("profit_percent", "drawdown_from_peak_percent", "entry_price"):
            self.assertIn(key, FIELD_REGISTRY, f"Missing position field {key}")


if __name__ == "__main__":
    unittest.main()
