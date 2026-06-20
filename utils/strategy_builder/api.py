from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from utils.strategy_builder.strategy_fields import get_field_catalog, get_supported_functions
from utils.strategy_builder.strategy_parser import StrategyQueryError, extract_symbols_from_query, format_strategy_query, parse_strategy_query
from utils.strategy_builder.strategy_validator import validate_strategy_plan
from utils.strategy_builder.strategy_llm_prompt import build_strategy_query_llm_prompt
from utils.strategy_builder.ai_query import StrategyQueryAiError, execute_strategy_query_ai_with_retries

router = APIRouter(prefix="/api", tags=["strategy-builder"])


class StrategyQueryRequest(BaseModel):
    query_text: str = ""
    strategy_type: Optional[str] = None
    side: Optional[str] = None
    form_symbol: Optional[str] = None
    client_id: Optional[str] = None
    gui_plan: Optional[Dict[str, Any]] = None
    compiled_plan: Optional[Dict[str, Any]] = None
    capture_reference_ltp: bool = False
    drop_percent: float = 10.0
    fixed_symbols: Optional[List[str]] = None
    expiration: Optional[Dict[str, Any]] = None
    preview_references: Optional[Dict[str, Dict[str, Any]]] = None
    skip_live_checks: bool = False
    check_holdings: bool = False
    holdings_by_symbol: Optional[Dict[str, int]] = None
    known_symbols: Optional[List[str]] = None
    include_schedule_preflight: bool = False


class StrategyPlanCreateRequest(StrategyQueryRequest):
    name: str
    execution_mode: str = "paper"
    client_id: str
    user_id: Optional[str] = None


class StrategyAiGenerateRequest(BaseModel):
    message: str
    side: str = "buy"
    strategy_type: Optional[str] = None
    form_symbol: Optional[str] = None
    client_id: Optional[str] = None
    current_query: Optional[str] = None


class ScreenerDropBatchRequest(BaseModel):
    client_id: str
    query_text: str
    symbols: List[str]
    drop_percent: float = 10.0
    expiration: Optional[Dict[str, Any]] = None
    expiry_time: Optional[datetime] = None
    expiry_action: Optional[str] = None
    max_allowed_slippage_percent: float = 1.0
    default_qty: Optional[int] = None
    per_symbol_qty: Optional[Dict[str, int]] = None


class ScreenerDropCommitRequest(ScreenerDropBatchRequest):
    strategy_type: str = "Custom Query Buy"
    odd_lot_allowed: bool = False
    security_details_by_symbol: Optional[Dict[str, Dict[str, Any]]] = None


class CustomQueryBatchScheduleRequest(BaseModel):
    client_id: str
    symbols: List[str]
    order_type: str = "buy"
    order_fields: Dict[str, Any] = Field(default_factory=dict)
    security_details_by_symbol: Optional[Dict[str, Dict[str, Any]]] = None
    skip_preflight: bool = False


@router.get("/strategy-builder/fields")
async def strategy_builder_fields():
    return {"fields": get_field_catalog(), "functions": get_supported_functions()}


@router.get("/strategy-builder/strategies")
async def strategy_builder_strategies(side: Optional[str] = None):
    from utils.strategies.strategy_query_catalog import get_delegatable_strategies

    return {"strategies": get_delegatable_strategies(side)}


@router.get("/strategy-builder/functions")
async def strategy_builder_functions():
    return {"functions": get_supported_functions()}


@router.get("/strategy-builder/llm-prompt")
async def strategy_builder_llm_prompt(side: str = "buy", form_symbol: Optional[str] = None):
    return {"prompt": build_strategy_query_llm_prompt(side=side, form_symbol=form_symbol)}


@router.get("/strategy-builder/symbols")
async def strategy_builder_symbols(search: str = "", db: Session = Depends(get_db)):
    from models.logged_in_user import LoggedInUsers
    from utils.tms_client_resolver import get_tms_user_for_client

    rows = db.query(LoggedInUsers).filter(LoggedInUsers.status == "logged_in").all()
    symbols: List[str] = []
    for row in rows:
        try:
            tms_user = await get_tms_user_for_client(row.client_id, db)
            details = await tms_user.get_stock_details_async()
            for item in details or []:
                symbol = str(item.get("symbol") or item.get("script") or "").strip().upper()
                if symbol:
                    symbols.append(symbol)
        except Exception:
            continue
    unique = sorted(set(symbols))
    if search:
        needle = search.strip().upper()
        unique = [symbol for symbol in unique if needle in symbol]
    return {"symbols": unique[:50]}


@router.post("/strategy-plans/parse-query")
async def parse_query(body: StrategyQueryRequest):
    try:
        plan = parse_strategy_query(body.query_text)
    except StrategyQueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"compiled_plan": plan.model_dump(), "formatted_query": format_strategy_query(plan)}


@router.post("/strategy-plans/format-query")
async def format_query(body: StrategyQueryRequest):
    try:
        plan = parse_strategy_query(body.query_text)
    except StrategyQueryError as exc:
        return {
            "valid": False,
            "errors": [{"code": "PARSE_ERROR", "message": str(exc)}],
            "warnings": [],
            "suggestions": [],
            "targets": [],
        }
    return {"valid": True, "formatted_query": format_strategy_query(plan), "compiled_plan": plan.model_dump()}


@router.post("/strategy-plans/generate-query")
async def generate_strategy_query(body: StrategyAiGenerateRequest):
    message = (body.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required.")
    if body.current_query and body.current_query.strip():
        message = (
            f"{message.strip()}\n\n"
            f"Refine or replace this draft query if helpful:\n```\n{body.current_query.strip()}\n```"
        )
    try:
        return await execute_strategy_query_ai_with_retries(
            message,
            side=body.side,
            form_symbol=body.form_symbol,
            strategy_type=body.strategy_type,
        )
    except StrategyQueryAiError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "message": str(exc),
                "ai_status": exc.status,
                "generated_query": exc.generated_query,
                "valid": False,
                "status": exc.status,
            },
        ) from exc


async def _resolve_validate_holdings(body: StrategyQueryRequest, db) -> tuple[Dict[str, int], bool]:
    if body.holdings_by_symbol:
        holdings = {
            str(symbol).strip().upper(): int(value or 0)
            for symbol, value in body.holdings_by_symbol.items()
            if str(symbol).strip()
        }
        return holdings, True

    if not body.client_id:
        return {}, False

    if body.skip_live_checks and not body.check_holdings:
        return {}, False

    from utils.strategy_builder.holdings_preflight import build_holdings_map
    from utils.tms_client_resolver import get_tms_user_for_client

    try:
        tms_user = await get_tms_user_for_client(body.client_id, db)
        holdings = await build_holdings_map(tms_user)
        return holdings, bool(holdings)
    except Exception:
        return {}, False


@router.post("/strategy-plans/validate")
async def validate_plan(body: StrategyQueryRequest, db: Session = Depends(get_db)):
    try:
        plan = parse_strategy_query(body.query_text)
    except StrategyQueryError as exc:
        return {
            "valid": False,
            "errors": [{"code": "PARSE_ERROR", "message": str(exc)}],
            "warnings": [],
            "suggestions": [],
            "targets": [],
        }
    except Exception as exc:
        return {
            "valid": False,
            "errors": [{"code": "VALIDATE_ERROR", "message": str(exc) or "Could not validate strategy query."}],
            "warnings": [],
            "suggestions": [],
            "targets": [],
        }
    holdings, holdings_checked = await _resolve_validate_holdings(body, db)
    known_symbols: set[str] = set()
    if body.known_symbols:
        known_symbols = {
            str(symbol).strip().upper()
            for symbol in body.known_symbols
            if str(symbol).strip()
        }
    if body.client_id and not body.skip_live_checks and not known_symbols:
        from utils.tms_client_resolver import get_tms_user_for_client

        try:
            tms_user = await get_tms_user_for_client(body.client_id, db)
            stock_details = await tms_user.get_stock_details_async()
            for item in stock_details or []:
                symbol = str(item.get("symbol") or item.get("script") or "").strip().upper()
                if symbol:
                    known_symbols.add(symbol)
        except Exception:
            known_symbols = set()
    result = validate_strategy_plan(
        plan,
        strategy_type=body.strategy_type,
        form_symbol=body.form_symbol,
        known_symbols=known_symbols or None,
        holdings=holdings,
        holdings_checked=holdings_checked,
    )
    return result.model_dump()


@router.post("/strategy-plans/preflight")
async def preflight_plan(body: StrategyQueryRequest, db: Session = Depends(get_db)):
    holdings = {}
    known_symbols: set[str] = set()
    if body.client_id:
        from utils.strategy_builder.holdings_preflight import build_holdings_map
        from utils.tms_client_resolver import get_tms_user_for_client

        try:
            tms_user = await get_tms_user_for_client(body.client_id, db)
            holdings = await build_holdings_map(tms_user)
            stock_details = await tms_user.get_stock_details_async()
            for item in stock_details or []:
                symbol = str(item.get("symbol") or item.get("script") or "").strip().upper()
                if symbol:
                    known_symbols.add(symbol)
        except Exception:
            holdings = {}
    from utils.strategy_builder.schedule_preflight import run_schedule_preflight

    return await run_schedule_preflight(
        query_text=body.query_text or None,
        compiled_plan=body.compiled_plan,
        strategy_type=body.strategy_type,
        client_id=body.client_id,
        script_name=body.form_symbol,
        db=db,
        holdings=holdings,
        known_symbols=known_symbols or None,
        capture_reference_ltp=body.capture_reference_ltp,
        drop_percent=body.drop_percent,
        fixed_symbols=body.fixed_symbols,
    )


@router.post("/strategy-plans/preview")
async def preview_plan(body: StrategyQueryRequest, db: Session = Depends(get_db)):
    preview_validation_body = body.model_copy(update={
        "skip_live_checks": True,
        "check_holdings": False,
        "holdings_by_symbol": None,
    })
    validation = await validate_plan(preview_validation_body, db)
    if not validation.get("valid"):
        return validation
    from utils.strategy_builder.preview_service import build_rule_previews
    from utils.strategy_builder.reference_dependencies import plan_uses_reference
    from utils.strategy_builder.strategy_models import StrategyPlanAST

    plan = StrategyPlanAST.model_validate(validation["compiled_plan"])
    validation["preview"] = await build_rule_previews(
        plan,
        client_id=body.client_id,
        db=db,
        preview_references=body.preview_references,
    )
    if plan_uses_reference(plan) and body.client_id and not body.skip_live_checks:
        validation["preview_reference_note"] = (
            "Preview uses live quotes as temporary REFERENCE values per symbol. "
            "Final reference snapshots are captured once at schedule time."
        )
    if body.include_schedule_preflight:
        from utils.strategy_builder.schedule_preflight import run_schedule_preflight

        validation["schedule_preflight"] = await run_schedule_preflight(
            query_text=body.query_text or None,
            compiled_plan=validation["compiled_plan"],
            strategy_type=body.strategy_type,
            client_id=body.client_id,
            script_name=body.form_symbol,
            db=db,
            holdings=body.holdings_by_symbol,
            capture_reference_ltp=body.capture_reference_ltp,
            drop_percent=body.drop_percent,
            fixed_symbols=body.fixed_symbols,
        )
    return validation


@router.post("/strategy-plans/screener-drop/preview")
async def preview_screener_drop_batch(body: ScreenerDropBatchRequest, db: Session = Depends(get_db)):
    from utils.strategy_builder.schedule_baseline import ScheduleBaselineError
    from utils.strategy_builder.screener_drop_schedule import preview_screener_drop_batch as preview_batch

    try:
        return await preview_batch(
            db,
            client_id=body.client_id,
            query_text=body.query_text,
            symbols=body.symbols,
            drop_percent=body.drop_percent,
            expiration=body.expiration,
            expiry_time=body.expiry_time,
            expiry_action=body.expiry_action,
            max_slippage_percent=body.max_allowed_slippage_percent,
            default_qty=body.default_qty,
            per_symbol_qty=body.per_symbol_qty,
        )
    except ScheduleBaselineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Cannot connect to TMS: {exc}") from exc


@router.post("/strategy-plans/screener-drop/commit")
async def commit_screener_drop_batch(body: ScreenerDropCommitRequest, db: Session = Depends(get_db)):
    from utils.strategy_builder.schedule_baseline import ScheduleBaselineError
    from utils.strategy_builder.screener_drop_schedule import commit_screener_drop_batch as commit_batch

    try:
        return await commit_batch(
            db,
            client_id=body.client_id,
            query_text=body.query_text,
            symbols=body.symbols,
            drop_percent=body.drop_percent,
            expiration=body.expiration,
            expiry_time=body.expiry_time,
            expiry_action=body.expiry_action,
            strategy_type=body.strategy_type,
            default_qty=body.default_qty,
            per_symbol_qty=body.per_symbol_qty,
            max_slippage_percent=body.max_allowed_slippage_percent,
            odd_lot_allowed=body.odd_lot_allowed,
            security_details_by_symbol=body.security_details_by_symbol,
        )
    except ScheduleBaselineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/strategy-plans/schedule-batch")
async def schedule_custom_query_batch(
    body: CustomQueryBatchScheduleRequest,
    background_tasks: BackgroundTasks,
):
    from utils.strategy_builder.custom_query_batch_schedule import (
        CustomQueryBatchError,
        run_custom_query_batch_safe,
    )

    try:
        symbols = [str(item).strip().upper() for item in body.symbols if str(item).strip()]
        if not symbols:
            raise CustomQueryBatchError("At least one symbol is required.")
        payload = body.model_dump()
        background_tasks.add_task(run_custom_query_batch_safe, payload)
        return {
            "status": "accepted",
            "symbol_count": len(symbols),
            "message": (
                f"Scheduling {len(symbols)} order(s) in parallel on the server. "
                "You can close this page; orders will appear in Order Logs when finished."
            ),
        }
    except CustomQueryBatchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/strategy-plans/schedule-batch/wait")
async def schedule_custom_query_batch_wait(body: CustomQueryBatchScheduleRequest):
    """Synchronous batch schedule — used by tests and optional blocking clients."""
    from utils.strategy_builder.custom_query_batch_schedule import (
        CustomQueryBatchError,
        run_custom_query_batch,
    )

    try:
        return await run_custom_query_batch(body.model_dump())
    except CustomQueryBatchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/strategy-plans")
async def create_plan(body: StrategyPlanCreateRequest, db: Session = Depends(get_db)):
    from models.strategy_plan import StrategyPlan, StrategyRule, StrategyTarget

    validation_response = await validate_plan(body, db)
    if not validation_response.get("valid"):
        raise HTTPException(status_code=400, detail=validation_response)
    plan_ast = validation_response["compiled_plan"]
    row = StrategyPlan(
        user_id=body.user_id or body.client_id,
        client_id=body.client_id,
        name=body.name,
        side=plan_ast["side"],
        strategy_type=body.strategy_type or f"Custom Query {plan_ast['side'].title()}",
        rule_source="custom_query" if "Custom Query" in (body.strategy_type or "") else "technical_gui",
        query_text=body.query_text,
        query_version=plan_ast.get("version", 1),
        compiled_plan=plan_ast,
        status="draft",
        execution_mode=body.execution_mode,
        portfolio_limits=plan_ast.get("portfolio_limits"),
        form_symbol=body.form_symbol,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    for rule in plan_ast.get("rules", []):
        rule_row = StrategyRule(
            plan_id=row.id,
            rule_name=rule["name"],
            rule_ast=rule.get("when"),
            order_config=rule.get("order"),
            confirmation_config=rule.get("confirmation"),
            execution_config=rule.get("execution"),
        )
        db.add(rule_row)
        db.commit()
        db.refresh(rule_row)
        for symbol in rule.get("symbols", []):
            db.add(
                StrategyTarget(
                    plan_id=row.id,
                    rule_id=rule_row.id,
                    symbol=symbol.upper(),
                    status="MONITORING",
                )
            )
    db.commit()
    return {"id": row.id, "status": row.status, "validation": validation_response}
