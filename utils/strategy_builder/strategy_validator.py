from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from utils.strategy_builder.constants import (
    MAX_CONDITIONS_PER_RULE,
    MAX_RULE_BLOCKS,
    MAX_SYMBOLS,
    RULE_BASED_BUY_STRATEGIES,
    RULE_BASED_SELL_STRATEGIES,
)
from utils.strategy_builder.feature_registry import classify_field, classify_function
from utils.strategy_builder.strategy_fields import is_known_field, resolve_field_name, suggest_fields_for_unknown, get_field_metadata
from utils.strategy_builder.strategy_models import (
    StrategyPlanAST,
    TargetPreview,
    ValidationIssue,
    ValidationResult,
)
from utils.strategy_builder.reference_validator import validate_reference_expressions
from utils.strategy_builder.execution_quantity import is_holding_dependent_mode
from utils.strategy_builder.strategy_linter import lint_rule_expression
from utils.strategies.strategy_query_catalog import (
    get_catalog_entry,
    is_delegatable_strategy,
    resolve_strategy_name,
    validate_strategy_params,
)


def _collect_symbols(plan: StrategyPlanAST) -> Set[str]:
    symbols: Set[str] = set()
    for rule in plan.rules:
        for symbol in rule.symbols:
            symbols.add(symbol.upper())
    return symbols


def _count_conditions(node: Any) -> int:
    if not isinstance(node, dict):
        return 0
    node_type = node.get("type")
    if node_type == "group":
        return sum(_count_conditions(child) for child in node.get("children") or [])
    if node_type in {"comparison", "function", "availability_check", "not"}:
        return 1
    return 0


def _validate_expression(node: Any, errors: List[ValidationIssue], path: str = "") -> None:
    if hasattr(node, "model_dump"):
        node = node.model_dump()
    if not isinstance(node, dict):
        return
    node_type = node.get("type")
    if node_type == "field":
        name = str(node.get("name") or "")
        if not is_known_field(name):
            errors.append(ValidationIssue(code="UNKNOWN_FIELD", message=f"Unknown field: {name}"))
        elif classify_field(name) == "UNSUPPORTED_DATA":
            errors.append(ValidationIssue(code="UNSUPPORTED_FIELD", message=f"Unsupported field: {name}"))
    elif node_type == "comparison":
        _validate_expression(node.get("left"), errors, path)
        _validate_expression(node.get("right"), errors, path)
    elif node_type == "group":
        for child in node.get("children") or []:
            _validate_expression(child, errors, path)
    elif node_type == "function":
        fn_name = str(node.get("name") or "").upper()
        fn_class = classify_function(fn_name)
        if fn_class not in {"SUPPORTED_RUNTIME", "SUPPORTED_PARSER_ONLY"}:
            code = "UNSUPPORTED_FUNCTION" if fn_class == "UNSUPPORTED_DATA" else "UNKNOWN_FUNCTION"
            errors.append(ValidationIssue(code=code, message=f"Unsupported function: {node.get('name')}"))
        for value in (node.get("arguments") or {}).values():
            _validate_expression(value, errors, path)
    elif node_type == "not":
        _validate_expression(node.get("child"), errors, path)


def validate_strategy_plan(
    plan: StrategyPlanAST,
    *,
    strategy_type: Optional[str] = None,
    form_symbol: Optional[str] = None,
    known_symbols: Optional[Set[str]] = None,
    holdings: Optional[Dict[str, int]] = None,
    holdings_checked: bool = False,
) -> ValidationResult:
    errors: List[ValidationIssue] = []
    warnings: List[ValidationIssue] = []
    suggestions: List[ValidationIssue] = []
    targets: List[TargetPreview] = []

    if strategy_type:
        side = (plan.side or "").upper()
        normalized_strategy = str(strategy_type or "").strip()
        if normalized_strategy == "Custom Query":
            pass
        elif side == "BUY" and strategy_type not in RULE_BASED_BUY_STRATEGIES:
            errors.append(ValidationIssue(code="SIDE_MISMATCH", message="BUY query cannot be used with a SELL strategy type."))
        elif side == "SELL" and strategy_type not in RULE_BASED_SELL_STRATEGIES:
            errors.append(ValidationIssue(code="SIDE_MISMATCH", message="SELL query cannot be used with a BUY strategy type."))

    if len(plan.rules) > MAX_RULE_BLOCKS:
        errors.append(ValidationIssue(code="TOO_MANY_RULES", message=f"Maximum {MAX_RULE_BLOCKS} rules allowed."))

    all_symbols = _collect_symbols(plan)
    if len(all_symbols) > MAX_SYMBOLS:
        errors.append(ValidationIssue(code="TOO_MANY_SYMBOLS", message=f"Maximum {MAX_SYMBOLS} symbols allowed."))

    if form_symbol and form_symbol.upper() not in all_symbols:
        warnings.append(
            ValidationIssue(
                code="FORM_SYMBOL_NOT_TARGETED",
                symbol=form_symbol.upper(),
                message=(
                    f"The currently selected symbol {form_symbol.upper()} is not included in this query. "
                    f"This query targets {', '.join(sorted(all_symbols)) or 'no symbols'} only."
                ),
            )
        )

    holdings = holdings or {}
    known_symbols = known_symbols or set()

    for rule in plan.rules:
        if not rule.symbols:
            errors.append(ValidationIssue(code="MISSING_STOCK_TARGET", message=f'Rule "{rule.name}" must target at least one symbol.'))
        if not rule.order or not rule.order.mode:
            errors.append(ValidationIssue(code="MISSING_ORDER_SIZE", message=f'Rule "{rule.name}" is missing order sizing.'))
        elif plan.side == "BUY" and is_holding_dependent_mode(rule.order.mode):
            errors.append(
                ValidationIssue(
                    code="INVALID_BUY_ORDER_SIZE",
                    message=(
                        f'Rule "{rule.name}" uses {rule.order.mode}, which applies to existing holdings '
                        "and is only valid for SELL strategies."
                    ),
                )
            )

        side = (plan.side or "BUY").lower()
        if rule.use_strategy:
            canonical = resolve_strategy_name(rule.use_strategy, side)
            if not is_delegatable_strategy(canonical, side):
                errors.append(
                    ValidationIssue(
                        code="UNKNOWN_STRATEGY",
                        message=f'Rule "{rule.name}" references unknown or non-delegatable strategy: {rule.use_strategy}',
                    )
                )
            else:
                for issue in validate_strategy_params(canonical, rule.strategy_params, side=side):
                    errors.append(
                        ValidationIssue(
                            code=issue.code,
                            message=issue.message,
                        )
                    )
                entry = get_catalog_entry(canonical, side)
                if entry and entry.requires_nepse_alpha:
                    warnings.append(
                        ValidationIssue(
                            code="STRATEGY_REQUIRES_NEPSE_ALPHA",
                            message=f'{entry.name} requires Nepse Alpha data for {", ".join(rule.symbols)}.',
                        )
                    )
                if entry and entry.requires_market_depth:
                    warnings.append(
                        ValidationIssue(
                            code="STRATEGY_REQUIRES_MARKET_DEPTH",
                            message=f'{entry.name} requires live market depth for {", ".join(rule.symbols)}.',
                        )
                    )
        elif not rule.when and not rule.eligibility and not rule.signal:
            errors.append(
                ValidationIssue(
                    code="MISSING_CONDITION",
                    message=f'Rule "{rule.name}" must include WHEN/ELIGIBILITY/SIGNAL or USE STRATEGY.',
                )
            )

        condition_count = _count_conditions(rule.when)
        if condition_count > MAX_CONDITIONS_PER_RULE:
            errors.append(ValidationIssue(code="TOO_MANY_CONDITIONS", message=f'Rule "{rule.name}" exceeds condition limit.'))
        if rule.when:
            _validate_expression(rule.when, errors)
            lint_rule_expression(rule.when, warnings, suggestions)
        for expr_name, expr in (
            ("eligibility", rule.eligibility),
            ("signal", rule.signal),
            ("require", rule.require),
        ):
            if expr:
                _validate_expression(expr, errors)
                lint_rule_expression(expr, warnings, suggestions)

        for symbol in rule.symbols:
            normalized = symbol.upper()
            if known_symbols and normalized not in known_symbols:
                errors.append(
                    ValidationIssue(
                        code="INVALID_SYMBOL",
                        symbol=normalized,
                        message=f"Symbol {normalized} does not exist in the allowed TMS symbol universe.",
                    )
                )
            preview = TargetPreview(symbol=normalized, rule_name=rule.name)
            if rule.use_strategy:
                entry = get_catalog_entry(rule.use_strategy, side)
                if entry:
                    preview.status = entry.name
            if plan.side == "SELL" and holdings_checked:
                held_qty = int(holdings.get(normalized, 0) or 0)
                if held_qty <= 0:
                    preview.eligible = False
                    preview.status = "SKIPPED_NOT_HELD"
                    entry = get_catalog_entry(rule.use_strategy, side) if rule.use_strategy else None
                    message = (
                        f"{normalized} is not in your DP holdings for this client. "
                        "Select the correct client, update holdings, or ask the user for sellable quantity before scheduling a SELL query."
                    )
                    if entry and entry.requires_holdings:
                        message = (
                            f"{normalized} is not in your DP holdings. "
                            f"{entry.name} requires a sellable holding before it can execute."
                        )
                    errors.append(
                        ValidationIssue(
                            code="SELL_SYMBOL_NOT_HELD",
                            symbol=normalized,
                            message=message,
                        )
                    )
                else:
                    preview.holding_qty = held_qty
                    if rule.order.mode == "quantity" and rule.order.value and rule.order.value > held_qty:
                        errors.append(
                            ValidationIssue(
                                code="SELL_QTY_EXCEEDS_HOLDING",
                                symbol=normalized,
                                message=(
                                    f"The query requests {int(rule.order.value)} {normalized} shares, "
                                    f"but only {held_qty} are currently sellable."
                                ),
                            )
                        )
            elif plan.side == "SELL" and holdings_checked is False:
                holding_qty = holdings.get(normalized)
                if holding_qty is not None and holding_qty > 0:
                    preview.holding_qty = holding_qty
            targets.append(preview)

    errors.extend(validate_reference_expressions(plan))

    result = ValidationResult(
        valid=not errors,
        errors=errors,
        warnings=warnings,
        suggestions=suggestions,
        compiled_plan=plan,
        targets=targets,
    )
    unsupported_issues = [
        issue for issue in errors if issue.code in {"UNKNOWN_FIELD", "UNSUPPORTED_FIELD", "UNSUPPORTED_FUNCTION"}
    ]
    if unsupported_issues:
        missing_items: List[str] = []
        suggested_keys: List[str] = []
        for issue in unsupported_issues:
            token = (
                issue.message.replace("Unknown field: ", "")
                .replace("Unsupported field: ", "")
                .replace("Unsupported function: ", "")
                .strip()
            )
            if token and token not in missing_items:
                missing_items.append(token)
            for key in suggest_fields_for_unknown(token):
                if key not in suggested_keys:
                    suggested_keys.append(key)
        result.status = "unsupported_data"
        result.message = "This query is not supported. The requested indicator is not available in the current data."
        result.missing_items = missing_items
        for key in suggested_keys:
            meta = get_field_metadata(key) or {}
            label = meta.get("label") or key
            result.suggestions.append(
                ValidationIssue(code="SUGGESTED_FIELD", message=label, symbol=key),
            )
    return result
