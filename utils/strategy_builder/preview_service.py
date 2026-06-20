from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from utils.strategy_builder.history_service import TargetHistory
from utils.strategy_builder.market_normalizer import build_symbol_snapshot_from_parts
from utils.strategy_builder.preview_builder import build_rule_preview, format_preview_value
from utils.strategy_builder.reference_dependencies import collect_reference_fields_from_plan, plan_uses_reference
from utils.strategy_builder.reference_store import ReferenceEvaluationError, ReferenceRow, ReferenceStore, build_preview_reference_store
from utils.strategy_builder.rule_evaluator import evaluate_rule, update_history_from_snapshot
from utils.strategy_builder.strategy_models import StrategyPlanAST
from utils.strategies.types import OrderContext, ScannerMemory
from utils.strategies.normalize import get_script_details, normalize_tms_quote
from utils.strategies.types import ScriptDetails


def _preview_ltp(details: ScriptDetails, quote: Optional[Dict[str, Any]] = None) -> float:
    if quote:
        ltp = quote.get("ltp")
        if ltp is not None and float(ltp) > 0:
            return float(ltp)
    if details.reference_ltp is not None and float(details.reference_ltp) > 0:
        return float(details.reference_ltp)
    for candidate in (details.fifty_two_week_high, details.fifty_two_week_low):
        if candidate is not None and float(candidate) > 0:
            return float(candidate)
    return 100.0


def _format_preview_number(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return f"{int(number):,}"
    return f"{number:,.2f}"


def _status_label(status: Optional[str]) -> str:
    mapping = {
        "MATCHED": "Ready",
        "NOT_ELIGIBLE": "Not eligible",
        "NOT_MATCHED": "Signal not met",
        "REQUIRE_FAILED": "Requirement failed",
        "ALREADY_EXECUTED": "Already executed",
        "REFERENCE_NOT_FOUND": "Reference missing",
        "MISSING_DATA": "Missing data",
    }
    normalized = str(status or "").upper()
    if normalized.startswith("WAITING"):
        return "Waiting"
    return mapping.get(normalized, status or "—")


def _primary_blocker(evaluation) -> Optional[str]:
    failed = [item for item in (evaluation.conditions or []) if not item.matched]
    if failed:
        item = failed[0]
        actual = _format_preview_number(item.actual_value)
        expected = _format_preview_number(item.expected_value)
        if actual and expected:
            return f"{item.expression} · have {actual}, need {expected}"
        if actual:
            return f"{item.expression} · actual {actual}"
        return str(item.expression)
    if evaluation.matched:
        return "All checks passed"
    if evaluation.status == "NOT_ELIGIBLE":
        return "Eligibility filter not met"
    if evaluation.status == "NOT_MATCHED":
        return "Signal conditions not met"
    return None


def _preview_reference_ltp(
    reference_store: Optional[ReferenceStore],
    *,
    rule_name: str,
    symbol: str,
) -> Optional[float]:
    if reference_store is None:
        return None
    try:
        return float(reference_store.get_value(rule_name, symbol, "ltp"))
    except ReferenceEvaluationError:
        return None


def _summarize_conditions(evaluation) -> Optional[str]:
    blocker = _primary_blocker(evaluation)
    if blocker and not evaluation.matched:
        return blocker
    if evaluation.status == "NOT_ELIGIBLE":
        return "Eligibility filter not met"
    if evaluation.status == "NOT_MATCHED":
        return "Signal conditions not met"
    if evaluation.status.startswith("WAITING_CONFIRMATION"):
        return f"Waiting for confirmation ({evaluation.status})"
    if evaluation.status.startswith("WAITING_MATCHES"):
        return f"Waiting for confirmation ({evaluation.status})"
    return None


def _preview_message(
    *,
    details: ScriptDetails,
    evaluation,
) -> Optional[str]:
    parts: List[str] = []
    if not details.available:
        if details.fetch_error:
            parts.append(f"Nepse Alpha unavailable: {details.fetch_error}")
        else:
            parts.append("Nepse Alpha data may be incomplete for technical fields.")
    summary = _summarize_conditions(evaluation)
    if summary and not evaluation.matched:
        parts.append(summary)
    return " · ".join(parts) if parts else None


async def _fetch_preview_quote(client_id: Optional[str], symbol: str, db) -> Optional[Dict[str, Any]]:
    if not client_id or db is None:
        return None
    from utils.tms_client_resolver import get_tms_user_for_client

    try:
        tms_user = await get_tms_user_for_client(client_id, db)
        security = await tms_user.get_security_id(symbol)
        if not security or not security.get("id"):
            return None
        return await tms_user.get_stock_details_async(
            str(security["id"]),
            max_retries=1,
            retry_backoff=False,
        )
    except Exception:
        return None


def _preview_reference_store_from_flat(
    plan: StrategyPlanAST,
    rule,
    symbol: str,
    flat: Dict[str, Any],
    *,
    fallback_values: Optional[Dict[str, Any]] = None,
) -> Optional[ReferenceStore]:
    from utils.strategy_builder.reference_capture import _typed_row_value

    per_rule = collect_reference_fields_from_plan(plan)
    fields = per_rule.get(rule.name) or set()
    if not fields:
        return None
    rows: List[ReferenceRow] = []
    normalized_symbol = symbol.strip().upper()
    fallbacks = fallback_values or {}
    for field_key in sorted(fields):
        raw_value = flat.get(field_key)
        if raw_value in (None, ""):
            raw_value = fallbacks.get(field_key)
        if raw_value in (None, ""):
            continue
        try:
            field_type, numeric_value, text_value, boolean_value = _typed_row_value(field_key, raw_value)
        except Exception:
            continue
        rows.append(
            ReferenceRow(
                rule_name=rule.name,
                symbol=normalized_symbol,
                field_key=field_key,
                field_type=field_type,
                numeric_value=numeric_value,
                text_value=text_value,
                boolean_value=boolean_value,
                source="preview_quote",
            )
        )
    return ReferenceStore(rows) if rows else None


def _resolve_preview_reference_store(
    plan: StrategyPlanAST,
    rule,
    symbol: str,
    flat: Dict[str, Any],
    reference_store: Optional[ReferenceStore],
    *,
    fallback_values: Optional[Dict[str, Any]] = None,
) -> Optional[ReferenceStore]:
    if not plan_uses_reference(plan):
        return reference_store
    needed = collect_reference_fields_from_plan(plan).get(rule.name) or set()
    missing = not needed or any(
        reference_store is None
        or not reference_store.is_reference_available(rule.name, symbol, field_key)
        for field_key in needed
    )
    if not missing:
        return reference_store
    supplemental = _preview_reference_store_from_flat(
        plan,
        rule,
        symbol,
        flat,
        fallback_values=fallback_values,
    )
    if supplemental is None:
        return reference_store
    if reference_store is None:
        return supplemental
    return reference_store.fill_missing_from(supplemental)


async def _preview_symbol(
    rule,
    symbol: str,
    *,
    plan: StrategyPlanAST,
    plan_side: str,
    client_id: Optional[str],
    db,
    reference_store: Optional[ReferenceStore] = None,
    holdings_by_symbol: Optional[Dict[str, int]] = None,
    holding_retrieval_failed: bool = False,
) -> Dict[str, Any]:
    try:
        details = await asyncio.to_thread(get_script_details, symbol, force_refresh=False)
        quote = await _fetch_preview_quote(client_id, symbol, db)
        snapshot = normalize_tms_quote(symbol, quote or {"ltp": _preview_ltp(details, quote)})
        normalized = build_symbol_snapshot_from_parts(symbol, snapshot, details)
        history = TargetHistory()
        update_history_from_snapshot(history, normalized["flat"])
        live_ltp = float(snapshot.ltp or 0) if snapshot.ltp else None
        preview_ltp = live_ltp or _preview_ltp(details, quote)
        reference_store = _resolve_preview_reference_store(
            plan,
            rule,
            symbol,
            normalized["flat"],
            reference_store,
            fallback_values={"ltp": preview_ltp},
        )
        evaluation = evaluate_rule(
            rule,
            symbol,
            normalized["flat"],
            history,
            trigger_on_cross=False,
            reference_store=reference_store,
        )
        reference_ltp = _preview_reference_ltp(reference_store, rule_name=rule.name, symbol=symbol)
        normalized_symbol = symbol.strip().upper()
        current_holding: Optional[int] = None
        holding_failed = holding_retrieval_failed
        if holdings_by_symbol is not None and not holding_failed:
            current_holding = int(holdings_by_symbol.get(normalized_symbol, 0) or 0)
        elif holding_failed:
            current_holding = None
        row: Dict[str, Any] = {}
        use_strategy = getattr(rule, "use_strategy", None)
        strategy_action = None
        if use_strategy:
            row["strategy"] = use_strategy
            if not evaluation.matched:
                row["status_label"] = _status_label(evaluation.status)
                row["blocker"] = f"Gate blocked · {_primary_blocker(evaluation)}"
            else:
                from utils.strategy_builder.strategy_delegate import (
                    evaluate_delegated_strategy,
                    map_delegated_decision_to_rule_action,
                )

                parent_ctx = OrderContext(
                    strategy_type=f"Custom Query {plan_side.title()}",
                    canonical_strategy=f"Custom Query {plan_side.title()}",
                    side=plan_side.lower(),
                    symbol=symbol.upper(),
                    qty=int(getattr(rule.order, "value", None) or 10),
                    remaining_qty=int(getattr(rule.order, "value", None) or 10),
                    target_price=float(snapshot.ltp or 0),
                )
                memory = ScannerMemory(
                    last_prices=[float(snapshot.ltp or 0)],
                    previous_ltp=float(snapshot.ltp or 0) if snapshot.ltp else None,
                )
                delegated = evaluate_delegated_strategy(
                    rule,
                    plan_side=plan_side,
                    symbol=symbol,
                    parent_ctx=parent_ctx,
                    snapshot=snapshot,
                    memory=memory,
                    details=details,
                )
                mapped = map_delegated_decision_to_rule_action(
                    delegated,
                    symbol=symbol,
                    strategy_name=use_strategy,
                )
                row["strategy_action"] = mapped.action
                strategy_action = mapped.action
                evaluation = evaluation.model_copy(
                    update={
                        "matched": mapped.action == "EXECUTE",
                        "status": mapped.reason_code or mapped.action,
                    }
                )
                if mapped.action == "EXECUTE":
                    row["status_label"] = "Ready"
                    row["blocker"] = mapped.reason or "Strategy ready to execute"
                else:
                    row["status_label"] = "Monitoring" if mapped.action == "TRACK" else _status_label(mapped.action)
                    row["blocker"] = mapped.reason or mapped.tracking_status or "Strategy not ready"
        message = _preview_message(
            details=details,
            evaluation=evaluation,
        )
        preview = build_rule_preview(
            rule=rule,
            symbol=symbol,
            plan_side=plan_side,
            flat=normalized["flat"],
            evaluation=evaluation,
            history=history,
            status_label=row.get("status_label") or _status_label(evaluation.status),
            live_ltp=live_ltp or _preview_ltp(details, quote),
            reference_ltp=reference_ltp,
            current_holding=current_holding,
            holding_retrieval_failed=holding_failed,
            blocker=row.get("blocker") or _primary_blocker(evaluation),
            message=message,
            nepse_alpha_available=details.available,
            strategy=use_strategy,
            strategy_action=strategy_action,
        )
        row = preview.to_legacy_row()
        row["rule"] = rule.name
        if use_strategy:
            row["strategy"] = use_strategy
        return row
    except ReferenceEvaluationError as exc:
        return {
            "symbol": symbol,
            "rule": rule.name,
            "matched": False,
            "status": exc.code,
            "message": str(exc),
        }
    except Exception as exc:
        return {
            "symbol": symbol,
            "rule": rule.name,
            "matched": False,
            "status": "MISSING_DATA",
            "message": str(exc),
        }


async def build_rule_previews(
    plan: StrategyPlanAST,
    *,
    client_id: Optional[str] = None,
    db=None,
    preview_references: Optional[Dict[str, Dict[str, Any]]] = None,
    holdings_by_symbol: Optional[Dict[str, int]] = None,
    holding_retrieval_failed: bool = False,
) -> List[Dict[str, Any]]:
    reference_store: Optional[ReferenceStore] = None
    if preview_references and plan_uses_reference(plan):
        reference_store = build_preview_reference_store(plan, preview_references)
    elif plan_uses_reference(plan) and client_id and db is not None:
        try:
            from utils.strategy_builder.reference_capture import capture_references_for_preview_plan
            from utils.tms_client_resolver import get_tms_user_for_client

            tms_user = await get_tms_user_for_client(client_id, db)
            reference_store = await capture_references_for_preview_plan(tms_user, plan=plan)
        except Exception:
            reference_store = None

    resolved_holdings = dict(holdings_by_symbol or {})
    holdings_failed = holding_retrieval_failed
    if plan.side == "SELL" and client_id and db is not None and not resolved_holdings:
        try:
            from utils.strategy_builder.holdings_preflight import build_holdings_map
            from utils.tms_client_resolver import get_tms_user_for_client

            tms_user = await get_tms_user_for_client(client_id, db)
            resolved_holdings = await build_holdings_map(tms_user)
        except Exception:
            holdings_failed = True

    semaphore = asyncio.Semaphore(3)

    async def _guarded_preview(rule, symbol: str) -> Dict[str, Any]:
        async with semaphore:
            return await _preview_symbol(
                rule,
                symbol,
                plan=plan,
                plan_side=plan.side,
                client_id=client_id,
                db=db,
                reference_store=reference_store,
                holdings_by_symbol=resolved_holdings,
                holding_retrieval_failed=holdings_failed,
            )

    tasks = []
    for rule in plan.rules:
        for symbol in rule.symbols:
            tasks.append(_guarded_preview(rule, symbol))
    if not tasks:
        return []
    return list(await asyncio.gather(*tasks))


def build_rule_previews_sync(plan: StrategyPlanAST) -> List[Dict[str, Any]]:
    """Backward-compatible sync wrapper without live TMS quotes."""
    return asyncio.run(build_rule_previews(plan))
