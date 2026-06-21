from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from lark import Lark, Transformer, v_args
from lark.exceptions import LarkError
from pydantic import ValidationError

from utils.strategy_builder.constants import (
    FORBIDDEN_SQL_KEYWORDS,
    DEFAULT_RULE_ORDER_QUANTITY,
    MAX_QUERY_LENGTH,
    STRATEGY_QUERY_VERSION,
)
from utils.strategy_builder.query_normalizer import (
    StrategyQueryNormalizationError,
    normalize_strategy_query_text,
)
from utils.strategy_builder.strategy_fields import resolve_field_name
from utils.strategies.strategy_query_catalog import normalize_query_param_name
from utils.strategy_builder.strategy_models import (
    ConfirmationConfig,
    ExecutionConfig,
    OrderSizing,
    PortfolioLimits,
    PositionProtectionConfig,
    PositionExitAction,
    RankConfig,
    RuleBlock,
    StrategyPlanAST,
)

GRAMMAR_PATH = Path(__file__).with_name("strategy_grammar.lark")


class StrategyQueryError(ValueError):
    pass


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    text = re.sub(r"--[^\n]*", " ", text)
    return text


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1]
    return value


def _check_forbidden_keywords(text: str) -> None:
    stripped = re.sub(r'"[^"]*"', ' ', text)
    upper = stripped.upper()
    for keyword in FORBIDDEN_SQL_KEYWORDS:
        if re.search(rf"\b{keyword}\b", upper):
            raise StrategyQueryError(f"Forbidden keyword: {keyword}")


def _merge_execution_config(base: ExecutionConfig, patch: ExecutionConfig) -> ExecutionConfig:
    data = base.model_dump()
    for key, value in patch.model_dump(exclude_defaults=True).items():
        if value is not None:
            data[key] = value
    return ExecutionConfig(**data)


@v_args(inline=True)
class StrategyTransformer(Transformer):
    def NUMBER(self, token):
        raw = str(token)
        return float(raw) if "." in raw else int(raw)

    def STRING(self, token):
        return _unquote(str(token))

    def SIDE_KW(self, token):
        return str(token)

    def true_lit(self):
        return {"type": "literal", "value": True}

    def false_lit(self):
        return {"type": "literal", "value": False}

    def identifier(self, token):
        name = resolve_field_name(str(token)) or str(token)
        return {"type": "field", "name": name}

    def number(self, value):
        return {"type": "literal", "value": value}

    def string(self, value):
        return {"type": "literal", "value": value}

    def string_list(self, *values):
        return [str(v) for v in values]

    def value_list(self, *values):
        return list(values)

    def arith_expr(self, left, *rest):
        if not rest:
            return left
        result = left
        for idx in range(0, len(rest), 2):
            op = str(rest[idx])
            right = rest[idx + 1]
            result = {"type": "arithmetic", "operator": op, "left": result, "right": right}
        return result

    def term(self, left, *rest):
        if not rest:
            return left
        result = left
        for idx in range(0, len(rest), 2):
            op = str(rest[idx])
            right = rest[idx + 1]
            result = {"type": "arithmetic", "operator": op, "left": result, "right": right}
        return result

    def factor(self, value):
        return value

    def not_expr(self, *args):
        if len(args) == 1:
            return args[0]
        return {"type": "not", "child": args[1]}

    def and_expr(self, *args):
        if len(args) == 1:
            return args[0]
        return {"type": "group", "logic": "AND", "children": list(args)}

    def or_expr(self, *args):
        if len(args) == 1:
            return args[0]
        return {"type": "group", "logic": "OR", "children": list(args)}

    def comparison(self, left, op, right):
        return {"type": "comparison", "left": left, "operator": _normalize_operator(str(op)), "right": right}

    def between_expr(self, left, low, high):
        return {
            "type": "group",
            "logic": "AND",
            "children": [
                {"type": "comparison", "left": left, "operator": "gte", "right": low},
                {"type": "comparison", "left": left, "operator": "lte", "right": high},
            ],
        }

    def not_between_expr(self, left, low, high):
        return {
            "type": "group",
            "logic": "OR",
            "children": [
                {"type": "comparison", "left": left, "operator": "lt", "right": low},
                {"type": "comparison", "left": left, "operator": "gt", "right": high},
            ],
        }

    def in_expr(self, left, values):
        return {"type": "comparison", "left": left, "operator": "in", "right": {"type": "list", "values": values}}

    def not_in_expr(self, left, values):
        return {"type": "comparison", "left": left, "operator": "not_in", "right": {"type": "list", "values": values}}

    def contains_expr(self, left, right):
        return {"type": "comparison", "left": left, "operator": "contains", "right": right}

    def not_contains_expr(self, left, right):
        return {"type": "comparison", "left": left, "operator": "not_contains", "right": right}

    def is_available(self, left):
        return self._availability_check(left, "is_available")

    def is_not_available(self, left):
        return self._availability_check(left, "is_not_available")

    def is_null(self, left):
        return self._availability_check(left, "is_null")

    def is_not_null(self, left):
        return self._availability_check(left, "is_not_null")

    def _availability_check(self, left, check: str):
        if isinstance(left, dict) and left.get("type") == "function" and str(left.get("name") or "").upper() == "REFERENCE":
            return {"type": "availability_check", "expression": left, "check": check}
        return {"type": "availability_check", "field": _field_name(left), "check": check}

    def changed_to(self, left, right):
        return {
            "type": "function",
            "name": "CHANGED_TO",
            "arguments": {"field": _field_name(left), "value": _literal_value(right)},
        }

    def changed_from_to(self, left, from_value, to_value):
        return {
            "type": "function",
            "name": "CHANGED_FROM_TO",
            "arguments": {
                "field": _field_name(left),
                "from_value": _literal_value(from_value),
                "to_value": _literal_value(to_value),
            },
        }

    def function_call(self, name, args=None):
        arguments: Dict[str, Any] = {}
        positional: List[Any] = []
        if args:
            for item in args:
                if isinstance(item, tuple) and len(item) == 2:
                    key, value = item
                    arguments[str(key)] = value
                else:
                    positional.append(item)
        if positional and "field" not in arguments:
            first = positional[0]
            if isinstance(first, dict) and first.get("type") == "field":
                arguments["field"] = first.get("name")
            elif isinstance(first, dict):
                arguments["field"] = first
            else:
                arguments["field"] = str(first)
            for idx, value in enumerate(positional[1:], start=1):
                if isinstance(value, dict) and value.get("type") == "literal":
                    arguments.setdefault("args", []).append(value.get("value"))
        return {"type": "function", "name": str(name), "arguments": arguments}

    def arg(self, *values):
        if len(values) == 2:
            return str(values[0]), values[1]
        return values[0]

    def arg_list(self, *args):
        return list(args)

    def strategy_version(self, version):
        return int(version)

    def side(self, side_kw):
        return str(side_kw)

    def single_symbol(self, value):
        raw = str(value)
        if raw != raw.upper():
            raise StrategyQueryError(
                f'Symbol "{raw}" must be an exact uppercase NEPSE code in double quotes.'
            )
        return [raw.upper()], "single"

    def multi_symbol(self, values):
        normalized: List[str] = []
        for value in values:
            raw = str(value)
            if raw != raw.upper():
                raise StrategyQueryError(
                    f'Symbol "{raw}" must be an exact uppercase NEPSE code in double quotes.'
                )
            normalized.append(raw.upper())
        return normalized, "symbol_list"

    def block_stmt(self, stmt):
        return stmt

    def block_body(self, *stmts):
        body: Dict[str, Any] = {}
        execution = ExecutionConfig()
        flattened: List[Any] = []
        for stmt in stmts:
            if isinstance(stmt, list):
                flattened.extend(stmt)
            else:
                flattened.append(stmt)
        for raw in flattened:
            stmt = raw.children[0] if hasattr(raw, "children") and raw.children else raw
            if not isinstance(stmt, dict):
                continue
            if "execution" in stmt and isinstance(stmt["execution"], ExecutionConfig):
                execution = _merge_execution_config(execution, stmt["execution"])
                stmt = {key: value for key, value in stmt.items() if key != "execution"}
            if "strategy_params" in stmt:
                params = body.setdefault("strategy_params", {})
                params.update(stmt["strategy_params"])
                stmt = {key: value for key, value in stmt.items() if key != "strategy_params"}
            body.update(stmt)
        body["execution"] = execution
        return body

    def when_clause(self, expr):
        return {"when": expr, "signal": expr}

    def eligibility_clause(self, expr):
        return {"eligibility": expr}

    def signal_clause(self, expr):
        return {"signal": expr}

    def require_clause(self, expr):
        return {"require": expr}

    def use_strategy_clause(self, name):
        cleaned = str(name).strip().strip('"')
        return {"use_strategy": cleaned}

    def strategy_param_name(self, token):
        return str(token)

    def strategy_param_number(self, name, value):
        return {"strategy_params": {normalize_query_param_name(str(name)): float(value)}}

    def strategy_param_string(self, name, value):
        cleaned = str(value).strip().strip('"')
        return {"strategy_params": {normalize_query_param_name(str(name)): cleaned}}

    def strategy_param_true(self, name):
        return {"strategy_params": {normalize_query_param_name(str(name)): True}}

    def strategy_param_false(self, name):
        return {"strategy_params": {normalize_query_param_name(str(name)): False}}

    def COMP_OP(self, token):
        return _normalize_operator(str(token))

    def ORDER_MODE(self, token):
        return str(token).lower()

    def order_value(self, *values):
        if not values:
            return None
        if len(values) == 1 and str(values[0]).upper() == "FROM_FORM":
            return "from_form"
        if len(values) == 2 and str(values[0]).upper() == "PER":
            return "per_symbol"
        return values[0]

    def order_clause(self, mode, parts):
        order = parts if isinstance(parts, OrderSizing) else OrderSizing(mode="quantity", value=DEFAULT_RULE_ORDER_QUANTITY)
        order.mode = str(mode).lower()
        order.explicit = True
        return {"order": order}

    def order_parts_value_price(self, value, price):
        return self._build_order_sizing(value, price)

    def order_parts_value(self, value):
        return self._build_order_sizing(value, None)

    def order_parts_price(self, price):
        return self._build_order_sizing(None, price)

    def order_parts_empty(self):
        return OrderSizing(mode="quantity", value=DEFAULT_RULE_ORDER_QUANTITY)

    def _build_order_sizing(self, value, price):
        price_source = _normalize_price_source(price)
        if value == "per_symbol":
            return OrderSizing(mode="quantity", price_source=price_source, explicit=True)
        if value == "from_form":
            return OrderSizing(mode="quantity", value=-1, price_source=price_source, explicit=True)
        if isinstance(value, (int, float)):
            return OrderSizing(mode="quantity", value=float(value), price_source=price_source, explicit=True)
        return OrderSizing(
            mode="quantity",
            value=DEFAULT_RULE_ORDER_QUANTITY,
            price_source=price_source,
            explicit=True,
        )

    def price_clause(self, source):
        return str(source)

    def confirm_clause(self, body):
        if isinstance(body, ConfirmationConfig):
            return {"confirmation": body}
        return {"confirmation": ConfirmationConfig()}

    def confirm_body(self, *args):
        if len(args) == 1 and isinstance(args[0], int):
            return ConfirmationConfig(mode="true_for_scans", scans=int(args[0]))
        if len(args) == 2:
            return ConfirmationConfig(mode="matches_in_last", required=int(args[0]), window=int(args[1]))
        return ConfirmationConfig(mode="immediate")

    def exec_once(self):
        return ExecutionConfig(frequency="once")

    def exec_once_per_symbol(self):
        return ExecutionConfig(frequency="once_per_symbol")

    def exec_once_per_market_day(self):
        return ExecutionConfig(frequency="once_per_market_day")

    def exec_max_times(self, count, per_symbol=None):
        frequency = "max_times_per_symbol" if per_symbol is not None else "max_times"
        return ExecutionConfig(frequency=frequency, max_times=int(count))

    def exec_clause(self, body):
        return {"execution": body}

    def trigger_on_cross(self):
        return {"execution": ExecutionConfig(trigger="on_cross")}

    def trigger_level(self):
        return {"execution": ExecutionConfig(trigger="level")}

    def slippage_clause(self, value):
        return {"execution": ExecutionConfig(max_slippage_pct=float(value))}

    def data_age_clause(self, value):
        return {"execution": ExecutionConfig(max_data_age_seconds=int(value))}

    def missing_depth_clause(self, value):
        return {"execution": ExecutionConfig(missing_market_depth=str(value).lower())}

    def missing_holding_clause(self, value):
        return {"execution": ExecutionConfig(missing_holding=str(value).lower())}

    def cooldown_clause(self, value):
        return {"execution": ExecutionConfig(cooldown_minutes=int(value))}

    def symbol_target(self, *values):
        if len(values) == 1:
            return values[0]
        return values[0], values[1]

    def defaults_block(self, body):
        return _parse_execution_block(body)

    def portfolio_limits_block(self, body):
        limits: Dict[str, Any] = {}
        for key, value in body.items():
            limits[key.lower()] = value
        return PortfolioLimits(
            max_matching_stocks=limits.get("max_matching_stocks"),
            max_total_buy_amount=limits.get("max_total_buy_amount"),
            max_amount_per_stock=limits.get("max_amount_per_stock"),
            max_position_pct=limits.get("max_position_pct"),
            max_open_orders=limits.get("max_open_orders"),
        )

    def fixed_stop_clause(self, value):
        return {"fixed_stop_loss_price": float(value)}

    def trailing_stop_clause(self, value):
        return {"trailing_stop_pct": float(value)}

    def position_protection_stmt(self, stmt):
        return stmt

    def position_protection_block(self, *stmts):
        payload: Dict[str, Any] = {}
        for stmt in stmts:
            if isinstance(stmt, dict):
                payload.update(stmt)
        return PositionProtectionConfig(
            fixed_stop_loss_price=payload.get("fixed_stop_loss_price"),
            trailing_stop_pct=payload.get("trailing_stop_pct"),
        )

    def sell_exit_stmt(self, *args):
        if len(args) == 3:
            mode, value, expr = args
            numeric = -1 if value == "from_form" else (float(value) if isinstance(value, (int, float)) else None)
            return PositionExitAction(action="sell", order_mode=str(mode).lower(), order_value=numeric, when=expr)
        mode, expr = args
        return PositionExitAction(action="sell", order_mode=str(mode).lower(), when=expr)

    def sell_exit_with_value(self, mode, value, expr):
        return self.sell_exit_stmt(mode, value, expr)

    def sell_exit_no_value(self, mode, expr):
        return self.sell_exit_stmt(mode, expr)

    def move_stop_stmt(self, expr):
        return PositionExitAction(action="move_stop_to_entry", when=expr)

    def lock_profit_stmt(self, pct, expr):
        return PositionExitAction(action="lock_profit_pct", lock_profit_pct=float(pct), when=expr)

    def trail_remaining_stmt(self, expr):
        return PositionExitAction(action="trail_remaining", when=expr)

    def position_exit_stmt(self, stmt):
        return stmt

    def position_exit_block(self, *stmts):
        return [stmt for stmt in stmts if isinstance(stmt, PositionExitAction)]

    def rank_field(self, field, direction=None):
        return {"field": resolve_field_name(str(field)) or str(field), "direction": str(direction or "DESC").lower()}

    def rank_limit(self, count):
        return int(count)

    def rank_block(self, *fields_and_limit):
        fields: List[Dict[str, str]] = []
        limit = None
        for item in fields_and_limit:
            if isinstance(item, dict):
                fields.append(item)
            else:
                limit = int(item)
        return RankConfig(fields=fields, limit=limit)

    def rule(self, name, symbols_info, body):
        symbols, target_type = symbols_info
        rule_id = str(uuid.uuid4())
        when = body.get("when")
        order = body.get("order") or OrderSizing(
            mode="quantity",
            value=DEFAULT_RULE_ORDER_QUANTITY,
            explicit=False,
        )
        return RuleBlock(
            rule_id=rule_id,
            name=str(name),
            symbols=symbols,
            target_type=target_type,
            when=when,
            eligibility=body.get("eligibility"),
            signal=body.get("signal") or when,
            require=body.get("require"),
            order=order,
            confirmation=body.get("confirmation") or ConfirmationConfig(),
            execution=body.get("execution") or ExecutionConfig(),
            use_strategy=body.get("use_strategy"),
            strategy_params=body.get("strategy_params") or {},
        )

    def document(self, version, side, *rest):
        defaults = ExecutionConfig()
        portfolio_limits = None
        position_protection = None
        position_exit: List[PositionExitAction] = []
        rank = None
        rules: List[RuleBlock] = []
        for item in rest:
            if item is None:
                continue
            if isinstance(item, ExecutionConfig):
                defaults = item
            elif isinstance(item, PortfolioLimits):
                portfolio_limits = item
            elif isinstance(item, PositionProtectionConfig):
                position_protection = item
            elif isinstance(item, list) and item and isinstance(item[0], PositionExitAction):
                position_exit = item
            elif isinstance(item, RankConfig):
                rank = item
            elif isinstance(item, RuleBlock):
                rules.append(item)
        return StrategyPlanAST(
            version=int(version),
            side=str(side),
            defaults=defaults,
            portfolio_limits=portfolio_limits,
            position_protection=position_protection,
            position_exit=position_exit,
            rank=rank,
            rules=rules,
        )


def _field_name(node: Any) -> str:
    if isinstance(node, dict) and node.get("type") == "field":
        return str(node.get("name"))
    if isinstance(node, dict) and node.get("type") == "literal":
        return str(node.get("value"))
    return str(node)


def _literal_value(node: Any) -> Any:
    if isinstance(node, dict) and node.get("type") == "literal":
        return node.get("value")
    return node


def _normalize_price_source(raw: Optional[str]) -> str:
    if not raw:
        return "ltp"
    cleaned = str(raw).strip().lower().replace(" ", "_")
    mapping = {
        "top_buy": "top_buy",
        "top_sell": "top_sell",
        "best_bid": "best_bid",
        "best_ask": "best_ask",
        "ltp": "ltp",
    }
    return mapping.get(cleaned, cleaned)


def _normalize_operator(op: str) -> str:
    mapping = {
        "=": "eq",
        "!=": "neq",
        ">": "gt",
        ">=": "gte",
        "<": "lt",
        "<=": "lte",
    }
    return mapping.get(op, op)


def _parse_execution_block(body: Dict[str, Any]) -> ExecutionConfig:
    config = ExecutionConfig()
    for key, value in body.items():
        if key == "trigger":
            config.trigger = value
        elif key == "frequency":
            config.frequency = value
        elif key == "max_slippage_pct":
            config.max_slippage_pct = float(value)
        elif key == "max_data_age_seconds":
            config.max_data_age_seconds = int(value)
        elif key == "missing_market_depth":
            config.missing_market_depth = value
        elif key == "missing_holding":
            config.missing_holding = value
        elif key == "cooldown_minutes":
            config.cooldown_minutes = int(value)
        elif key == "max_times":
            config.max_times = int(value)
    return config


_parser: Optional[Lark] = None


def _get_parser() -> Lark:
    global _parser
    if _parser is None:
        grammar = GRAMMAR_PATH.read_text(encoding="utf-8")
        _parser = Lark(grammar, start="document", parser="lalr", transformer=StrategyTransformer())
    return _parser


def extract_symbols_from_query(query_text: str) -> List[str]:
    plan = parse_strategy_query(query_text)
    symbols: List[str] = []
    seen: set[str] = set()
    for rule in plan.rules:
        for symbol in rule.symbols:
            normalized = symbol.upper()
            if normalized not in seen:
                seen.add(normalized)
                symbols.append(normalized)
    return symbols


def _format_parse_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(part) for part in first.get("loc", ()) if part != "__root__")
        msg = first.get("msg") or str(exc)
        return f"Invalid query structure{f' at {loc}' if loc else ''}: {msg}"
    return str(exc)


def parse_strategy_query(query_text: str) -> StrategyPlanAST:
    try:
        normalized = normalize_strategy_query_text(query_text)
    except StrategyQueryNormalizationError as exc:
        raise StrategyQueryError(str(exc)) from exc
    if not normalized:
        raise StrategyQueryError("Query text is required")
    if len(normalized) > MAX_QUERY_LENGTH:
        raise StrategyQueryError("Query exceeds maximum length")
    cleaned = _strip_comments(normalized)
    _check_forbidden_keywords(cleaned)
    try:
        parser = _get_parser()
        result = parser.parse(cleaned)
    except LarkError as exc:
        raise StrategyQueryError(str(exc)) from exc
    except (ValidationError, IndexError, TypeError, ValueError) as exc:
        raise StrategyQueryError(_format_parse_error(exc)) from exc
    if not isinstance(result, StrategyPlanAST):
        raise StrategyQueryError("Failed to compile strategy query")
    if result.version != STRATEGY_QUERY_VERSION:
        raise StrategyQueryError(f"Unsupported strategy version: {result.version}")
    return result


def _node_as_dict(node: Any) -> Any:
    if hasattr(node, "model_dump"):
        return node.model_dump(mode="python")
    return node


def _display_operator(op: str) -> str:
    mapping = {
        "eq": "=",
        "neq": "!=",
        "gt": ">",
        "gte": ">=",
        "lt": "<",
        "lte": "<=",
    }
    return mapping.get(op, op)


def _format_strategy_param_line(name: str, value: Any) -> str:
    if isinstance(value, bool):
        return f"    {name} {'TRUE' if value else 'FALSE'}"
    if isinstance(value, str):
        if any(ch in value for ch in (' ', ':', '-')):
            return f'    {name} "{value}"'
        return f"    {name} {value}"
    if isinstance(value, int) and not isinstance(value, bool):
        return f"    {name} {value}"
    if isinstance(value, float):
        if value.is_integer():
            return f"    {name} {int(value)}"
        return f"    {name} {value}"
    return f"    {name} {value}"


def format_strategy_query(plan: StrategyPlanAST) -> str:
    lines = [f"STRATEGY_VERSION {plan.version}", f"SIDE {plan.side}", ""]
    if plan.rank and plan.rank.fields:
        rank_parts = []
        for item in plan.rank.fields:
            field = item.get("field")
            if not field:
                continue
            direction = str(item.get("direction") or "desc").upper()
            rank_parts.append(f"{field} {direction}")
        if rank_parts:
            suffix = f" LIMIT {int(plan.rank.limit)} ORDERS" if plan.rank.limit is not None else ""
            lines.append(f"RANK MATCHES BY {', '.join(rank_parts)}{suffix}")
            lines.append("")
    if plan.position_protection:
        lines.append("POSITION_PROTECTION {")
        if plan.position_protection.fixed_stop_loss_price is not None:
            lines.append(f"    FIXED_STOP_LOSS_PRICE {plan.position_protection.fixed_stop_loss_price}")
        if plan.position_protection.trailing_stop_pct is not None:
            lines.append(f"    TRAILING_STOP_PCT {plan.position_protection.trailing_stop_pct}")
        lines.append("}")
        lines.append("")
    for rule in plan.rules:
        if len(rule.symbols) == 1:
            target = f'FOR SYMBOL "{rule.symbols[0]}"'
        else:
            joined = ", ".join(f'"{symbol}"' for symbol in rule.symbols)
            target = f"FOR SYMBOL IN ({joined})"
        lines.append(f'RULE "{rule.name}" {target} {{')
        if rule.use_strategy:
            lines.append(f'    USE STRATEGY "{rule.use_strategy}"')
            for param_name in sorted(rule.strategy_params.keys()):
                lines.append(_format_strategy_param_line(param_name, rule.strategy_params[param_name]))
        if rule.eligibility:
            lines.append(f"    ELIGIBILITY {_expr_to_text(rule.eligibility)}")
        elif rule.when and not rule.use_strategy:
            lines.append(f"    WHEN {_expr_to_text(rule.when)}")
        elif rule.when and rule.use_strategy and rule.when != rule.signal:
            lines.append(f"    WHEN {_expr_to_text(rule.when)}")
        if rule.signal and rule.use_strategy and rule.signal != rule.when:
            lines.append(f"    SIGNAL {_expr_to_text(rule.signal)}")
        if rule.require:
            lines.append(f"    REQUIRE {_expr_to_text(rule.require)}")
        lines.append(f"    ORDER {_order_to_text(rule.order)}")
        if rule.confirmation.mode == "true_for_scans" and rule.confirmation.scans:
            lines.append(f"    CONFIRM TRUE_FOR {int(rule.confirmation.scans)} SCANS")
        elif rule.confirmation.mode == "matches_in_last" and rule.confirmation.required and rule.confirmation.window:
            lines.append(
                f"    CONFIRM MATCHES {int(rule.confirmation.required)} OF LAST {int(rule.confirmation.window)} SCANS"
            )
        if rule.execution.max_slippage_pct is not None:
            lines.append(f"    MAX_SLIPPAGE_PCT {rule.execution.max_slippage_pct}")
        lines.append(f"    TRIGGER {rule.execution.trigger.upper()}")
        lines.append(f"    EXECUTE {rule.execution.frequency.upper().replace('_', ' ')}")
        lines.append("}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def format_expression(node: Any) -> str:
    """Render an AST node as human-readable strategy text."""
    return _expr_to_text(node)


def _expr_to_text(node: Any) -> str:
    node = _node_as_dict(node)
    if not isinstance(node, dict):
        return str(node)
    node_type = node.get("type")
    if node_type == "field":
        return str(node["name"])
    if node_type == "literal":
        value = node["value"]
        if isinstance(value, str):
            return f'"{value}"'
        return str(value)
    if node_type == "arithmetic":
        op = str(node.get("operator") or "")
        return f"{_expr_to_text(node.get('left'))} {op} {_expr_to_text(node.get('right'))}"
    if node_type == "comparison":
        op = _display_operator(str(node.get("operator") or ""))
        return f"{_expr_to_text(node.get('left'))} {op} {_expr_to_text(node.get('right'))}"
    if node_type == "group":
        joiner = f" {node['logic']} "
        return joiner.join(_expr_to_text(child) for child in node.get("children") or [])
    if node_type == "availability_check":
        target = node.get("expression") or node.get("field")
        label = _expr_to_text(target) if isinstance(target, dict) else str(target or "")
        check = str(node.get("check") or "is_available").replace("_", " ")
        return f"{label} {check}"
    if node_type == "function":
        name = str(node.get("name") or "")
        args = node.get("arguments") or {}
        rendered = ", ".join(f"{key}={_render_arg(value)}" for key, value in args.items())
        return f"{name}({rendered})"
    return str(node_type or "expression")


def _render_arg(value: Any) -> str:
    value = _node_as_dict(value)
    if isinstance(value, dict):
        return _expr_to_text(value)
    if isinstance(value, str):
        return f'"{value}"'
    return str(value)


def _order_to_text(order: OrderSizing) -> str:
    order_data = _node_as_dict(order)
    mode = str(order_data.get("mode") or order.mode).upper().replace("_", " ")
    value = order_data.get("value", order.value)
    price_source = str(order_data.get("price_source") or order.price_source or "ltp").upper()
    price_suffix = f" PRICE {price_source}" if price_source and price_source != "LTP" else ""
    if value == -1:
        return f"{mode} FROM_FORM{price_suffix}"
    if value is None:
        return f"{mode}{price_suffix}"
    if str(order_data.get("mode") or order.mode).lower() == "quantity":
        return f"QUANTITY {int(value)}{price_suffix}"
    return f"{mode} {value}{price_suffix}"
