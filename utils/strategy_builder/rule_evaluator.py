from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from utils.strategy_builder.history_service import (
    TargetHistory,
    append_observation,
    changed_from_to,
    changed_to,
    change_percent,
    consecutive_moves,
    matches_in_last,
    previous_value,
    remains_above,
    remains_below,
)
from utils.strategy_builder.math_stats import depth_imbalance, rolling_slope, rolling_stddev, trend_direction
from utils.strategy_builder.derived_fields import sector_position_percent
from utils.strategy_builder.score_evaluator import evaluate_score_block
from utils.strategy_builder.strategy_models import ConditionResult, EvaluationResult, RuleBlock
from utils.strategy_builder.strategy_fields import get_field_metadata, is_known_field, resolve_field_name
from utils.strategy_builder.strategy_parser import format_expression
from utils.strategy_builder.reference_store import ReferenceEvaluationError, ReferenceStore


def _reference_field_key(arguments: Dict[str, Any]) -> str:
    field_arg = arguments.get("field")
    if isinstance(field_arg, dict) and field_arg.get("type") == "field":
        return str(resolve_field_name(str(field_arg.get("name") or "")) or field_arg.get("name") or "")
    return str(resolve_field_name(str(field_arg or "")) or field_arg or "")


def _resolve_value(
    node: Any,
    flat: Dict[str, Any],
    history: TargetHistory,
    *,
    reference_store: Optional["ReferenceStore"] = None,
    rule_name: str = "",
    symbol: str = "",
) -> Any:
    node = _node_as_dict(node)
    if not isinstance(node, dict):
        return node
    node_type = node.get("type")
    if node_type == "literal":
        return node.get("value")
    if node_type == "field":
        return flat.get(node.get("name"))
    if node_type == "arithmetic":
        left = _resolve_value(
            node.get("left"), flat, history, reference_store=reference_store, rule_name=rule_name, symbol=symbol
        )
        right = _resolve_value(
            node.get("right"), flat, history, reference_store=reference_store, rule_name=rule_name, symbol=symbol
        )
        if left is None or right is None:
            return None
        op = node.get("operator")
        if op == "+":
            return left + right
        if op == "-":
            return left - right
        if op == "*":
            return left * right
        if op == "/":
            return right != 0 and left / right
    if node_type == "function":
        name = str(node.get("name") or "").upper()
        if name == "REFERENCE":
            field_key = _reference_field_key(node.get("arguments") or {})
            if reference_store is None:
                raise ReferenceEvaluationError(
                    "REFERENCE_NOT_FOUND",
                    f"Missing schedule reference for {field_key}.",
                    rule_name=rule_name,
                    symbol=symbol,
                    field_key=field_key,
                )
            return reference_store.get_value(rule_name, symbol, field_key)
        result = _evaluate_node(
            node, flat, history, reference_store=reference_store, rule_name=rule_name, symbol=symbol
        )
        if result.actual_value is not None:
            return result.actual_value
    return None


def _node_as_dict(node: Any) -> Any:
    if hasattr(node, "model_dump"):
        return node.model_dump(mode="python")
    return node


def _expr_cache_key(node: Any) -> str:
    return json.dumps(_node_as_dict(node), sort_keys=True, default=str)


def _numeric_arg(
    args: Dict[str, Any],
    key: str,
    default: float,
    flat: Dict[str, Any],
    history: TargetHistory,
    *,
    reference_store: Optional["ReferenceStore"] = None,
    rule_name: str = "",
    symbol: str = "",
) -> float:
    raw = args.get(key, default)
    if isinstance(raw, dict):
        resolved = _resolve_value(
            raw, flat, history, reference_store=reference_store, rule_name=rule_name, symbol=symbol
        )
        return float(resolved if resolved is not None else default)
    return float(raw)


def _compare(left: Any, operator: str, right: Any) -> bool:
    if operator == "eq":
        return left == right
    if operator == "neq":
        return left != right
    if operator == "gt":
        return left is not None and right is not None and left > right
    if operator == "gte":
        return left is not None and right is not None and left >= right
    if operator == "lt":
        return left is not None and right is not None and left < right
    if operator == "lte":
        return left is not None and right is not None and left <= right
    if operator == "contains" and isinstance(left, str):
        return str(right) in left
    if operator == "not_contains" and isinstance(left, str):
        return str(right) not in left
    if operator == "in":
        values = right.get("values") if isinstance(right, dict) else right
        return left in (values or [])
    if operator == "not_in":
        values = right.get("values") if isinstance(right, dict) else right
        return left not in (values or [])
    return False


def _function_field_name(args: Dict[str, Any]) -> str:
    field_name = args.get("field")
    if isinstance(field_name, dict):
        field_name = field_name.get("name")
    return str(field_name or "")


def _depth_levels(flat: Dict[str, Any], side: str, levels: int) -> List[dict]:
    key = "buy_levels" if side == "BUY" else "sell_levels"
    return list(flat.get(key) or [])[:levels]


def _depth_imbalance_value(flat: Dict[str, Any], levels: int) -> Optional[float]:
    buy_qty = sum(float(row.get("quantity") or 0) for row in _depth_levels(flat, "BUY", levels))
    sell_qty = sum(float(row.get("quantity") or 0) for row in _depth_levels(flat, "SELL", levels))
    return depth_imbalance(buy_qty, sell_qty)


def evaluate_expression(
    node: Any,
    flat: Dict[str, Any],
    history: TargetHistory,
    *,
    reference_store: Optional["ReferenceStore"] = None,
    rule_name: str = "",
    symbol: str = "",
) -> ConditionResult:
    return _evaluate_node(
        node,
        flat,
        history,
        reference_store=reference_store,
        rule_name=rule_name,
        symbol=symbol,
    )


def _rolling_values(field_name: str, history: TargetHistory, window: int) -> List[float]:
    rows = history.observations.get(field_name) or []
    values = [row.value for row in rows[-window:] if row.value is not None]
    return [float(value) for value in values]


def _evaluate_node(
    node: Any,
    flat: Dict[str, Any],
    history: TargetHistory,
    *,
    reference_store: Optional["ReferenceStore"] = None,
    rule_name: str = "",
    symbol: str = "",
) -> ConditionResult:
    node = _node_as_dict(node)
    if not isinstance(node, dict):
        return ConditionResult(expression=str(node), matched=False)
    eval_kwargs = {
        "reference_store": reference_store,
        "rule_name": rule_name,
        "symbol": symbol,
    }
    node_type = node.get("type")
    if node_type == "group":
        logic = node.get("logic")
        children = node.get("children") or []
        results = [_evaluate_node(child, flat, history, **eval_kwargs) for child in children]
        matched = all(item.matched for item in results) if logic == "AND" else any(item.matched for item in results)
        return ConditionResult(expression=f"{logic} group", matched=matched)
    if node_type == "comparison":
        left = _resolve_value(node.get("left"), flat, history, **eval_kwargs)
        right = _resolve_value(node.get("right"), flat, history, **eval_kwargs)
        matched = _compare(left, node.get("operator"), right)
        return ConditionResult(
            expression=format_expression(node),
            matched=matched,
            actual_value=left,
            expected_value=right,
        )
    if node_type == "availability_check":
        expression = node.get("expression")
        if expression:
            ref_value = _resolve_value(expression, flat, history, **eval_kwargs)
            value = ref_value
            field_label = "REFERENCE"
        else:
            field = node.get("field")
            value = flat.get(field)
            field_label = field
        check = node.get("check")
        if check == "is_available":
            matched = value is not None
        elif check == "is_not_available":
            matched = value is None
        elif check == "is_null":
            matched = value is None
        else:
            matched = value is not None
        return ConditionResult(expression=f"{field_label} {check}", matched=matched, actual_value=value)
    if node_type == "function":
        name = str(node.get("name") or "").upper()
        args = node.get("arguments") or {}
        if name == "REFERENCE":
            field_key = _reference_field_key(args)
            if reference_store is None:
                raise ReferenceEvaluationError(
                    "REFERENCE_NOT_FOUND",
                    "Reference store is unavailable for REFERENCE evaluation.",
                    field_key=field_key,
                    symbol=symbol,
                    rule_name=rule_name,
                )
            value = reference_store.get_value(rule_name, symbol, field_key)
            return ConditionResult(
                expression=f"REFERENCE(field={field_key})",
                matched=value is not None,
                actual_value=value,
            )
        field_name = _function_field_name(args)
        if name == "CONSECUTIVE_DROPS":
            matched = consecutive_moves(
                field_name,
                history,
                direction="drop",
                count=int(_numeric_arg(args, "count", 2, flat, history)),
                min_each_change_pct=_numeric_arg(args, "min_each_change_pct", 0, flat, history),
                min_total_change_pct=_numeric_arg(args, "min_total_change_pct", 0, flat, history),
            )
            values = [row.value for row in (history.observations.get(field_name) or [])[-5:]]
            return ConditionResult(expression=f"CONSECUTIVE_DROPS({field_name})", matched=matched, values=values)
        if name == "CONSECUTIVE_RISES":
            matched = consecutive_moves(
                field_name,
                history,
                direction="rise",
                count=int(_numeric_arg(args, "count", 2, flat, history)),
                min_each_change_pct=_numeric_arg(args, "min_each_change_pct", 0, flat, history),
                min_total_change_pct=_numeric_arg(args, "min_total_change_pct", 0, flat, history),
            )
            values = [row.value for row in (history.observations.get(field_name) or [])[-5:]]
            return ConditionResult(expression=f"CONSECUTIVE_RISES({field_name})", matched=matched, values=values)
        if name == "CROSSES_ABOVE":
            threshold = _resolve_value(args.get("threshold") or args.get("value"), flat, history)
            current = flat.get(field_name)
            prev = previous_value(field_name, history, 1)
            matched = prev is not None and current is not None and prev <= threshold < current
            return ConditionResult(expression=f"CROSSES_ABOVE({field_name}, {threshold})", matched=matched, actual_value=current)
        if name == "CROSSES_BELOW":
            threshold = _resolve_value(args.get("threshold") or args.get("value"), flat, history)
            current = flat.get(field_name)
            prev = previous_value(field_name, history, 1)
            matched = prev is not None and current is not None and prev >= threshold > current
            return ConditionResult(expression=f"CROSSES_BELOW({field_name}, {threshold})", matched=matched, actual_value=current)
        if name == "REMAINS_ABOVE":
            threshold = float(_resolve_value(args.get("threshold") or args.get("value"), flat, history))
            scans = int(args.get("scans") or args.get("count") or 2)
            matched = remains_above(field_name, history, threshold, scans)
            return ConditionResult(expression=f"REMAINS_ABOVE({field_name}, {threshold}, {scans})", matched=matched)
        if name == "REMAINS_BELOW":
            threshold = float(_resolve_value(args.get("threshold") or args.get("value"), flat, history))
            scans = int(args.get("scans") or args.get("count") or 2)
            matched = remains_below(field_name, history, threshold, scans)
            return ConditionResult(expression=f"REMAINS_BELOW({field_name}, {threshold}, {scans})", matched=matched)
        if name == "PREVIOUS":
            scans_back = int(args.get("offset") or args.get("scans_back") or args.get("count") or 1)
            value = previous_value(field_name, history, scans_back)
            return ConditionResult(expression=f"PREVIOUS({field_name}, {scans_back})", matched=value is not None, actual_value=value)
        if name == "CHANGE":
            scans_back = int(args.get("scans_back") or args.get("count") or 1)
            current = flat.get(field_name)
            previous = previous_value(field_name, history, scans_back)
            value = None if current is None or previous is None else current - previous
            return ConditionResult(expression=f"CHANGE({field_name}, {scans_back})", matched=value is not None, actual_value=value)
        if name == "CHANGE_PERCENT":
            scans_back = int(args.get("scans_back") or args.get("count") or 1)
            value = change_percent(field_name, history, scans_back)
            return ConditionResult(expression=f"CHANGE_PERCENT({field_name}, {scans_back})", matched=value is not None, actual_value=value)
        if name == "CHANGED_TO":
            expected = args.get("value")
            matched = changed_to(field_name, history, expected)
            return ConditionResult(expression=f"CHANGED_TO({field_name}, {expected})", matched=matched, actual_value=flat.get(field_name))
        if name == "CHANGED_FROM_TO":
            from_value = args.get("from") or args.get("from_value")
            to_value = args.get("to") or args.get("to_value") or args.get("value")
            matched = changed_from_to(field_name, history, from_value, to_value)
            return ConditionResult(expression=f"CHANGED_FROM_TO({field_name})", matched=matched, actual_value=flat.get(field_name))
        if name == "STDDEV":
            window = int(args.get("scans") or args.get("window") or args.get("count") or 10)
            values = _rolling_values(field_name, history, window)
            actual = rolling_stddev(values)
            threshold = _resolve_value(args.get("threshold") or args.get("value"), flat, history)
            operator = str(args.get("operator") or "lt")
            matched = _compare(actual, operator, threshold) if actual is not None and threshold is not None else actual is not None
            return ConditionResult(expression=f"STDDEV({field_name}, {window})", matched=matched, actual_value=actual, expected_value=threshold)
        if name == "SLOPE":
            window = int(args.get("scans") or args.get("window") or args.get("count") or 5)
            values = _rolling_values(field_name, history, window)
            actual = rolling_slope(values)
            threshold = _resolve_value(args.get("threshold") or args.get("value"), flat, history)
            operator = str(args.get("operator") or "gt")
            matched = _compare(actual, operator, threshold) if actual is not None and threshold is not None else actual is not None
            return ConditionResult(expression=f"SLOPE({field_name}, {window})", matched=matched, actual_value=actual, expected_value=threshold)
        if name == "TREND":
            window = int(args.get("scans") or args.get("window") or args.get("count") or 5)
            min_move = float(args.get("min_move_pct") or args.get("min_each_change_pct") or 0.05)
            values = _rolling_values(field_name, history, window)
            actual = trend_direction(values, min_move_pct=min_move)
            expected = args.get("value")
            if isinstance(expected, dict) and expected.get("type") == "literal":
                expected = expected.get("value")
            matched = actual == expected if expected is not None else actual in {"UP", "DOWN"}
            return ConditionResult(expression=f"TREND({field_name}, {window})", matched=matched, actual_value=actual, expected_value=expected)
        if name == "DEPTH_ORDER_COUNT":
            side = str(args.get("side") or args.get("book") or "BUY").upper()
            levels = int(args.get("levels") or args.get("count") or 5)
            actual = len([row for row in _depth_levels(flat, side, levels) if float(row.get("quantity") or 0) > 0])
            threshold = _resolve_value(args.get("threshold") or args.get("value"), flat, history)
            operator = str(args.get("operator") or "gt")
            matched = _compare(actual, operator, threshold) if threshold is not None else actual > 0
            return ConditionResult(expression=f"DEPTH_ORDER_COUNT({side}, {levels})", matched=matched, actual_value=actual)
        if name == "DEPTH_IMBALANCE":
            levels_raw = _resolve_value(args.get("levels") or args.get("count"), flat, history) or 5
            levels = int(levels_raw)
            actual = _depth_imbalance_value(flat, levels)
            threshold = _resolve_value(args.get("threshold") or args.get("value"), flat, history)
            operator = str(args.get("operator") or "gt")
            matched = _compare(actual, operator, threshold) if actual is not None and threshold is not None else actual is not None
            return ConditionResult(expression=f"DEPTH_IMBALANCE({levels})", matched=matched, actual_value=actual, expected_value=threshold)
        if name == "DEPTH_IMBALANCE_REMAINS_ABOVE":
            levels = int(args.get("levels") or args.get("count") or 5)
            threshold = float(_resolve_value(args.get("value") or args.get("threshold"), flat, history) or 0)
            scans = int(args.get("scans") or args.get("count") or 2)
            key = f"depth_imbalance_{levels}"
            append_observation(history, key, _depth_imbalance_value(flat, levels), policy="count_only_value_change")
            matched = remains_above(key, history, threshold, scans)
            return ConditionResult(expression=name, matched=matched)
        if name == "DEPTH_IMBALANCE_REMAINS_BELOW":
            levels = int(args.get("levels") or args.get("count") or 5)
            threshold = float(_resolve_value(args.get("value") or args.get("threshold"), flat, history) or 0)
            scans = int(args.get("scans") or args.get("count") or 2)
            key = f"depth_imbalance_{levels}"
            append_observation(history, key, _depth_imbalance_value(flat, levels), policy="count_only_value_change")
            matched = remains_below(key, history, threshold, scans)
            return ConditionResult(expression=name, matched=matched)
        if name == "SPREAD_REMAINS_BELOW":
            threshold = float(_resolve_value(args.get("value") or args.get("threshold"), flat, history) or 0)
            scans = int(args.get("scans") or args.get("count") or 2)
            append_observation(history, "spread_percent", flat.get("spread_percent"), policy="count_only_value_change")
            matched = remains_below("spread_percent", history, threshold, scans)
            return ConditionResult(expression=name, matched=matched)
        if name == "DEPTH_PRESSURE_TREND":
            levels = int(args.get("levels") or args.get("count") or 5)
            scans = int(args.get("scans") or args.get("window") or 3)
            key = f"depth_imbalance_{levels}"
            append_observation(history, key, _depth_imbalance_value(flat, levels), policy="count_only_value_change")
            values = _rolling_values(key, history, scans)
            direction = trend_direction(values, min_move_pct=0.01) if values else None
            if values and values[-1] is not None:
                direction = "BUYING" if values[-1] > 0.05 else "SELLING" if values[-1] < -0.05 else "NEUTRAL"
            expected = args.get("value")
            if isinstance(expected, dict) and expected.get("type") == "literal":
                expected = expected.get("value")
            matched = direction == expected if expected else direction in {"BUYING", "SELLING"}
            return ConditionResult(expression=name, matched=matched, actual_value=direction, expected_value=expected)
        if name == "SECTOR_POSITION":
            base_field = field_name or str(args.get("field") or "")
            if isinstance(base_field, dict):
                base_field = base_field.get("name", "")
            actual = sector_position_percent(flat, base_field)
            threshold = _resolve_value(args.get("threshold") or args.get("value"), flat, history)
            operator = str(args.get("operator") or "gte")
            matched = _compare(actual, operator, threshold) if actual is not None and threshold is not None else False
            return ConditionResult(expression=f"SECTOR_POSITION({base_field})", matched=matched, actual_value=actual, expected_value=threshold)
        if name in {"UNIVERSE_PERCENTILE", "SECTOR_PERCENTILE"}:
            actual = flat.get(f"_universe_percentile_{field_name}") or flat.get(f"_sector_percentile_{field_name}")
            threshold = _resolve_value(args.get("threshold") or args.get("value"), flat, history)
            operator = str(args.get("operator") or "gte")
            matched = _compare(actual, operator, threshold) if actual is not None and threshold is not None else False
            return ConditionResult(expression=name, matched=matched, actual_value=actual, expected_value=threshold)
        if name == "TRUE_FOR_SCANS":
            condition = args.get("condition") or args.get("expr")
            scans = int(args.get("scans") or args.get("count") or 2)
            current_match = _evaluate_node(condition, flat, history).matched if condition else False
            key = _expr_cache_key(condition)
            streak = int(history.function_streaks.get(key, 0))
            streak = streak + 1 if current_match else 0
            history.function_streaks[key] = streak
            matched = streak >= scans
            return ConditionResult(expression=f"TRUE_FOR_SCANS(..., {scans})", matched=matched, actual_value=streak)
        if name == "MATCHES_IN_LAST":
            condition = args.get("condition") or args.get("expr")
            required = int(args.get("required") or args.get("count") or 1)
            window = int(args.get("window") or args.get("scans") or required)
            current_match = _evaluate_node(condition, flat, history).matched if condition else False
            key = _expr_cache_key(condition)
            values = list(history.condition_window.get(key, []))
            values.append(current_match)
            history.condition_window[key] = values[-max(window, 1) :]
            matched = matches_in_last(values, required, window)
            return ConditionResult(expression=f"MATCHES_IN_LAST(..., {required}, {window})", matched=matched)
        if name in {"AVERAGE", "MIN_VALUE", "MAX_VALUE", "SUM_VALUE"}:
            window = int(args.get("window") or args.get("count") or 5)
            values = _rolling_values(field_name, history, window)
            if not values:
                return ConditionResult(expression=name, matched=False)
            if name == "AVERAGE":
                actual = sum(values) / len(values)
            elif name == "MIN_VALUE":
                actual = min(values)
            elif name == "MAX_VALUE":
                actual = max(values)
            else:
                actual = sum(values)
            threshold = _resolve_value(args.get("threshold") or args.get("value"), flat, history)
            operator = str(args.get("operator") or "gte")
            matched = _compare(actual, operator, threshold) if threshold is not None else actual is not None
            return ConditionResult(expression=name, matched=matched, actual_value=actual, expected_value=threshold)
        if name == "DEPTH_QUANTITY":
            side = str(args.get("side") or args.get("book") or "BUY").upper()
            levels = int(args.get("levels") or args.get("count") or 5)
            key = "buy_levels" if side == "BUY" else "sell_levels"
            rows = flat.get(key) or []
            actual = sum(float(row.get("quantity") or 0) for row in rows[:levels])
            threshold = _resolve_value(args.get("threshold") or args.get("value"), flat, history)
            operator = str(args.get("operator") or "gt")
            matched = _compare(actual, operator, threshold) if threshold is not None else actual > 0
            return ConditionResult(expression=f"DEPTH_QUANTITY({side}, {levels})", matched=matched, actual_value=actual)
    if node_type == "not":
        child = _evaluate_node(node.get("child"), flat, history)
        return ConditionResult(expression=f"NOT ({child.expression})", matched=not child.matched)
    return ConditionResult(expression=str(node_type), matched=False)


def _apply_confirmation(rule: RuleBlock, when_matched: bool, history: TargetHistory) -> tuple[bool, str]:
    confirmation = rule.confirmation
    if confirmation.mode == "immediate":
        return when_matched, "MATCHED" if when_matched else "NOT_MATCHED"
    if confirmation.mode == "true_for_scans":
        required = int(confirmation.scans or 1)
        if when_matched:
            history.confirmation_streak += 1
        else:
            history.confirmation_streak = 0
        matched = history.confirmation_streak >= required
        status = "CONFIRMED" if matched else f"WAITING_CONFIRMATION_{history.confirmation_streak}/{required}"
        return matched, status
    if confirmation.mode == "matches_in_last":
        required = int(confirmation.required or 1)
        window = int(confirmation.window or required)
        key = f"rule:{rule.rule_id}:confirm"
        values = list(history.condition_window.get(key, []))
        values.append(when_matched)
        history.condition_window[key] = values[-max(window, 1) :]
        matched = matches_in_last(values, required, window)
        status = "CONFIRMED" if matched else f"WAITING_MATCHES_{sum(values)}/{required}"
        return matched, status
    return when_matched, "MATCHED" if when_matched else "NOT_MATCHED"


def evaluate_rule(
    rule: RuleBlock,
    symbol: str,
    flat: Dict[str, Any],
    history: TargetHistory,
    *,
    trigger_on_cross: bool = True,
    reference_store: Optional["ReferenceStore"] = None,
) -> EvaluationResult:
    eval_kwargs = {
        "reference_store": reference_store,
        "rule_name": rule.name,
        "symbol": symbol,
    }
    if history.executed and (rule.execution.frequency or "once") in {"once", "once_per_symbol"}:
        return EvaluationResult(symbol=symbol, rule_name=rule.name, matched=False, status="ALREADY_EXECUTED", final_result=False)

    signal_expr = rule.signal or rule.when
    if not signal_expr and not rule.score_items and not rule.use_strategy:
        return EvaluationResult(symbol=symbol, rule_name=rule.name, matched=False, status="INVALID_RULE", final_result=False)

    conditions: List[ConditionResult] = []
    if rule.eligibility:
        eligibility = _evaluate_node(rule.eligibility, flat, history, **eval_kwargs)
        conditions.append(eligibility)
        if not eligibility.matched:
            return EvaluationResult(symbol=symbol, rule_name=rule.name, matched=False, status="NOT_ELIGIBLE", conditions=conditions, final_result=False)

    if rule.require:
        required = _evaluate_node(rule.require, flat, history, **eval_kwargs)
        conditions.append(required)
        if not required.matched:
            return EvaluationResult(symbol=symbol, rule_name=rule.name, matched=False, status="REQUIRE_FAILED", conditions=conditions, final_result=False)

    score_breakdown: List[Dict[str, Any]] = []
    final_score: Optional[float] = None
    if rule.score_items:
        def _score_eval_node(node, flat_arg, history_arg):
            return _evaluate_node(node, flat_arg, history_arg, **eval_kwargs)

        score_ok, score_breakdown, final_score = evaluate_score_block(
            rule.score_items,
            flat,
            history,
            required_score=float(rule.required_score or 0),
            evaluate_node=_score_eval_node,
        )
        if not score_ok:
            return EvaluationResult(
                symbol=symbol,
                rule_name=rule.name,
                matched=False,
                status=f"SCORE_{final_score}_LT_{rule.required_score}",
                conditions=conditions,
                final_result=False,
                score_breakdown=score_breakdown,
                final_score=final_score,
            )

    if rule.use_strategy and not signal_expr and not rule.score_items:
        matched, status = _apply_confirmation(rule, True, history)
        if trigger_on_cross and matched and history.rule_was_true:
            matched = False
            status = "ALREADY_TRIGGERED"
        history.rule_was_true = True
        return EvaluationResult(
            symbol=symbol,
            rule_name=rule.name,
            matched=matched,
            status=status or "MATCHED",
            conditions=conditions,
            final_result=matched,
        )

    result = _evaluate_node(signal_expr, flat, history, **eval_kwargs) if signal_expr else ConditionResult(expression="score_only", matched=True)
    conditions.append(result)
    when_matched = result.matched and (not rule.score_items or bool(final_score and final_score >= float(rule.required_score or 0)))
    matched, status = _apply_confirmation(rule, when_matched, history)
    if trigger_on_cross and matched and history.rule_was_true:
        matched = False
        status = "ALREADY_TRIGGERED"
    history.rule_was_true = bool(when_matched)
    return EvaluationResult(
        symbol=symbol,
        rule_name=rule.name,
        matched=matched,
        status=status,
        conditions=conditions,
        final_result=matched,
        score_breakdown=score_breakdown,
        final_score=final_score,
    )


def update_history_from_snapshot(history: TargetHistory, flat: Dict[str, Any]) -> None:
    ltp_policy = "count_only_new_trade"
    for field_name, value in flat.items():
        meta = get_field_metadata(field_name)
        if not is_known_field(field_name):
            continue
        if meta and meta.get("category") == "position":
            continue
        policy = ltp_policy if field_name == "ltp" else "count_only_value_change"
        append_kwargs = {
            "source_timestamp": flat.get("last_traded_at") if field_name == "ltp" else flat.get("received_at"),
            "policy": policy,
        }
        append_observation(history, field_name, value, **append_kwargs)
        if field_name.startswith("technical_") and not field_name.endswith(("_sector_high", "_sector_low")):
            history.previous_enum_values[field_name] = history.previous_values.get(field_name)
        history.previous_values[field_name] = value
