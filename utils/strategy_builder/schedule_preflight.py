from __future__ import annotations

from typing import Dict, List, Optional, Set

from sqlalchemy.orm import Session

from models.logged_in_user import LoggedInUsers
from models.user import User
from utils.strategy_builder.feature_registry import (
    SCHEDULE_UNSUPPORTED_FUNCTIONS,
    classify_field,
    classify_function,
)
from utils.strategy_builder.market_normalizer import build_symbol_snapshot_from_parts
from utils.strategy_builder.plan_expression_walk import walk_plan_expressions
from utils.strategy_builder.strategy_fields import (
    DERIVED_LIVE_FIELDS,
    DERIVED_STAT_FIELDS,
    LIVE_FIELDS,
    MARKET_DEPTH_FIELDS,
    get_field_metadata,
)
from utils.strategy_builder.strategy_models import StrategyPlanAST, ValidationIssue
from utils.strategy_builder.strategy_parser import StrategyQueryError, parse_strategy_query
from utils.strategy_builder.strategy_validator import validate_strategy_plan
from utils.strategies.normalize import get_script_details, normalize_tms_quote
from config.app_environment import is_testing

NEPSE_ALPHA_CATEGORIES = {
    "technical",
    "fundamental",
    "statistical",
    "sector",
}

TMS_CATEGORIES = {"live", "derived_live", "market_depth"}

_DERIVED_STATISTICAL_KEYS = {item["key"] for item in DERIVED_STAT_FIELDS}
_DERIVED_LIVE_KEYS = {item["key"] for item in DERIVED_LIVE_FIELDS}
_MARKET_DEPTH_KEYS = {item["key"] for item in MARKET_DEPTH_FIELDS}
_TMS_FIELD_KEYS = {
    str(item["key"])
    for group in (LIVE_FIELDS, DERIVED_LIVE_FIELDS, DERIVED_STAT_FIELDS, MARKET_DEPTH_FIELDS)
    for item in group
}
_NEPSE_PREREQ_FOR_DERIVED_STAT = {
    "fifty_two_week_high",
    "fifty_two_week_low",
}


def _field_data_source(field_name: str) -> str:
    if classify_field(field_name) == "UNSUPPORTED_DATA":
        return "unsupported"
    if field_name in _DERIVED_STATISTICAL_KEYS:
        return "derived_statistical"
    if field_name in _DERIVED_LIVE_KEYS:
        return "tms_derived"
    if field_name in _TMS_FIELD_KEYS:
        return "tms"
    meta = get_field_metadata(field_name) or {}
    category = str(meta.get("category") or "")
    if category == "derived_statistical":
        return "derived_statistical"
    if category in TMS_CATEGORIES:
        return "tms" if category == "live" else "tms_derived"
    if category in NEPSE_ALPHA_CATEGORIES:
        return "nepse_alpha"
    if field_name.startswith(("technical_", "fundamental_", "alpha_", "beta_", "sharpe_", "volatility_")):
        return "nepse_alpha"
    if field_name in {"ltp", "volume", "open", "high", "low", "previous_close", "change", "change_percent"}:
        return "tms"
    if field_name in _MARKET_DEPTH_KEYS or field_name in {"best_bid", "best_ask", "spread", "spread_percent"}:
        return "tms"
    return "runtime"


def _symbols_for_plan(plan: StrategyPlanAST, script_name: Optional[str] = None) -> Set[str]:
    symbols: Set[str] = set()
    for rule in plan.rules:
        for symbol in rule.symbols:
            symbols.add(symbol.upper())
    if script_name:
        symbols.add(script_name.strip().upper())
    return {symbol for symbol in symbols if symbol}


def _preflight_target_symbols(plan: StrategyPlanAST, script_name: Optional[str] = None) -> Set[str]:
    """Symbols to verify at schedule time (one order = one symbol, not the whole IN list)."""
    if script_name and script_name.strip():
        return {script_name.strip().upper()}
    return _symbols_for_plan(plan, None)


def _missing_nepse_fields(symbol: str, details, required_fields: Set[str]) -> List[str]:
    snapshot = normalize_tms_quote(symbol, {"ltp": details.reference_ltp or details.fifty_two_week_high or 1})
    normalized = build_symbol_snapshot_from_parts(symbol, snapshot, details)
    flat = normalized.get("flat") or {}
    missing: List[str] = []
    for field_name in sorted(required_fields):
        if _field_data_source(field_name) != "nepse_alpha":
            continue
        value = flat.get(field_name)
        if value is None or value == "":
            missing.append(field_name)
    return missing


def _missing_derived_stat_fields(symbol: str, details, quote: dict, required_fields: Set[str]) -> List[str]:
    if not required_fields:
        return []
    snapshot = normalize_tms_quote(symbol, quote or {})
    normalized = build_symbol_snapshot_from_parts(symbol, snapshot, details)
    flat = normalized.get("flat") or {}
    missing: List[str] = []
    for field_name in sorted(required_fields):
        if flat.get(field_name) is None:
            missing.append(field_name)
    prereq_missing = [
        key
        for key in sorted(_NEPSE_PREREQ_FOR_DERIVED_STAT)
        if flat.get(key) is None
    ]
    if prereq_missing and missing:
        return missing
    return missing


async def run_schedule_preflight(
    *,
    query_text: Optional[str],
    compiled_plan: Optional[dict],
    strategy_type: Optional[str],
    client_id: Optional[str],
    script_name: Optional[str],
    db: Session,
    holdings: Optional[Dict[str, int]] = None,
    known_symbols: Optional[Set[str]] = None,
    capture_reference_ltp: bool = False,
    drop_percent: float = 10.0,
    fixed_symbols: Optional[List[str]] = None,
) -> dict:
    errors: List[ValidationIssue] = []
    warnings: List[ValidationIssue] = []

    plan: Optional[StrategyPlanAST] = None
    if compiled_plan:
        try:
            plan = StrategyPlanAST.model_validate(compiled_plan)
        except Exception as exc:
            return _result(
                ready=False,
                status="parse_error",
                message=f"Compiled plan is invalid: {exc}",
                errors=[ValidationIssue(code="INVALID_PLAN", message=str(exc))],
            )
    elif query_text and query_text.strip():
        try:
            from utils.strategy_builder.schedule_baseline import reject_self_referential_drop_query

            reject_self_referential_drop_query(query_text)
            plan = parse_strategy_query(query_text)
        except StrategyQueryError as exc:
            return _result(
                ready=False,
                status="parse_error",
                message=str(exc),
                errors=[ValidationIssue(code="PARSE_ERROR", message=str(exc))],
            )
    else:
        return _result(
            ready=False,
            status="parse_error",
            message="Strategy query is required.",
            errors=[ValidationIssue(code="MISSING_QUERY", message="Strategy query is required.")],
        )

    validation = validate_strategy_plan(
        plan,
        strategy_type=strategy_type,
        form_symbol=script_name,
        known_symbols=known_symbols,
        holdings=holdings,
    )
    errors.extend(validation.errors)
    warnings.extend(validation.warnings)

    if validation.status == "unsupported_data":
        missing = ", ".join(validation.missing_items or [])
        return _result(
            ready=False,
            status="unsupported_feature",
            message=validation.message or "This query uses data or features that are not supported.",
            errors=errors,
            warnings=warnings,
            missing_items=validation.missing_items,
            suggestions=validation.suggestions,
        )

    if errors:
        first = errors[0].message
        return _result(
            ready=False,
            status="invalid_query",
            message=first,
            errors=errors,
            warnings=warnings,
        )

    fields, functions = walk_plan_expressions(plan)
    schedule_blocked_functions = sorted(
        name for name in functions if name in SCHEDULE_UNSUPPORTED_FUNCTIONS
    )
    if schedule_blocked_functions:
        joined = ", ".join(schedule_blocked_functions)
        message = (
            f"This query is not supported for scheduled monitoring. "
            f"It uses ranking function(s) that need a multi-symbol universe scan: {joined}."
        )
        errors.append(ValidationIssue(code="UNSUPPORTED_SCHEDULE_FUNCTION", message=message))
        return _result(
            ready=False,
            status="unsupported_feature",
            message=message,
            errors=errors,
            warnings=warnings,
            missing_items=schedule_blocked_functions,
        )

    unsupported_functions = sorted(
        name for name in functions if classify_function(name) == "UNSUPPORTED_DATA"
    )
    if unsupported_functions:
        joined = ", ".join(unsupported_functions)
        message = f"This query is not supported. It uses unsupported function(s): {joined}."
        errors.append(ValidationIssue(code="UNSUPPORTED_FUNCTION", message=message))
        return _result(
            ready=False,
            status="unsupported_feature",
            message=message,
            errors=errors,
            warnings=warnings,
            missing_items=unsupported_functions,
        )

    plan_symbols = _symbols_for_plan(plan, None)
    if script_name and plan_symbols:
        scheduled_symbol = script_name.strip().upper()
        if scheduled_symbol not in plan_symbols:
            message = (
                f"Scheduled symbol {scheduled_symbol} is not targeted by this query. "
                f"The query only monitors: {', '.join(sorted(plan_symbols))}."
            )
            errors.append(
                ValidationIssue(
                    code="FORM_SYMBOL_NOT_TARGETED",
                    symbol=scheduled_symbol,
                    message=message,
                )
            )
            return _result(
                ready=False,
                status="invalid_query",
                message=message,
                errors=errors,
                warnings=warnings,
            )

    if not client_id:
        errors.append(
            ValidationIssue(
                code="CLIENT_REQUIRED",
                message="Select a logged-in TMS client before scheduling a monitored query order.",
            )
        )
        return _result(
            ready=False,
            status="monitor_unavailable",
            message=errors[-1].message,
            errors=errors,
            warnings=warnings,
        )

    session = (
        db.query(LoggedInUsers)
        .filter(LoggedInUsers.client_id == client_id, LoggedInUsers.status == "logged_in")
        .first()
    )
    if not session:
        message = "Client is not logged in to TMS. Log in before scheduling a monitored order."
        errors.append(ValidationIssue(code="CLIENT_NOT_LOGGED_IN", message=message))
        return _result(
            ready=False,
            status="monitor_unavailable",
            message=message,
            errors=errors,
            warnings=warnings,
        )

    user = db.query(User).filter(User.client_id == client_id).first()
    if not user:
        message = "TMS account not found for the selected client."
        errors.append(ValidationIssue(code="USER_NOT_FOUND", message=message))
        return _result(
            ready=False,
            status="monitor_unavailable",
            message=message,
            errors=errors,
            warnings=warnings,
        )

    symbols = _preflight_target_symbols(plan, script_name)
    nepse_fields = {field for field in fields if _field_data_source(field) == "nepse_alpha"}
    derived_stat_fields = {field for field in fields if _field_data_source(field) == "derived_statistical"}
    tms_fields = {
        field
        for field in fields
        if _field_data_source(field) in {"tms", "tms_derived", "derived_statistical"}
    }
    market_depth_fields = {field for field in fields if field in _MARKET_DEPTH_KEYS}
    missing_data_by_symbol: Dict[str, List[str]] = {}
    tms_warnings: List[ValidationIssue] = []

    for symbol in sorted(symbols):
        if not nepse_fields and not derived_stat_fields:
            continue
        details = get_script_details(symbol, force_refresh=True)
        symbol_data_blocked = False
        if nepse_fields:
            if not getattr(details, "available", False):
                missing_data_by_symbol[symbol] = sorted(nepse_fields)
                detail = getattr(details, "fetch_error", None) or "Nepse Alpha request failed"
                errors.append(
                    ValidationIssue(
                        code="NEPSE_ALPHA_UNAVAILABLE",
                        symbol=symbol,
                        message=(
                            f"Nepse Alpha data is not available for {symbol} ({detail}). "
                            f"This query needs Nepse Alpha fields: {', '.join(sorted(nepse_fields))}."
                        ),
                    )
                )
                symbol_data_blocked = True
            else:
                missing = _missing_nepse_fields(symbol, details, nepse_fields)
                if missing:
                    missing_data_by_symbol[symbol] = missing
                    errors.append(
                        ValidationIssue(
                            code="NEPSE_ALPHA_FIELD_MISSING",
                            symbol=symbol,
                            message=(
                                f"Nepse Alpha does not currently provide {', '.join(missing)} for {symbol}. "
                                "This order cannot be monitored until that data is available."
                            ),
                        )
                    )
                    symbol_data_blocked = True
        if derived_stat_fields and not symbol_data_blocked:
            prereq_missing = [
                key
                for key in sorted(_NEPSE_PREREQ_FOR_DERIVED_STAT)
                if getattr(details, key, None) is None
            ]
            if prereq_missing:
                missing_data_by_symbol[symbol] = sorted(derived_stat_fields)
                errors.append(
                    ValidationIssue(
                        code="NEPSE_ALPHA_STAT_MISSING",
                        symbol=symbol,
                        message=(
                            f"Cannot compute {', '.join(sorted(derived_stat_fields))} for {symbol} "
                            f"because Nepse Alpha 52-week range is missing ({', '.join(prereq_missing)})."
                        ),
                    )
                )

    if errors:
        return _result(
            ready=False,
            status="missing_data",
            message=errors[0].message,
            errors=errors,
            warnings=warnings,
            missing_data_by_symbol=missing_data_by_symbol,
            compiled_plan=plan.model_dump(),
        )

    from utils.tms_client_resolver import get_tms_user_for_client

    tms_user = None
    try:
        tms_user = await get_tms_user_for_client(client_id, db)
    except Exception as exc:
        message = f"Cannot connect to TMS for monitoring: {exc}"
        errors.append(ValidationIssue(code="TMS_UNAVAILABLE", message=message))
        return _result(
            ready=False,
            status="monitor_unavailable",
            message=message,
            errors=errors,
            warnings=warnings,
        )

    from utils.strategy_builder.holdings_preflight import build_holdings_map

    resolved_holdings: Dict[str, int] = {}
    if holdings is not None:
        resolved_holdings = dict(holdings)
    elif tms_user is not None:
        try:
            resolved_holdings = await build_holdings_map(tms_user)
        except Exception:
            resolved_holdings = {}

    if (plan.side or "").upper() == "SELL" and resolved_holdings:
        for symbol in sorted(_preflight_target_symbols(plan, script_name)):
            held = int(resolved_holdings.get(symbol, 0) or 0)
            if held <= 0:
                message = (
                    f"Cannot schedule SELL for {symbol}: no sellable DP holding. "
                    "Acquire shares or remove this symbol from the query."
                )
                errors.append(
                    ValidationIssue(
                        code="SELL_NOT_HELD",
                        symbol=symbol,
                        message=message,
                    )
                )
        for rule in plan.rules:
            if not rule.order:
                continue
            for symbol in rule.symbols:
                sym = symbol.upper()
                held = int(resolved_holdings.get(sym, 0) or 0)
                if held <= 0:
                    continue
                if rule.order.mode == "quantity" and rule.order.value and int(rule.order.value) > held:
                    message = (
                        f"Cannot schedule SELL for {sym}: query requests {int(rule.order.value)} shares "
                        f"but only {held} are sellable."
                    )
                    errors.append(
                        ValidationIssue(
                            code="SELL_QTY_EXCEEDS_HOLDING",
                            symbol=sym,
                            message=message,
                        )
                    )
        if errors:
            return _result(
                ready=False,
                status="invalid_query",
                message=errors[0].message,
                errors=errors,
                warnings=warnings,
            )

    for symbol in sorted(symbols):
        if not tms_fields or tms_user is None:
            continue
        try:
            security = await tms_user.get_security_id(symbol)
            if not security:
                errors.append(
                    ValidationIssue(
                        code="TMS_SYMBOL_NOT_FOUND",
                        symbol=symbol,
                        message=f"{symbol} was not found in TMS for live price monitoring.",
                    )
                )
                continue
            quote = await tms_user.get_stock_details_async(security["id"], max_retries=1)
            if not quote or quote.get("ltp") in (None, 0):
                message = (
                    f"Live TMS quote is unavailable for {symbol}. "
                    f"This query needs live TMS fields: {', '.join(sorted(tms_fields))}."
                )
                issue = ValidationIssue(
                    code="TMS_QUOTE_UNAVAILABLE",
                    symbol=symbol,
                    message=message,
                )
                if is_testing():
                    tms_warnings.append(issue)
                else:
                    errors.append(issue)
                continue
            if derived_stat_fields:
                details = get_script_details(symbol, force_refresh=False)
                missing_derived = _missing_derived_stat_fields(symbol, details, quote, derived_stat_fields)
                if missing_derived:
                    missing_data_by_symbol[symbol] = missing_derived
                    errors.append(
                        ValidationIssue(
                            code="DERIVED_FIELD_MISSING",
                            symbol=symbol,
                            message=(
                                f"Cannot compute {', '.join(missing_derived)} for {symbol} "
                                "(needs live LTP plus Nepse Alpha 52-week high/low)."
                            ),
                        )
                    )
            if market_depth_fields:
                depth_snapshot = normalize_tms_quote(symbol, quote)
                has_depth = bool(depth_snapshot.top_buy_orders or depth_snapshot.top_sell_orders)
                if not has_depth:
                    tms_warnings.append(
                        ValidationIssue(
                            code="MARKET_DEPTH_EMPTY",
                            symbol=symbol,
                            message=(
                                f"TMS quote for {symbol} has no top buy/sell levels yet. "
                                "Depth-based rules may not match until the market session is live."
                            ),
                        )
                    )
        except Exception as exc:
            from utils.tms_broker import tms_host_for_broker

            host = tms_host_for_broker(str(getattr(tms_user, "broker_no", "") or ""))
            message = f"Could not fetch live TMS data for {symbol} from {host}: {exc}"
            issue = ValidationIssue(
                code="TMS_QUOTE_ERROR",
                symbol=symbol,
                message=message,
            )
            if is_testing():
                tms_warnings.append(issue)
            else:
                errors.append(issue)

    if errors:
        return _result(
            ready=False,
            status="missing_data",
            message=errors[0].message,
            errors=errors,
            warnings=warnings + tms_warnings,
            missing_data_by_symbol=missing_data_by_symbol,
            compiled_plan=plan.model_dump(),
        )

    warnings.extend(tms_warnings)

    preview_references: Dict[str, Dict[str, Any]] = {}
    from utils.strategy_builder.reference_dependencies import plan_uses_reference
    if plan_uses_reference(plan) and tms_user is not None and script_name:
        from utils.strategy_builder.reference_schedule import preview_field_references

        try:
            preview_references = await preview_field_references(
                tms_user=tms_user,
                symbol=script_name,
                plan=plan,
            )
        except Exception as exc:
            return _result(
                ready=False,
                status="baseline_unavailable",
                message=str(exc),
                errors=[ValidationIssue(code="REFERENCE_CAPTURE_FAILED", message=str(exc))],
                warnings=warnings,
            )

    symbol_baselines: List[dict] = []
    compiled_payload = plan.model_dump()
    if capture_reference_ltp and client_id and script_name and tms_user is not None:
        from utils.strategy_builder.schedule_baseline import (
            ScheduleBaselineError,
            capture_symbol_baseline_from_tms,
            compile_baseline_strategy_config,
        )

        try:
            baseline = await capture_symbol_baseline_from_tms(
                tms_user,
                script_name,
                drop_percent=drop_percent,
            )
            baseline_config = compile_baseline_strategy_config(
                query_text=query_text or "",
                symbol=script_name,
                baseline=baseline,
                fixed_symbols=fixed_symbols or [script_name.strip().upper()],
            )
            compiled_payload = baseline_config["compiled_plan"]
            symbol_baselines.append(baseline)
        except ScheduleBaselineError as exc:
            return _result(
                ready=False,
                status="baseline_unavailable",
                message=str(exc),
                errors=[ValidationIssue(code="BASELINE_UNAVAILABLE", message=str(exc))],
                warnings=warnings,
            )

    parts = ["Query can be monitored"]
    if nepse_fields:
        parts.append("Nepse Alpha data verified")
    if tms_fields and not tms_warnings:
        parts.append("live TMS quotes verified")
    elif tms_fields and tms_warnings and is_testing():
        parts.append("live TMS quote check deferred (test mode)")
    return _result(
        ready=True,
        status="ready",
        message=" with ".join(parts) + ".",
        errors=[],
        warnings=warnings,
        compiled_plan=compiled_payload,
        symbol_baselines=symbol_baselines,
        preview_references=preview_references,
    )


def _result(
    *,
    ready: bool,
    status: str,
    message: Optional[str],
    errors: List[ValidationIssue],
    warnings: Optional[List[ValidationIssue]] = None,
    missing_items: Optional[List[str]] = None,
    missing_data_by_symbol: Optional[Dict[str, List[str]]] = None,
    suggestions: Optional[List[ValidationIssue]] = None,
    compiled_plan: Optional[dict] = None,
    symbol_baselines: Optional[List[dict]] = None,
    preview_references: Optional[Dict[str, Dict[str, Any]]] = None,
) -> dict:
    return {
        "ready": ready,
        "valid": ready,
        "status": status,
        "message": message,
        "missing_items": missing_items or [],
        "missing_data_by_symbol": missing_data_by_symbol or {},
        "errors": [item.model_dump() for item in errors],
        "warnings": [item.model_dump() for item in (warnings or [])],
        "suggestions": [item.model_dump() for item in (suggestions or [])],
        "compiled_plan": compiled_plan,
        "symbol_baselines": symbol_baselines or [],
        "preview_references": preview_references or {},
        "baseline_warning": (
            "The reference LTP and trigger price will remain fixed after scheduling. "
            "Live LTP will continue to update during monitoring."
            if symbol_baselines
            else None
        ),
    }
