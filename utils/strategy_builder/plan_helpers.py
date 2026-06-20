from __future__ import annotations

from typing import Any, Dict, Optional


from utils.strategy_builder.constants import DEFAULT_RULE_ORDER_QUANTITY


def extract_planned_quantity_from_compiled_plan(
    compiled_plan: Dict[str, Any],
    symbol: Optional[str] = None,
) -> Optional[int]:
    """Return ORDER QUANTITY value from the first matching rule, if present."""
    rules = compiled_plan.get("rules") or []
    normalized_symbol = (symbol or "").strip().upper()
    for rule in rules:
        rule_symbols = [str(item).strip().upper() for item in (rule.get("symbols") or []) if str(item).strip()]
        if normalized_symbol and rule_symbols and normalized_symbol not in rule_symbols:
            continue
        order = rule.get("order") or {}
        mode = str(order.get("mode") or "").lower()
        value = order.get("value")
        if mode == "quantity":
            if value is not None and float(value) > 0:
                return int(float(value))
            return DEFAULT_RULE_ORDER_QUANTITY
    return None
