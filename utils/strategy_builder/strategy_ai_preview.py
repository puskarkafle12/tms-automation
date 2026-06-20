from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from sqlalchemy.orm import Session

from schemas.schemas import OrderCreateRequest
from utils.strategy_builder.preview_service import build_rule_previews
from utils.strategy_builder.reference_dependencies import plan_uses_reference
from utils.strategy_builder.strategy_models import StrategyPlanAST
from utils.strategy_builder.strategy_parser import StrategyQueryError, parse_strategy_query
from utils.strategy_builder.strategy_validator import validate_strategy_plan


async def resolve_preview_holdings(
    *,
    client_id: Optional[str],
    db: Session,
    plan_side: str,
    holdings_by_symbol: Optional[Dict[str, int]] = None,
) -> tuple[Dict[str, int], bool]:
    if holdings_by_symbol:
        return (
            {
                str(symbol).strip().upper(): int(value or 0)
                for symbol, value in holdings_by_symbol.items()
                if str(symbol).strip()
            },
            True,
        )
    if plan_side != "SELL" or not client_id:
        return {}, False
    from utils.strategy_builder.holdings_preflight import build_holdings_map
    from utils.tms_client_resolver import get_tms_user_for_client

    try:
        tms_user = await get_tms_user_for_client(client_id, db)
        holdings = await build_holdings_map(tms_user)
        return dict(holdings or {}), bool(holdings)
    except Exception:
        return {}, True


async def resolve_known_symbols(
    *,
    client_id: Optional[str],
    db: Session,
    known_symbols: Optional[List[str]] = None,
) -> Set[str]:
    resolved = {
        str(symbol).strip().upper()
        for symbol in (known_symbols or [])
        if str(symbol).strip()
    }
    if resolved or not client_id:
        return resolved
    from utils.tms_client_resolver import get_tms_user_for_client

    try:
        tms_user = await get_tms_user_for_client(client_id, db)
        stock_details = await tms_user.get_stock_details_async()
        for item in stock_details or []:
            symbol = str(item.get("symbol") or item.get("script") or "").strip().upper()
            if symbol:
                resolved.add(symbol)
    except Exception:
        pass
    return resolved


async def build_strategy_preview_validation(
    *,
    query_text: str,
    compiled_plan: Optional[dict],
    strategy_type: Optional[str],
    form_symbol: Optional[str],
    client_id: Optional[str],
    db: Session,
    holdings_by_symbol: Optional[Dict[str, int]] = None,
    known_symbols: Optional[List[str]] = None,
    include_schedule_preflight: bool = True,
) -> Dict[str, Any]:
    plan: StrategyPlanAST
    if compiled_plan:
        plan = StrategyPlanAST.model_validate(compiled_plan)
    else:
        try:
            plan = parse_strategy_query(query_text)
        except StrategyQueryError as exc:
            return {
                "valid": False,
                "errors": [{"code": "PARSE_ERROR", "message": str(exc)}],
                "warnings": [],
                "suggestions": [],
                "targets": [],
            }

    holdings, _ = await resolve_preview_holdings(
        client_id=client_id,
        db=db,
        plan_side=str(plan.side or "BUY"),
        holdings_by_symbol=holdings_by_symbol,
    )
    known = await resolve_known_symbols(
        client_id=client_id,
        db=db,
        known_symbols=known_symbols,
    )
    validation = validate_strategy_plan(
        plan,
        strategy_type=strategy_type,
        form_symbol=form_symbol,
        known_symbols=known or None,
        holdings=holdings,
        holdings_checked=bool(holdings) or plan.side != "SELL",
    )
    payload = validation.model_dump()
    if not validation.valid:
        return payload

    preview_holdings, holdings_checked = await resolve_preview_holdings(
        client_id=client_id,
        db=db,
        plan_side=str(plan.side or "BUY"),
        holdings_by_symbol=holdings_by_symbol,
    )
    holdings_failed = str(plan.side or "").upper() == "SELL" and bool(client_id) and not holdings_checked
    payload["preview"] = await build_rule_previews(
        plan,
        client_id=client_id,
        db=db,
        holdings_by_symbol=preview_holdings,
        holding_retrieval_failed=holdings_failed,
    )
    from utils.strategy_builder.schedule_preview_capture import (
        capture_batch_preview_snapshots,
        snapshots_from_preview_rows,
    )

    preview_snapshots = snapshots_from_preview_rows(payload["preview"])
    missing_trigger_symbols = [
        symbol
        for symbol, snapshot in preview_snapshots.items()
        if snapshot.get("estimated_trigger_price") is None
        and str(snapshot.get("estimated_trigger_price_display") or "") in {"", "—", "Unavailable"}
    ]
    if missing_trigger_symbols and client_id:
        retry_request = OrderCreateRequest(
            client_id=client_id,
            script_name=missing_trigger_symbols[0],
            order_type=str(plan.side or "buy").lower(),
            price=0,
            qty=0,
            status="pending",
            strategy_type=strategy_type,
            strategy_config={"compiled_plan": payload.get("compiled_plan") or plan.model_dump()},
        )
        retried = await capture_batch_preview_snapshots(
            retry_request,
            db,
            missing_trigger_symbols,
            holdings_by_symbol=preview_holdings,
            holding_retrieval_failed=holdings_failed,
        )
        preview_snapshots.update(retried)
    payload["schedule_preview_snapshots_by_symbol"] = preview_snapshots
    if plan_uses_reference(plan) and client_id:
        payload["preview_reference_note"] = (
            "Preview uses live quotes as temporary REFERENCE values per symbol. "
            "Final reference snapshots are captured once at schedule time."
        )
    if include_schedule_preflight:
        from utils.strategy_builder.schedule_preflight import run_schedule_preflight

        payload["schedule_preflight"] = await run_schedule_preflight(
            query_text=query_text,
            compiled_plan=payload.get("compiled_plan") or plan.model_dump(),
            strategy_type=strategy_type,
            client_id=client_id,
            script_name=form_symbol,
            db=db,
            holdings=preview_holdings or holdings,
            known_symbols=known or None,
        )
    return payload
