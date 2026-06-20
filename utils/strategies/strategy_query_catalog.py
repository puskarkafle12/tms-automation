from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Set

from utils.strategy_builder.constants import RULE_BASED_BUY_STRATEGIES, RULE_BASED_SELL_STRATEGIES
from utils.strategies.aliases import BUY_STRATEGIES, SELL_STRATEGIES, canonical_strategy_name
from utils.strategies.handlers import HANDLERS
from utils.strategies.types import OrderContext, StrategyConfig

ParamType = Literal["number", "string", "boolean", "datetime"]

RULE_BASED_STRATEGIES = RULE_BASED_BUY_STRATEGIES | RULE_BASED_SELL_STRATEGIES

DELEGATABLE_BUY_STRATEGIES: Set[str] = BUY_STRATEGIES - RULE_BASED_BUY_STRATEGIES
DELEGATABLE_SELL_STRATEGIES: Set[str] = SELL_STRATEGIES - RULE_BASED_SELL_STRATEGIES
DELEGATABLE_STRATEGIES: Set[str] = DELEGATABLE_BUY_STRATEGIES | DELEGATABLE_SELL_STRATEGIES


@dataclass(frozen=True)
class StrategyParamSpec:
    query_name: str
    field_path: str
    param_type: ParamType
    label: str
    required: bool = False
    default: Any = None


@dataclass(frozen=True)
class StrategyCatalogEntry:
    name: str
    side: Literal["buy", "sell"]
    purpose: str
    params: tuple[StrategyParamSpec, ...] = ()
    aliases: tuple[str, ...] = ()
    requires_nepse_alpha: bool = False
    requires_market_depth: bool = False
    requires_holdings: bool = False
    handler_name: Optional[str] = None

    @property
    def required_params(self) -> tuple[StrategyParamSpec, ...]:
        return tuple(item for item in self.params if item.required)

    @property
    def optional_params(self) -> tuple[StrategyParamSpec, ...]:
        return tuple(item for item in self.params if not item.required)


@dataclass
class StrategyParamValidationIssue:
    code: str
    message: str
    param: Optional[str] = None


def _params(*items: StrategyParamSpec) -> tuple[StrategyParamSpec, ...]:
    return items


_COMMON_BUY_SCORE_PARAMS = _params(
    StrategyParamSpec("MIN_BUY_SCORE", "config.min_buy_score", "number", "Minimum buy score", default=65),
    StrategyParamSpec("REQUIRE_VOLUME_INCREASE", "config.require_volume_increase", "boolean", "Require volume increase"),
    StrategyParamSpec("REQUIRE_FRESH_TRADE", "config.require_fresh_trade", "boolean", "Require fresh trade"),
)

STRATEGY_CATALOG: Dict[str, StrategyCatalogEntry] = {
    "Fixed Price Buy": StrategyCatalogEntry(
        name="Fixed Price Buy",
        side="buy",
        purpose="Limit buy when LTP is at or below target price.",
        params=_params(
            StrategyParamSpec("TARGET_PRICE", "target_price", "number", "Target buy price", required=True),
        ),
        handler_name="Fixed Price Buy",
    ),
    "Quality Pullback Recovery Buy": StrategyCatalogEntry(
        name="Quality Pullback Recovery Buy",
        side="buy",
        purpose="Buy quality names after pullback recovery with score threshold.",
        params=_COMMON_BUY_SCORE_PARAMS,
        requires_nepse_alpha=True,
        handler_name="Quality Pullback Recovery Buy",
    ),
    "Confirmed Breakout Buy": StrategyCatalogEntry(
        name="Confirmed Breakout Buy",
        side="buy",
        purpose="Buy confirmed breakout above day high with rising scans.",
        params=_params(
            StrategyParamSpec("TARGET_PRICE", "target_price", "number", "Breakout trigger price", required=True),
        ),
        handler_name="Confirmed Breakout Buy",
    ),
    "Smart Pullback Buy": StrategyCatalogEntry(
        name="Smart Pullback Buy",
        side="buy",
        purpose="Buy after controlled pullback from day high recovers.",
        params=_params(
            StrategyParamSpec("TARGET_PRICE", "target_price", "number", "Optional trigger price"),
        ),
        aliases=("Dip Buy", "Buy Below Price"),
        handler_name="Smart Pullback Buy",
    ),
    "Mean Reversion Bounce Buy": StrategyCatalogEntry(
        name="Mean Reversion Bounce Buy",
        side="buy",
        purpose="Buy mean-reverting oversold bounce setups.",
        params=_COMMON_BUY_SCORE_PARAMS,
        requires_nepse_alpha=True,
        handler_name="Mean Reversion Bounce Buy",
    ),
    "Order Book Strength Buy": StrategyCatalogEntry(
        name="Order Book Strength Buy",
        side="buy",
        purpose="Buy when order book buy pressure is strong.",
        params=_COMMON_BUY_SCORE_PARAMS,
        requires_market_depth=True,
        handler_name="Order Book Strength Buy",
    ),
    "Time-Based Buy": StrategyCatalogEntry(
        name="Time-Based Buy",
        side="buy",
        purpose="Run a wrapped buy strategy until expiry, then cancel.",
        params=_params(
            StrategyParamSpec("EXPIRY_TIME", "expiry_time", "datetime", "Expiry date/time (Nepal local)", required=True),
            StrategyParamSpec(
                "WRAPPED_STRATEGY",
                "config.wrapped_strategy_type",
                "string",
                "Wrapped buy strategy",
                default="Quality Pullback Recovery Buy",
            ),
        ),
        handler_name=None,
    ),
    "Fixed Price Sell": StrategyCatalogEntry(
        name="Fixed Price Sell",
        side="sell",
        purpose="Limit sell when LTP is at or above target price.",
        params=_params(
            StrategyParamSpec("TARGET_PRICE", "target_price", "number", "Target sell price", required=True),
        ),
        requires_holdings=True,
        handler_name="Fixed Price Sell",
    ),
    "Capital Protection Sell": StrategyCatalogEntry(
        name="Capital Protection Sell",
        side="sell",
        purpose="Trailing stop / break-even protection sell.",
        params=_params(
            StrategyParamSpec("STOP_LOSS_PRICE", "stop_loss_price", "number", "Stop-loss trigger price"),
            StrategyParamSpec("AVERAGE_BUY_PRICE", "average_buy_price", "number", "Average buy price"),
            StrategyParamSpec("TRAILING_DROP_PCT", "trailing_drop_percent", "number", "Trailing drop percent", default=3),
            StrategyParamSpec("MAX_SLIPPAGE_PCT", "max_allowed_slippage_percent", "number", "Max slippage percent", default=1),
            StrategyParamSpec("BREAK_EVEN_TRIGGER_PCT", "config.break_even_trigger_pct", "number", "Break-even trigger percent"),
        ),
        aliases=("Fast Stop Loss", "Stop Limit Sell", "Break-Even Protection"),
        requires_holdings=True,
        handler_name="Capital Protection Sell",
    ),
    "Profit Ladder Sell": StrategyCatalogEntry(
        name="Profit Ladder Sell",
        side="sell",
        purpose="Partial profit booking at configured targets.",
        params=_params(
            StrategyParamSpec("FIRST_TARGET", "partial_legs.0.targetPrice", "number", "First target price", required=True),
            StrategyParamSpec("FIRST_PERCENT", "partial_legs.0.sellPercent", "number", "First sell percent", required=True),
            StrategyParamSpec("SECOND_TARGET", "partial_legs.1.targetPrice", "number", "Second target price", required=True),
            StrategyParamSpec("SECOND_PERCENT", "partial_legs.1.sellPercent", "number", "Second sell percent", required=True),
        ),
        aliases=("Smart Profit Booking", "Book Profit + Stop Loss", "Partial Profit Booking"),
        requires_holdings=True,
        handler_name="Profit Ladder Sell",
    ),
    "Trailing Runner Sell": StrategyCatalogEntry(
        name="Trailing Runner Sell",
        side="sell",
        purpose="Trail from highest price and sell on drop.",
        params=_params(
            StrategyParamSpec("TRAILING_DROP_PCT", "trailing_drop_percent", "number", "Trailing drop percent", required=True),
            StrategyParamSpec("ACTIVATION_PRICE", "activation_price", "number", "Activation price"),
        ),
        aliases=("Trailing Stop Loss",),
        requires_holdings=True,
        handler_name="Trailing Runner Sell",
    ),
    "Technical Weakness Sell": StrategyCatalogEntry(
        name="Technical Weakness Sell",
        side="sell",
        purpose="Sell on combined technical and price weakness.",
        params=(),
        requires_nepse_alpha=True,
        requires_holdings=True,
        handler_name="Technical Weakness Sell",
    ),
    "Emergency Exit by Top Buyer": StrategyCatalogEntry(
        name="Emergency Exit by Top Buyer",
        side="sell",
        purpose="Emergency sell to top buy price.",
        params=_params(
            StrategyParamSpec("EMERGENCY_CONFIRMED", "emergency_execution", "boolean", "Confirm emergency exit", required=True),
            StrategyParamSpec("ALLOW_SPLIT_EMERGENCY_EXIT", "config.allow_split_emergency_exit", "boolean", "Split across depth levels"),
        ),
        aliases=("Emergency Exit",),
        requires_holdings=True,
        handler_name="Emergency Exit by Top Buyer",
    ),
    "Time-Based Exit": StrategyCatalogEntry(
        name="Time-Based Exit",
        side="sell",
        purpose="Monitor until expiry, then cancel or emergency sell.",
        params=_params(
            StrategyParamSpec("EXPIRY_TIME", "expiry_time", "datetime", "Expiry date/time (Nepal local)", required=True),
            StrategyParamSpec(
                "EXPIRY_ACTION",
                "expiry_action",
                "string",
                "Expiry action",
                default="Cancel strategy",
            ),
        ),
        requires_holdings=True,
        handler_name=None,
    ),
}

QUERY_PARAM_ALIASES: Dict[str, str] = {
    "PRICE": "TARGET_PRICE",
    "TARGET": "TARGET_PRICE",
    "STOP_LOSS": "STOP_LOSS_PRICE",
    "AVERAGE_PRICE": "AVERAGE_BUY_PRICE",
    "TRAILING_DROP": "TRAILING_DROP_PCT",
    "MAX_SLIPPAGE": "MAX_SLIPPAGE_PCT",
    "WRAPPED_STRATEGY_TYPE": "WRAPPED_STRATEGY",
}


def normalize_query_param_name(name: str) -> str:
    upper = str(name or "").strip().upper().replace("-", "_")
    return QUERY_PARAM_ALIASES.get(upper, upper)


def resolve_strategy_name(name: str, side: str = "buy") -> str:
    return canonical_strategy_name(name, side)


def is_delegatable_strategy(name: str, side: Optional[str] = None) -> bool:
    canonical = resolve_strategy_name(name, side or "buy")
    if side:
        allowed = DELEGATABLE_BUY_STRATEGIES if side.lower() == "buy" else DELEGATABLE_SELL_STRATEGIES
        return canonical in allowed
    return canonical in DELEGATABLE_STRATEGIES


def get_catalog_entry(name: str, side: str = "buy") -> Optional[StrategyCatalogEntry]:
    canonical = resolve_strategy_name(name, side)
    return STRATEGY_CATALOG.get(canonical)


def get_strategy_param_glossary() -> List[Dict[str, Any]]:
    seen: Dict[str, StrategyParamSpec] = {}
    for entry in STRATEGY_CATALOG.values():
        for spec in entry.params:
            seen.setdefault(spec.query_name, spec)
    glossary: List[Dict[str, Any]] = []
    for name in sorted(seen.keys()):
        spec = seen[name]
        glossary.append(
            {
                "query_name": spec.query_name,
                "label": spec.label,
                "type": spec.param_type,
                "aliases": [key for key, value in QUERY_PARAM_ALIASES.items() if value == spec.query_name],
            }
        )
    return glossary


def get_delegatable_strategies(side: Optional[str] = None) -> List[Dict[str, Any]]:
    names: Set[str]
    if side and side.lower() == "buy":
        names = DELEGATABLE_BUY_STRATEGIES
    elif side and side.lower() == "sell":
        names = DELEGATABLE_SELL_STRATEGIES
    else:
        names = DELEGATABLE_STRATEGIES

    payload: List[Dict[str, Any]] = []
    for name in sorted(names):
        entry = STRATEGY_CATALOG.get(name)
        if not entry:
            continue
        payload.append(
            {
                "name": entry.name,
                "side": entry.side,
                "purpose": entry.purpose,
                "aliases": list(entry.aliases),
                "requires_nepse_alpha": entry.requires_nepse_alpha,
                "requires_market_depth": entry.requires_market_depth,
                "requires_holdings": entry.requires_holdings,
                "has_handler": entry.handler_name in HANDLERS if entry.handler_name else name in {"Time-Based Buy", "Time-Based Exit"},
                "params": [
                    {
                        "query_name": spec.query_name,
                        "label": spec.label,
                        "type": spec.param_type,
                        "required": spec.required,
                        "default": spec.default,
                    }
                    for spec in entry.params
                ],
            }
        )
    return payload


def _parse_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"true", "yes", "1"}:
        return True
    if text in {"false", "no", "0"}:
        return False
    return None


def _parse_number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _parse_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if value is None or value == "":
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    from utils.api_time import parse_nepal_datetime_local_to_utc

    parsed = parse_nepal_datetime_local_to_utc(text)
    return parsed if parsed else None


def _coerce_param_value(spec: StrategyParamSpec, raw: Any) -> tuple[Optional[Any], Optional[str]]:
    if spec.param_type == "number":
        number = _parse_number(raw)
        if number is None:
            return None, f"{spec.query_name} must be a number"
        if number <= 0 and spec.query_name not in {"FIRST_PERCENT", "SECOND_PERCENT"}:
            return None, f"{spec.query_name} must be greater than zero"
        return number, None
    if spec.param_type == "boolean":
        parsed = _parse_bool(raw)
        if parsed is None:
            return None, f"{spec.query_name} must be TRUE or FALSE"
        return parsed, None
    if spec.param_type == "datetime":
        parsed = _parse_datetime(raw)
        if parsed is None:
            return None, f"{spec.query_name} must be a valid date/time"
        return parsed, None
    text = str(raw or "").strip()
    if not text:
        return None, f"{spec.query_name} must be a non-empty string"
    return text, None


def normalize_strategy_params(raw_params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}
    for key, value in (raw_params or {}).items():
        normalized[normalize_query_param_name(key)] = value
    return normalized


def _set_path(target: Dict[str, Any], path: str, value: Any) -> None:
    if path.startswith("partial_legs."):
        _, index_text, field = path.split(".", 2)
        legs = target.setdefault("partial_legs", [])
        while len(legs) <= int(index_text):
            legs.append({"id": f"target{len(legs) + 1}", "targetPrice": 0, "sellPercent": 0})
        key = "targetPrice" if field == "targetPrice" else "sellPercent"
        legs[int(index_text)][key] = value
        return
    if path.startswith("config."):
        config = target.setdefault("config", {})
        config[path.split(".", 1)[1]] = value
        return
    target[path] = value


def map_strategy_params_to_order_fields(
    strategy_name: str,
    raw_params: Optional[Dict[str, Any]],
    *,
    side: str = "buy",
) -> tuple[Dict[str, Any], List[StrategyParamValidationIssue]]:
    entry = get_catalog_entry(strategy_name, side)
    if not entry:
        return {}, [StrategyParamValidationIssue("UNKNOWN_STRATEGY", f"Unknown strategy: {strategy_name}")]

    params = normalize_strategy_params(raw_params)
    issues: List[StrategyParamValidationIssue] = []
    mapped: Dict[str, Any] = {"strategy_type": entry.name, "config": {}}

    spec_by_name = {spec.query_name: spec for spec in entry.params}
    for query_name, raw_value in params.items():
        spec = spec_by_name.get(query_name)
        if spec is None:
            issues.append(
                StrategyParamValidationIssue(
                    "UNKNOWN_STRATEGY_PARAM",
                    f"Unknown parameter {query_name} for strategy {entry.name}",
                    param=query_name,
                )
            )
            continue
        value, error = _coerce_param_value(spec, raw_value)
        if error:
            issues.append(
                StrategyParamValidationIssue("INVALID_STRATEGY_PARAM", error, param=query_name)
            )
            continue
        _set_path(mapped, spec.field_path, value)

    for spec in entry.required_params:
        if spec.query_name not in params and spec.default is None:
            issues.append(
                StrategyParamValidationIssue(
                    "MISSING_STRATEGY_PARAM",
                    f"{spec.query_name} is required for {entry.name}",
                    param=spec.query_name,
                )
            )

    if entry.name == "Capital Protection Sell":
        if not mapped.get("stop_loss_price") and not mapped.get("average_buy_price"):
            issues.append(
                StrategyParamValidationIssue(
                    "MISSING_STRATEGY_PARAM",
                    "STOP_LOSS_PRICE or AVERAGE_BUY_PRICE is required for Capital Protection Sell",
                )
            )

    if entry.name == "Profit Ladder Sell" and not issues:
        legs = mapped.get("partial_legs") or []
        if len(legs) >= 2:
            first = legs[0]
            second = legs[1]
            percent_total = float(first.get("sellPercent") or 0) + float(second.get("sellPercent") or 0)
            if percent_total <= 0 or percent_total > 100:
                issues.append(
                    StrategyParamValidationIssue(
                        "INVALID_STRATEGY_PARAM",
                        "FIRST_PERCENT and SECOND_PERCENT must total 100% or less",
                    )
                )
            if float(second.get("targetPrice") or 0) <= float(first.get("targetPrice") or 0):
                issues.append(
                    StrategyParamValidationIssue(
                        "INVALID_STRATEGY_PARAM",
                        "SECOND_TARGET must be above FIRST_TARGET",
                    )
                )

    if entry.name == "Emergency Exit by Top Buyer":
        if mapped.get("emergency_execution") is not True:
            issues.append(
                StrategyParamValidationIssue(
                    "MISSING_STRATEGY_PARAM",
                    "EMERGENCY_CONFIRMED TRUE is required for Emergency Exit by Top Buyer",
                    param="EMERGENCY_CONFIRMED",
                )
            )

    return mapped, issues


def validate_strategy_params(
    strategy_name: str,
    raw_params: Optional[Dict[str, Any]],
    *,
    side: str,
    ltp: Optional[float] = None,
) -> List[StrategyParamValidationIssue]:
    canonical = resolve_strategy_name(strategy_name, side)
    issues: List[StrategyParamValidationIssue] = []

    if not is_delegatable_strategy(canonical, side):
        if canonical in RULE_BASED_STRATEGIES:
            return [
                StrategyParamValidationIssue(
                    "STRATEGY_NOT_DELEGATABLE",
                    f"{canonical} cannot be referenced with USE STRATEGY",
                )
            ]
        return [StrategyParamValidationIssue("UNKNOWN_STRATEGY", f"Unknown strategy: {strategy_name}")]

    entry = get_catalog_entry(canonical, side)
    if not entry:
        return [StrategyParamValidationIssue("UNKNOWN_STRATEGY", f"Unknown strategy: {strategy_name}")]

    if entry.side != side.lower():
        issues.append(
            StrategyParamValidationIssue(
                "STRATEGY_SIDE_MISMATCH",
                f"{entry.name} is a {entry.side.upper()} strategy but plan side is {side.upper()}",
            )
        )

    _, param_issues = map_strategy_params_to_order_fields(canonical, raw_params, side=side)
    issues.extend(param_issues)

    if ltp and ltp > 0:
        mapped, _ = map_strategy_params_to_order_fields(canonical, raw_params, side=side)
        stop = mapped.get("stop_loss_price")
        if entry.name == "Capital Protection Sell" and stop and float(stop) >= ltp:
            issues.append(
                StrategyParamValidationIssue(
                    "INVALID_STRATEGY_PARAM",
                    "STOP_LOSS_PRICE must be below current LTP",
                    param="STOP_LOSS_PRICE",
                )
            )
        if entry.name == "Profit Ladder Sell":
            legs = mapped.get("partial_legs") or []
            if legs and float(legs[0].get("targetPrice") or 0) <= ltp:
                issues.append(
                    StrategyParamValidationIssue(
                        "INVALID_STRATEGY_PARAM",
                        "FIRST_TARGET must be above current LTP",
                        param="FIRST_TARGET",
                    )
                )

    return issues


def build_order_context_from_rule(
    rule: Any,
    *,
    plan_side: str,
    symbol: str,
    qty: int,
    remaining_qty: Optional[int] = None,
) -> tuple[Optional[OrderContext], List[StrategyParamValidationIssue]]:
    strategy_name = getattr(rule, "use_strategy", None) or (rule.get("use_strategy") if isinstance(rule, dict) else None)
    if not strategy_name:
        return None, [StrategyParamValidationIssue("MISSING_STRATEGY", "Rule is missing USE STRATEGY")]

    raw_params = getattr(rule, "strategy_params", None)
    if raw_params is None and isinstance(rule, dict):
        raw_params = rule.get("strategy_params")

    side = plan_side.lower()
    mapped, issues = map_strategy_params_to_order_fields(strategy_name, raw_params, side=side)
    if issues:
        return None, issues

    canonical = resolve_strategy_name(strategy_name, side)
    config_payload = mapped.pop("config", {})
    config = StrategyConfig(
        min_buy_score=float(config_payload.get("min_buy_score") or 65),
        require_fresh_trade=bool(config_payload.get("require_fresh_trade")),
        require_volume_increase=bool(config_payload.get("require_volume_increase")),
        allow_market_depth_filter=bool(config_payload.get("allow_market_depth_filter", True)),
        wrapped_strategy_type=config_payload.get("wrapped_strategy_type"),
        expiry_action=config_payload.get("expiry_action") or mapped.get("expiry_action"),
        break_even_trigger_pct=float(config_payload.get("break_even_trigger_pct") or 3.0),
        allow_split_emergency_exit=bool(config_payload.get("allow_split_emergency_exit")),
        extra=dict(config_payload.get("extra") or {}),
    )

    return OrderContext(
        strategy_type=canonical,
        canonical_strategy=canonical,
        side=side,
        symbol=symbol.upper(),
        qty=int(qty or 0),
        remaining_qty=int(remaining_qty if remaining_qty is not None else qty or 0),
        target_price=float(mapped.get("target_price") or 0),
        stop_loss_price=mapped.get("stop_loss_price"),
        average_buy_price=mapped.get("average_buy_price"),
        trailing_drop_percent=float(mapped.get("trailing_drop_percent") or config.trailing_stop_pct or 3.0),
        activation_price=mapped.get("activation_price"),
        partial_legs=list(mapped.get("partial_legs") or []),
        expiry_time=mapped.get("expiry_time"),
        expiry_action=mapped.get("expiry_action"),
        max_allowed_slippage_percent=float(mapped.get("max_allowed_slippage_percent") or 1.0),
        emergency_execution=bool(mapped.get("emergency_execution")),
        config=config,
    ), []


def assert_catalog_covers_handlers() -> None:
    missing_catalog = [name for name in DELEGATABLE_STRATEGIES if name not in STRATEGY_CATALOG]
    if missing_catalog:
        raise RuntimeError(f"Missing strategy catalog entries: {', '.join(sorted(missing_catalog))}")

    handler_backed = DELEGATABLE_STRATEGIES - {"Time-Based Buy", "Time-Based Exit"}
    missing_handlers = [name for name in handler_backed if name not in HANDLERS]
    if missing_handlers:
        raise RuntimeError(f"Missing handlers for catalog entries: {', '.join(sorted(missing_handlers))}")


assert_catalog_covers_handlers()
