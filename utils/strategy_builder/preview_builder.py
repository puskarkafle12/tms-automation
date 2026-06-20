from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from utils.strategy_builder.constants import DEFAULT_RULE_ORDER_QUANTITY
from utils.strategy_builder.history_service import TargetHistory
from utils.strategy_builder.preview_field_metadata import (
    DIRECT_PRICE_FIELDS,
    field_display_name,
    infer_formatter,
    infer_price_conversion,
    infer_unit,
    operator_display,
)
from utils.strategy_builder.preview_models import (
    ConditionPreview,
    ConfirmationPreview,
    ExecutionPolicyPreview,
    ExecutionPricePreview,
    PreviewWarning,
    QuantityPreview,
    RulePreview,
    TriggerPreview,
)
from utils.strategy_builder.strategy_fields import get_field_metadata
from utils.strategy_builder.strategy_models import EvaluationResult, RuleBlock

HOLDING_DEPENDENT_MODES = frozenset({"percent_of_holding", "all_available", "sell_up_to"})


def _is_holding_dependent_mode(mode: Optional[str]) -> bool:
    return str(mode or "").lower() in HOLDING_DEPENDENT_MODES


def format_preview_value(field_key: Optional[str], value: Any, *, formatter: Optional[str] = None) -> str:
    if value is None or value == "":
        return "—"
    fmt = formatter or infer_formatter(field_key or "")
    if fmt == "price":
        try:
            return f"Rs. {float(value):,.2f}"
        except (TypeError, ValueError):
            return str(value)
    if fmt == "percentage":
        try:
            return f"{float(value):,.2f}%"
        except (TypeError, ValueError):
            return str(value)
    if fmt == "integer":
        try:
            return f"{int(float(value)):,}"
        except (TypeError, ValueError):
            return str(value)
    if fmt == "boolean":
        if isinstance(value, bool):
            return "Available" if value else "Unavailable"
        lowered = str(value).lower()
        if lowered in {"true", "1", "yes"}:
            return "Available"
        if lowered in {"false", "0", "no"}:
            return "Unavailable"
        return str(value)
    if fmt == "enum" or fmt == "text":
        return str(value)
    try:
        number = float(value)
        if math.isfinite(number) and float(number).is_integer():
            return f"{int(number):,}"
        return f"{number:,.2f}"
    except (TypeError, ValueError):
        return str(value)


def _node_as_dict(node: Any) -> Any:
    if hasattr(node, "model_dump"):
        return node.model_dump(mode="python")
    return node


def _literal_value(node: Any) -> Any:
    node = _node_as_dict(node)
    if isinstance(node, dict) and node.get("type") == "literal":
        return node.get("value")
    return node


def _field_name_from_node(node: Any) -> Optional[str]:
    node = _node_as_dict(node)
    if isinstance(node, dict) and node.get("type") == "field":
        return str(node.get("name") or "")
    if isinstance(node, dict) and node.get("type") == "function":
        args = node.get("arguments") or {}
        field = args.get("field")
        if isinstance(field, dict) and field.get("type") == "field":
            return str(field.get("name") or "")
        if isinstance(field, str):
            return field
    return None


def _estimate_price_boundary(
    field_key: str,
    operator: str,
    target_value: float,
    flat: Dict[str, Any],
) -> Tuple[Optional[float], bool, List[PreviewWarning]]:
    warnings: List[PreviewWarning] = []
    conversion = infer_price_conversion(field_key)
    op = str(operator or "").lower()

    if conversion == "direct" and field_key == "ltp":
        return float(target_value), True, warnings

    if conversion == "direct" and field_key in DIRECT_PRICE_FIELDS:
        return float(target_value), field_key in {"ltp", "best_bid", "best_ask"}, warnings

    if conversion == "52_week_position":
        low = flat.get("fifty_two_week_low")
        high = flat.get("fifty_two_week_high")
        if low is None or high is None or float(high) == float(low):
            warnings.append(
                PreviewWarning(
                    code="MISSING_52_WEEK_RANGE",
                    message="52-week high or low is unavailable.",
                )
            )
            return None, False, warnings
        pct = float(target_value)
        if pct < 0 or pct > 100:
            warnings.append(
                PreviewWarning(
                    code="INVALID_RANGE",
                    message="52-week range position must be between 0 and 100.",
                )
            )
        price = float(low) + (pct / 100.0) * (float(high) - float(low))
        return price, False, warnings

    if conversion == "intraday_position":
        low = flat.get("low")
        high = flat.get("high")
        if low is None or high is None or float(high) == float(low):
            warnings.append(
                PreviewWarning(code="MISSING_INTRADAY_RANGE", message="Intraday high or low is unavailable.")
            )
            return None, False, warnings
        pct = float(target_value)
        price = float(low) + (pct / 100.0) * (float(high) - float(low))
        return price, False, warnings

    if conversion == "distance_from_52w_high":
        high = flat.get("fifty_two_week_high")
        if high in (None, 0):
            warnings.append(PreviewWarning(code="MISSING_52_WEEK_RANGE", message="52-week high is unavailable."))
            return None, False, warnings
        if op in {"lte", "lt"}:
            price = float(high) * (1.0 + float(target_value) / 100.0)
        else:
            price = float(high) * (1.0 + float(target_value) / 100.0)
        return price, False, warnings

    if conversion == "distance_from_52w_low":
        low = flat.get("fifty_two_week_low")
        if low in (None, 0):
            warnings.append(PreviewWarning(code="MISSING_52_WEEK_RANGE", message="52-week low is unavailable."))
            return None, False, warnings
        price = float(low) * (1.0 + float(target_value) / 100.0)
        return price, False, warnings

    if conversion == "distance_from_day_high":
        high = flat.get("high")
        if high in (None, 0):
            warnings.append(PreviewWarning(code="MISSING_INTRADAY_RANGE", message="Day high is unavailable."))
            return None, False, warnings
        price = float(high) * (1.0 + float(target_value) / 100.0)
        return price, False, warnings

    if conversion == "distance_from_day_low":
        low = flat.get("low")
        if low in (None, 0):
            warnings.append(PreviewWarning(code="MISSING_INTRADAY_RANGE", message="Day low is unavailable."))
            return None, False, warnings
        price = float(low) * (1.0 + float(target_value) / 100.0)
        return price, False, warnings

    return None, False, warnings


def _describe_comparison_node(node: Dict[str, Any], flat: Dict[str, Any]) -> ConditionPreview:
    left_node = node.get("left")
    right_node = node.get("right")
    operator = str(node.get("operator") or "")
    field_key = _field_name_from_node(left_node) or ""
    target_value = _literal_value(right_node)
    actual_value = flat.get(field_key) if field_key else None
    label = field_display_name(field_key) if field_key else "Condition"
    op_text = operator_display(operator)
    strategy_text = f"{label} {op_text} {format_preview_value(field_key, target_value)}"

    estimated_price = None
    is_exact = False
    warnings: List[PreviewWarning] = []
    if field_key and target_value is not None:
        try:
            numeric_target = float(target_value)
            estimated_price, is_exact, warnings = _estimate_price_boundary(field_key, operator, numeric_target, flat)
        except (TypeError, ValueError):
            pass

    if field_key == "position_in_52_week_range_percent":
        strategy_text = f"52-week range position {op_text} {format_preview_value(field_key, target_value, formatter='percentage')}"
    elif field_key == "position_in_intraday_range_percent":
        strategy_text = f"Intraday range position {op_text} {format_preview_value(field_key, target_value, formatter='percentage')}"
    elif field_key == "distance_from_52_week_high_percent":
        strategy_text = f"Distance from 52-week high {op_text} {format_preview_value(field_key, target_value, formatter='percentage')}"
    elif field_key == "distance_from_52_week_low_percent":
        strategy_text = f"Distance from 52-week low {op_text} {format_preview_value(field_key, target_value, formatter='percentage')}"

    return ConditionPreview(
        strategy_text=strategy_text,
        current_value=actual_value,
        target_value=target_value,
        current_display=format_preview_value(field_key, actual_value),
        target_display=format_preview_value(field_key, target_value),
        value_unit=infer_unit(field_key),
        estimated_price=estimated_price,
        estimated_price_available=estimated_price is not None,
        is_exact_price=is_exact,
    )


def _describe_function_node(node: Dict[str, Any], flat: Dict[str, Any]) -> ConditionPreview:
    name = str(node.get("name") or "").upper()
    args = node.get("arguments") or {}
    field_key = _field_name_from_node({"type": "function", "arguments": args, "name": name}) or ""
    label = field_display_name(field_key) if field_key else "Field"
    threshold = args.get("threshold")
    if isinstance(threshold, dict):
        threshold = _literal_value(threshold)
    scans = args.get("scans") or args.get("count") or args.get("window")

    estimated_price = None
    is_exact = False
    if name in {"CROSSES_ABOVE", "CROSSES_BELOW", "REMAINS_ABOVE", "REMAINS_BELOW"} and field_key == "ltp" and threshold is not None:
        try:
            estimated_price = float(threshold)
            is_exact = True
        except (TypeError, ValueError):
            pass

    if name == "CROSSES_ABOVE":
        text = f"{label} crosses above {format_preview_value(field_key, threshold)}"
    elif name == "CROSSES_BELOW":
        text = f"{label} crosses below {format_preview_value(field_key, threshold)}"
    elif name == "REMAINS_ABOVE":
        text = f"{label} remains above {format_preview_value(field_key, threshold)} for {scans or 1} scan(s)"
    elif name == "REMAINS_BELOW":
        text = f"{label} remains below {format_preview_value(field_key, threshold)} for {scans or 1} scan(s)"
    elif name == "CONSECUTIVE_RISES":
        min_pct = args.get("min_total_change_pct")
        suffix = f" with at least {min_pct}% total gain" if min_pct is not None else ""
        text = f"{label} rises for {args.get('count', scans or 2)} consecutive observation(s){suffix}"
    elif name == "CONSECUTIVE_DROPS":
        min_pct = args.get("min_total_change_pct")
        suffix = f" with at least {min_pct}% total loss" if min_pct is not None else ""
        text = f"{label} drops for {args.get('count', scans or 2)} consecutive observation(s){suffix}"
    elif name == "TRUE_FOR_SCANS":
        text = f"Condition remains true for {args.get('scans', scans or 1)} scan(s)"
    elif name == "MATCHES_IN_LAST":
        text = f"Condition matches {args.get('required', 1)} of last {args.get('window', scans or 1)} scan(s)"
    elif name == "REFERENCE":
        field_ref = args.get("field") or "ltp"
        text = f"REFERENCE({field_ref})"
    elif name in {"UNIVERSE_PERCENTILE", "SECTOR_PERCENTILE"}:
        text = f"{name.replace('_', ' ').title()} for {label}"
    else:
        rendered_args = ", ".join(f"{key}={value}" for key, value in args.items())
        text = f"{name}({rendered_args})"

    return ConditionPreview(
        strategy_text=text,
        current_display=format_preview_value(field_key, flat.get(field_key)) if field_key else None,
        target_display=format_preview_value(field_key, threshold) if threshold is not None else None,
        value_unit=infer_unit(field_key) if field_key else None,
        estimated_price=estimated_price,
        estimated_price_available=estimated_price is not None,
        is_exact_price=is_exact,
    )


def _walk_condition_nodes(node: Any, flat: Dict[str, Any]) -> List[ConditionPreview]:
    node = _node_as_dict(node)
    if not isinstance(node, dict):
        return [ConditionPreview(strategy_text=str(node))]
    node_type = node.get("type")
    if node_type == "group":
        logic = str(node.get("logic") or "AND")
        items: List[ConditionPreview] = []
        children = node.get("children") or []
        for index, child in enumerate(children):
            child_items = _walk_condition_nodes(child, flat)
            for child_index, item in enumerate(child_items):
                if index > 0 and child_index == 0:
                    item.connector = logic
                items.append(item)
        return items
    if node_type == "comparison":
        return [_describe_comparison_node(node, flat)]
    if node_type == "function":
        return [_describe_function_node(node, flat)]
    if node_type == "availability_check":
        target = node.get("expression") or node.get("field")
        field_key = _field_name_from_node(target) if isinstance(target, dict) else str(target or "")
        check = str(node.get("check") or "is_available").replace("_", " ")
        return [
            ConditionPreview(
                strategy_text=f"{field_display_name(field_key) if field_key else 'Field'} {check}",
                value_unit=infer_unit(field_key) if field_key else None,
            )
        ]
    if node_type == "not":
        child_items = _walk_condition_nodes(node.get("child"), flat)
        if child_items:
            first = child_items[0]
            first.strategy_text = f"NOT ({first.strategy_text})"
            return child_items
    return [ConditionPreview(strategy_text=str(node_type or "condition"))]


def _enrich_conditions_from_evaluation(
    conditions: List[ConditionPreview],
    evaluation: EvaluationResult,
) -> List[ConditionPreview]:
    eval_conditions = [item for item in (evaluation.conditions or []) if item.expression]
    enriched: List[ConditionPreview] = []
    for index, item in enumerate(conditions):
        merged = item.model_copy()
        if index < len(eval_conditions):
            result = eval_conditions[index]
            merged.matched = result.matched
            if result.actual_value is not None:
                merged.current_value = result.actual_value
                field_guess = None
                if " " in result.expression:
                    field_guess = result.expression.split(" ")[0]
                merged.current_display = format_preview_value(field_guess, result.actual_value)
            if result.expected_value is not None:
                merged.target_value = result.expected_value
                merged.target_display = format_preview_value(None, result.expected_value)
        enriched.append(merged)
    if not enriched and eval_conditions:
        for result in eval_conditions:
            enriched.append(
                ConditionPreview(
                    strategy_text=str(result.expression),
                    matched=result.matched,
                    current_value=result.actual_value,
                    target_value=result.expected_value,
                    current_display=format_preview_value(None, result.actual_value),
                    target_display=format_preview_value(None, result.expected_value),
                )
            )
    return enriched


def build_trigger_preview(
    rule: RuleBlock,
    flat: Dict[str, Any],
    evaluation: EvaluationResult,
) -> TriggerPreview:
    expr = rule.signal or rule.when
    raw_conditions = _walk_condition_nodes(expr, flat) if expr else []
    for item in raw_conditions:
        if item.strategy_text and "Condition" in item.strategy_text:
            continue
    conditions = _enrich_conditions_from_evaluation(raw_conditions, evaluation)

    for item in conditions:
        if item.estimated_price is None and item.target_value is not None:
            field_key = None
            for key in flat:
                if item.strategy_text and field_display_name(key) in item.strategy_text:
                    field_key = key
                    break
            if field_key:
                try:
                    price, exact, _ = _estimate_price_boundary(field_key, "gte", float(item.target_value), flat)
                    item.estimated_price = price
                    item.estimated_price_available = price is not None
                    item.is_exact_price = exact
                except (TypeError, ValueError):
                    pass

    logic = None
    expr_dict = _node_as_dict(expr)
    if isinstance(expr_dict, dict) and expr_dict.get("type") == "group":
        logic = str(expr_dict.get("logic") or "AND")

    primary = conditions[0] if conditions else ConditionPreview(strategy_text="No condition configured")
    if expr_dict and isinstance(expr_dict, dict) and expr_dict.get("type") == "comparison":
        primary = _describe_comparison_node(expr_dict, flat)
        primary.matched = evaluation.conditions[0].matched if evaluation.conditions else None
        if evaluation.conditions:
            result = evaluation.conditions[0]
            primary.current_value = result.actual_value
            primary.target_value = result.expected_value
            field_key = _field_name_from_node(expr_dict.get("left")) or ""
            primary.current_display = format_preview_value(field_key, result.actual_value)
            primary.target_display = format_preview_value(field_key, result.expected_value)

    estimated_price = None
    is_exact = False
    for item in conditions:
        if item.estimated_price is not None:
            estimated_price = item.estimated_price
            is_exact = item.is_exact_price
            if logic != "OR":
                break

    source_fields: Dict[str, Any] = {}
    for key in ("fifty_two_week_low", "fifty_two_week_high", "low", "high"):
        if flat.get(key) is not None:
            source_fields[key] = flat.get(key)

    strategy_text = primary.strategy_text
    if len(conditions) > 1:
        strategy_text = " · ".join(item.strategy_text for item in conditions[:3])
        if len(conditions) > 3:
            strategy_text += f" · +{len(conditions) - 3} more"

    kind = "derived_price_boundary"
    if is_exact:
        kind = "direct_price"
    elif estimated_price is None:
        if "52-week range" in strategy_text or "intraday range position" in strategy_text:
            kind = "derived_price_boundary"
        else:
            kind = "non_price_condition"

    price_display = "—"
    if estimated_price is not None:
        price_display = format_preview_value("ltp", estimated_price)
        if not is_exact:
            price_display = f"{price_display} (est.)"
    elif kind == "derived_price_boundary":
        price_display = "Unavailable"

    return TriggerPreview(
        kind=kind,
        strategy_text=strategy_text,
        estimated_price=estimated_price,
        estimated_price_display=price_display,
        estimated_price_available=estimated_price is not None,
        is_exact_price=is_exact,
        current_value=primary.current_value,
        target_value=primary.target_value,
        current_display=primary.current_display,
        target_display=primary.target_display,
        value_unit=primary.value_unit,
        source_fields=source_fields,
        conditions=conditions,
        logic=logic,
    )


def build_quantity_preview(
    rule: RuleBlock,
    *,
    plan_side: str,
    flat: Dict[str, Any],
    current_holding: Optional[int],
    form_qty: int = 0,
    holding_retrieval_failed: bool = False,
) -> QuantityPreview:
    order = rule.order
    mode = str(order.mode or "quantity").lower()
    value = order.value
    warnings: List[PreviewWarning] = []
    note = (
        "Final quantity is recalculated immediately before execution."
        if _is_holding_dependent_mode(mode) or mode == "all_available"
        else None
    )

    if holding_retrieval_failed and plan_side.upper() == "SELL" and (
        _is_holding_dependent_mode(mode) or mode == "quantity"
    ):
        return QuantityPreview(
            mode=mode,
            configured_value=value,
            estimated_quantity_display="Unavailable",
            is_final=False,
            description=_quantity_description(mode, value),
            note=note,
            warnings=[
                PreviewWarning(
                    code="HOLDING_UNAVAILABLE",
                    message="Current holding could not be retrieved.",
                )
            ],
        )

    holding_qty = int(current_holding or 0)
    if plan_side.upper() == "SELL" and holding_qty <= 0 and (
        _is_holding_dependent_mode(mode) or (mode == "quantity" and value and float(value) > 0)
    ):
        warnings.append(
            PreviewWarning(
                code="ZERO_HOLDING",
                message="No sellable holding is currently available.",
            )
        )

    ltp = float(flat.get("ltp") or 0)
    from utils.strategy_builder.execution_sizing import resolve_order_quantity

    estimated = resolve_order_quantity(
        order_mode=mode,
        order_value=value,
        ltp=ltp if ltp > 0 else None,
        holding_qty=holding_qty,
        form_qty=form_qty,
    )
    if estimated <= 0 and mode == "quantity":
        estimated = int(value or form_qty or DEFAULT_RULE_ORDER_QUANTITY)

    if mode == "quantity" and plan_side.upper() == "SELL" and holding_qty > 0 and estimated > holding_qty:
        warnings.append(
            PreviewWarning(
                code="FIXED_SELL_QTY_EXCEEDS_HOLDING",
                message=f"Fixed quantity {estimated} exceeds current holding {holding_qty}.",
            )
        )

    display_qty: Optional[str]
    if estimated > 0:
        display_qty = f"{estimated:,}"
    elif holding_retrieval_failed:
        display_qty = "Unavailable"
    else:
        display_qty = "0" if holding_qty == 0 and plan_side.upper() == "SELL" else "—"

    return QuantityPreview(
        mode=mode,
        configured_value=value,
        current_holding=current_holding if current_holding is not None else None,
        estimated_quantity=estimated if estimated > 0 else (0 if holding_qty == 0 else None),
        estimated_quantity_display=display_qty,
        is_final=False if _is_holding_dependent_mode(mode) or mode == "all_available" else True,
        description=_quantity_description(mode, value),
        note=note,
        warnings=warnings,
    )


def _quantity_description(mode: str, value: Optional[float]) -> str:
    if mode == "percent_of_holding":
        pct = int(value or 100)
        return f"Sell {pct}% of current holding"
    if mode == "all_available":
        return "Sell all available holding"
    if mode == "sell_up_to":
        return f"Sell up to {int(value or 0):,}"
    if mode == "amount":
        return f"Budget Rs. {float(value or 0):,.2f}"
    if mode == "quantity" and value == -1:
        return "Quantity from form"
    if mode == "quantity":
        return "Fixed quantity"
    if mode in {"top_buy_qty", "top_sell_qty", "partial_top_buy", "partial_top_sell"}:
        return mode.replace("_", " ").title()
    return mode.replace("_", " ")


def build_confirmation_preview(rule: RuleBlock, evaluation: EvaluationResult, history: TargetHistory) -> ConfirmationPreview:
    confirmation = rule.confirmation
    mode = str(confirmation.mode or "immediate").lower()
    required = int(confirmation.scans or confirmation.required or 1)
    matched = int(history.confirmation_streak or 0)
    status = str(evaluation.status or "")
    if status.startswith("WAITING_CONFIRMATION_") and "/" in status:
        parts = status.replace("WAITING_CONFIRMATION_", "").split("/")
        if len(parts) == 2:
            try:
                matched = int(parts[0])
                required = int(parts[1])
            except ValueError:
                pass
    if mode == "immediate":
        display = "Immediate"
    elif mode == "true_for_scans":
        display = f"{matched} / {required} scans"
    elif mode == "matches_in_last":
        display = f"{confirmation.required or 1} of last {confirmation.window or required} scans"
    else:
        display = mode
    return ConfirmationPreview(mode=mode, matched_scans=matched, required_scans=required, display=display)


def build_execution_price_preview(rule: RuleBlock, flat: Dict[str, Any]) -> ExecutionPricePreview:
    source = str(rule.order.price_source or "ltp").lower()
    mapping = {
        "ltp": ("Current LTP", flat.get("ltp")),
        "top_buy": ("Current top-buy price", flat.get("best_bid")),
        "best_bid": ("Current best bid", flat.get("best_bid")),
        "top_sell": ("Current top-sell price", flat.get("best_ask")),
        "best_ask": ("Current best ask", flat.get("best_ask")),
    }
    description, price = mapping.get(source, ("Default execution price", flat.get("ltp")))
    return ExecutionPricePreview(
        mode=source,
        description=description,
        estimated_price=float(price) if price not in (None, "") else None,
        estimated_price_display=format_preview_value("ltp", price) if price not in (None, "") else "—",
    )


def build_execution_policy_preview(rule: RuleBlock) -> ExecutionPolicyPreview:
    trigger = str(rule.execution.trigger or "on_cross")
    frequency = str(rule.execution.frequency or "once_per_symbol")
    trigger_label = "Level" if trigger == "level" else "On cross"
    frequency_labels = {
        "once": "Once",
        "once_per_symbol": "Once per symbol",
        "once_per_day": "Once per market day",
    }
    return ExecutionPolicyPreview(
        trigger_mode=trigger,
        frequency=frequency,
        max_slippage_pct=rule.execution.max_slippage_pct,
        display=f"{trigger_label} · {frequency_labels.get(frequency, frequency)}",
    )


def _build_reason(trigger: TriggerPreview, evaluation: EvaluationResult) -> Optional[str]:
    if evaluation.matched:
        return "All checks passed."
    if trigger.current_display and trigger.target_display:
        return f"Current value is {trigger.current_display}; required is {trigger.target_display}."
    if trigger.conditions:
        first = trigger.conditions[0]
        if first.current_display and first.target_display:
            return f"Current {first.current_display}; at least {first.target_display} is required."
    return None


def build_rule_preview(
    *,
    rule: RuleBlock,
    symbol: str,
    plan_side: str,
    flat: Dict[str, Any],
    evaluation: EvaluationResult,
    history: TargetHistory,
    status_label: str,
    live_ltp: Optional[float],
    reference_ltp: Optional[float],
    current_holding: Optional[int] = None,
    holding_retrieval_failed: bool = False,
    blocker: Optional[str] = None,
    message: Optional[str] = None,
    nepse_alpha_available: Optional[bool] = None,
    strategy: Optional[str] = None,
    strategy_action: Optional[str] = None,
) -> RulePreview:
    trigger = build_trigger_preview(rule, flat, evaluation)
    if strategy and trigger.estimated_price is not None:
        trigger.is_exact_price = True

    quantity = build_quantity_preview(
        rule,
        plan_side=plan_side,
        flat=flat,
        current_holding=current_holding,
        form_qty=int(getattr(rule.order, "value", None) or 0) if rule.order.mode == "quantity" else 0,
        holding_retrieval_failed=holding_retrieval_failed,
    )
    confirmation = build_confirmation_preview(rule, evaluation, history)
    execution_price = build_execution_price_preview(rule, flat)
    execution_policy = build_execution_policy_preview(rule)
    reason = _build_reason(trigger, evaluation)

    warnings = list(quantity.warnings)
    for item in trigger.conditions:
        if item.strategy_text and "UNIVERSE_PERCENTILE" in item.strategy_text.upper():
            warnings.append(
                PreviewWarning(
                    code="PREVIEW_ONLY_FUNCTION",
                    message="Preview supported; monitored scheduling is not supported for universe percentile.",
                )
            )

    preview = RulePreview(
        symbol=symbol,
        status=evaluation.status,
        status_label=status_label,
        matched=evaluation.matched,
        live_ltp=live_ltp,
        live_ltp_display=format_preview_value("ltp", live_ltp),
        reference_ltp=reference_ltp,
        reference_ltp_display=format_preview_value("ltp", reference_ltp) if reference_ltp is not None else None,
        trigger=trigger,
        quantity=quantity,
        confirmation=confirmation,
        execution_price=execution_price,
        execution_policy=execution_policy,
        reason=reason,
        warnings=warnings,
        blocker=blocker,
        message=message,
        nepse_alpha_available=nepse_alpha_available,
        strategy=strategy,
        strategy_action=strategy_action,
    )
    preview.__dict__["rule_name"] = rule.name
    return preview
