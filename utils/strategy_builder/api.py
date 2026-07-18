from __future__ import annotations

import asyncio
import json
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from schemas.schemas import OrderCreateRequest
from utils.strategy_builder.strategy_fields import get_field_catalog, get_supported_functions
from utils.strategy_builder.strategy_parser import StrategyQueryError, extract_symbols_from_query, format_strategy_query, parse_strategy_query
from utils.strategy_builder.strategy_validator import validate_strategy_plan
from utils.strategy_builder.strategy_llm_prompt import build_strategy_query_copy_prompt
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
    holdings_by_symbol: Optional[Dict[str, int]] = None
    known_symbols: Optional[List[str]] = None


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
    holdings_by_symbol: Optional[Dict[str, int]] = None
    skip_preflight: bool = False


class BacktestRequest(BaseModel):
    symbol: str
    query_text: str
    start_date: date
    end_date: date
    initial_capital: float = Field(default=100000, gt=0)
    charge_model: str = Field(default="nepse_equity", pattern="^(nepse_equity|nepse_equity_v2024_05_14|legacy_flat)$")
    investor_type: str = Field(default="individual", pattern="^(individual|institution|other)$")
    apply_cgt: bool = True
    dp_charge: float = Field(default=25, ge=0)
    stop_loss_pct: float = Field(default=5, gt=0, le=100)
    take_profit_pct: float = Field(default=10, gt=0, le=500)
    min_holding_days: int = Field(default=0, ge=0, le=365)
    max_holding_days: int = Field(default=20, ge=1, le=365)
    fee_pct: float = Field(default=0.4, ge=0, le=10)
    fixed_fee: float = Field(default=0, ge=0)
    slippage_pct: float = Field(default=0.1, ge=0, le=10)
    position_size_pct: float = Field(default=100, gt=0, le=100)
    trailing_stop_pct: Optional[float] = Field(default=None, gt=0, le=100)
    max_volume_participation_pct: float = Field(default=10, gt=0, le=100)
    risk_free_rate_pct: float = Field(default=4, ge=0, le=100)
    data_source: str = "auto"


class BacktestBatchRequest(BaseModel):
    start_date: date
    end_date: date
    preset_ids: Optional[List[str]] = None
    symbols: Optional[List[str]] = None
    data_source: str = "combined"
    max_workers: int = Field(default=8, ge=1, le=12)
    initial_capital: float = Field(default=100000, gt=0)
    charge_model: str = Field(default="nepse_equity", pattern="^(nepse_equity|nepse_equity_v2024_05_14|legacy_flat)$")
    investor_type: str = Field(default="individual", pattern="^(individual|institution|other)$")
    apply_cgt: bool = True
    dp_charge: float = Field(default=25, ge=0)
    fee_pct: float = Field(default=0.4, ge=0, le=10)
    fixed_fee: float = Field(default=0, ge=0)
    slippage_pct: float = Field(default=0.1, ge=0, le=10)
    position_size_pct: float = Field(default=100, gt=0, le=100)
    min_holding_days: int = Field(default=0, ge=0, le=365)
    max_holding_days: Optional[int] = Field(default=None, ge=1, le=365)
    trailing_stop_pct: Optional[float] = Field(default=None, gt=0, le=100)
    max_volume_participation_pct: float = Field(default=10, gt=0, le=100)
    risk_free_rate_pct: float = Field(default=4, ge=0, le=100)
    ordinary_shares_only: bool = True
    max_listing_age_days: Optional[int] = Field(default=None, ge=1, le=36500)
    min_volume: Optional[float] = Field(default=None, ge=0)


class BacktestAnalysisAskRequest(BaseModel):
    message: str = Field(min_length=2, max_length=1000)
    symbol: Optional[str] = None
    include_non_equities: bool = False
    max_listing_age_days: Optional[int] = Field(default=None, ge=1, le=36500)
    min_volume: Optional[float] = Field(default=None, ge=0)
    manual_filters: List[Dict[str, Any]] = Field(default_factory=list, max_length=30)


class BacktestV2RunRequest(BacktestBatchRequest):
    name: str = Field(default="NEPSE market research", min_length=2, max_length=200)
    notes: Optional[str] = Field(default=None, max_length=4000)
    run_type: str = Field(default="market_scan", pattern="^(single_stock|market_scan|portfolio)$")
    portfolio: Dict[str, Any] = Field(default_factory=dict)
    strategy_mode: str = Field(default="presets", pattern="^(presets|custom)$")
    custom_query_text: Optional[str] = Field(default=None, min_length=20, max_length=50000)


class BacktestV2ResultQuery(BaseModel):
    filters: Dict[str, Any] = Field(default_factory=lambda: {"join": "and", "conditions": []})
    include_non_equities: bool = False
    sort_by: str = "robust_score"
    sort_direction: str = Field(default="desc", pattern="^(asc|desc)$")
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=100, ge=1, le=100)


class BacktestV2AiQueryRequest(BacktestAnalysisAskRequest):
    include_non_equities: bool = False


class BacktestV2StrategyDraftRequest(BaseModel):
    message: str = Field(min_length=2, max_length=4000)
    side: str = Field(default="buy", pattern="^(buy|sell)$")
    symbol: Optional[str] = None


class BacktestV2CloneRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=200)


class BacktestV2PromoteRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=100)
    name: Optional[str] = Field(default=None, min_length=2, max_length=200)


class BacktestV2SortItem(BaseModel):
    field: str = Field(min_length=1, max_length=80)
    direction: str = Field(default="desc", pattern="^(asc|desc)$")


class BacktestV2StrongBuyQuery(BaseModel):
    minimum_trades: int = Field(default=5, ge=0)
    minimum_win_rate: float = Field(default=0, ge=0, le=100)
    minimum_confidence: float = Field(default=0, ge=0, le=100)
    minimum_sharpe: float = -999
    minimum_profit_factor: float = Field(default=0, ge=0)
    maximum_drawdown: float = Field(default=100, ge=0, le=100)
    minimum_return: float = 0
    minimum_volume: Optional[float] = Field(default=None, ge=0)
    category: Optional[str] = None
    current_signal: str = Field(default="all", pattern="^(all|triggered_today|near_trigger|strong_buy|buy|watch|no_signal)$")
    latest_signal_date: Optional[date] = None
    include_non_equities: bool = False
    sort_by: str = "recommendation_score"
    sort_direction: str = Field(default="desc", pattern="^(asc|desc)$")
    sorts: List[BacktestV2SortItem] = Field(default_factory=list, max_length=8)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=25, ge=1, le=100)


def _append_ai_symbol_context(message: str, known_symbols: Optional[List[str]], form_symbol: Optional[str]) -> str:
    symbols: List[str] = []
    seen: set[str] = set()
    for symbol in known_symbols or []:
        clean = str(symbol or "").strip().upper()
        if clean and clean not in seen:
            seen.add(clean)
            symbols.append(clean)
    if not symbols:
        return message

    shown = symbols[:100]
    lines = [
        message.rstrip(),
        "",
        "Available symbol universe for this order form:",
        ", ".join(f'"{symbol}"' for symbol in shown),
    ]
    if len(symbols) > len(shown):
        lines.append(f"(Only the first {len(shown)} symbols are shown from {len(symbols)} available symbols.)")
    if form_symbol:
        lines.append(f'Current form symbol: "{str(form_symbol).strip().upper()}".')
    lines.extend(
        [
            "If the user asks for top N / best N / N NEPSE stocks, use FOR SYMBOL IN with this available universe and RANK MATCHES BY ... LIMIT N ORDERS.",
            "Do not collapse a top-N request to only the current form symbol when this universe is available.",
        ]
    )
    return "\n".join(lines)


@router.get("/strategy-builder/fields")
async def strategy_builder_fields():
    return {"fields": get_field_catalog(), "functions": get_supported_functions()}


@router.post("/backtests/v2/runs", status_code=202)
async def create_backtest_v2_run(body: BacktestV2RunRequest):
    from utils.backtesting.v2_jobs import create_run
    try:
        return await run_in_threadpool(create_run, body.model_dump(), owner_id="local")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/backtests/v2/runs")
async def list_backtest_v2_runs(page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100)):
    from utils.backtesting.v2_jobs import list_runs
    return await run_in_threadpool(list_runs, owner_id="local", page=page, page_size=page_size)


@router.get("/backtests/v2/runs/{run_id}")
async def read_backtest_v2_run(run_id: str):
    from utils.backtesting.v2_jobs import get_run
    try:
        return await run_in_threadpool(get_run, run_id, owner_id="local")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/backtests/v2/runs/{run_id}/events")
async def stream_backtest_v2_events(run_id: str):
    from utils.backtesting.v2_jobs import get_run
    from database import SessionLocal
    from utils.backtesting.v2_query import query_results

    async def events():
        last_payload = ""
        while True:
            try:
                run = await run_in_threadpool(get_run, run_id, owner_id="local")
                session = SessionLocal()
                try:
                    leaders = query_results(session, run_id, {"page_size": 10, "sort_by": "robust_score"})["items"]
                finally:
                    session.close()
                payload = json.dumps({"type": "progress", "run": run, "partial_leaders": leaders}, default=str)
                if payload != last_payload:
                    yield f"data: {payload}\n\n"
                    last_payload = payload
                if run["status"] in {"completed", "failed", "cancelled"}:
                    break
            except Exception as exc:
                yield f"event: error\ndata: {json.dumps({'detail': str(exc)})}\n\n"
                break
            await asyncio.sleep(1)
    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def _control_backtest_v2_run(run_id: str, action: str):
    from utils.backtesting.v2_jobs import retry_failed_symbols, set_run_control
    try:
        if action == "retry":
            return await run_in_threadpool(retry_failed_symbols, run_id, owner_id="local")
        return await run_in_threadpool(set_run_control, run_id, action, owner_id="local")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/backtests/v2/runs/{run_id}/cancel")
async def cancel_backtest_v2_run(run_id: str):
    return await _control_backtest_v2_run(run_id, "cancel")


@router.post("/backtests/v2/runs/{run_id}/pause")
async def pause_backtest_v2_run(run_id: str):
    return await _control_backtest_v2_run(run_id, "pause")


@router.post("/backtests/v2/runs/{run_id}/resume")
async def resume_backtest_v2_run(run_id: str):
    return await _control_backtest_v2_run(run_id, "resume")


@router.post("/backtests/v2/runs/{run_id}/retry")
async def retry_backtest_v2_run(run_id: str):
    return await _control_backtest_v2_run(run_id, "retry")


@router.post("/backtests/v2/runs/{run_id}/clone-with-name", status_code=202)
async def clone_backtest_v2_run(run_id: str, body: BacktestV2CloneRequest):
    from utils.backtesting.v2_jobs import clone_run
    try:
        return await run_in_threadpool(clone_run, run_id, owner_id="local", name=body.name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/backtests/v2/results/fields")
async def backtest_v2_result_fields():
    from utils.backtesting.v2_query import field_catalog
    return {"fields": field_catalog(), "ordinary_shares_default": True}


@router.get("/backtests/v2/symbols")
async def search_backtest_v2_symbols(search: str = "", include_non_equities: bool = False, db: Session = Depends(get_db)):
    from sqlalchemy import text
    needle = f"%{search.strip()}%"
    universe = "TRUE" if include_non_equities else "combined_data->>'security_type'='ordinary_share'"
    rows = db.execute(text(f"""
        SELECT symbol,
               COALESCE(combined_data->>'company_name',combined_data->>'name',combined_data->>'companyName',symbol) company_name,
               combined_data->>'security_type' security_type,
               COALESCE(combined_data->>'sector',combined_data->>'ml_sector') sector
        FROM market_screener_cache
        WHERE {universe} AND (:search='%%' OR symbol ILIKE :search
              OR COALESCE(combined_data->>'company_name',combined_data->>'name',combined_data->>'companyName','') ILIKE :search)
        ORDER BY CASE WHEN symbol ILIKE :search THEN 0 ELSE 1 END,symbol LIMIT 20
    """), {"search": needle}).mappings().all()
    return {"items": [dict(row) for row in rows], "ordinary_shares_default": not include_non_equities}


@router.post("/backtests/v2/runs/{run_id}/results/query")
async def query_backtest_v2_results(run_id: str, body: BacktestV2ResultQuery, db: Session = Depends(get_db)):
    from utils.backtesting.v2_query import ResultQueryError, query_results
    try:
        return query_results(db, run_id, body.model_dump(), owner_id="local")
    except ResultQueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/backtests/v2/runs/{run_id}/strong-buys/query")
async def query_backtest_v2_strong_buys(run_id: str, body: BacktestV2StrongBuyQuery, db: Session = Depends(get_db)):
    from utils.backtesting.v2_query import ResultQueryError, query_strong_buys
    try:
        payload = body.model_dump(mode="json")
        return query_strong_buys(db, run_id, payload, owner_id="local")
    except ResultQueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/backtests/v2/runs/{run_id}/strong-buys/{symbol}")
async def read_backtest_v2_strong_buy_stock(
    run_id: str, symbol: str, result_id: Optional[int] = Query(None, ge=1), db: Session = Depends(get_db),
):
    from sqlalchemy import text
    rows = db.execute(text(
        """SELECT r.result_id,r.symbol,r.preset_id,r.preset_name,r.category,r.current_signal_status,
                  r.current_signal_date,r.reliability_score,r.current_technical_score,r.current_evidence,
                  r.total_trades,r.wins,r.losses,r.win_rate_pct,r.confidence_score,r.net_return_pct,
                  r.max_drawdown_pct,r.sharpe_ratio,r.sortino_ratio,r.profit_factor,r.expectancy_pct,
                  r.assumptions,r.warning_codes,s.ltp,s.latest_volume,s.sector
           FROM backtest_results r JOIN backtest_runs br ON br.run_id=r.run_id
           JOIN backtest_run_symbols s ON s.run_id=r.run_id AND s.symbol=r.symbol
           WHERE r.run_id=:run_id AND br.owner_id='local' AND br.deleted_at IS NULL AND r.symbol=:symbol
           ORDER BY CASE WHEN r.result_id=:result_id THEN 0 ELSE 1 END,
                    r.current_signal_active DESC,r.reliability_score DESC,r.robust_score DESC"""
    ), {"run_id": run_id, "symbol": symbol.strip().upper(), "result_id": result_id or -1}).mappings().all()
    if not rows:
        raise HTTPException(status_code=404, detail="No saved backtest strategy was found for this stock.")
    return {"best": dict(rows[0]), "alternatives": [dict(row) for row in rows[1:]],
            "disclaimer": "Backtested historical performance does not guarantee future results."}


@router.get("/backtests/v2/results/{result_id}")
async def read_backtest_v2_result(result_id: int, db: Session = Depends(get_db)):
    from utils.backtesting.v2_query import ResultQueryError, result_detail
    try:
        return result_detail(db, result_id, owner_id="local")
    except ResultQueryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/backtests/v2/results/{result_id}/trades")
async def read_backtest_v2_result_trades(
    result_id: int, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100),
    result_filter: str = Query("all", pattern="^(all|wins|losses|stop_loss|take_profit)$"),
    start_date: Optional[date] = None, end_date: Optional[date] = None, db: Session = Depends(get_db),
):
    from utils.backtesting.v2_query import ResultQueryError, result_detail, result_trades
    try:
        detail = result_detail(db, result_id, owner_id="local")
    except ResultQueryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    trades = result_trades(db, result_id, owner_id="local")
    equity = float((detail.get("assumptions") or {}).get("initial_capital") or 100000)
    peak = equity
    for trade in trades:
        equity += float(trade.get("pnl") or 0)
        peak = max(peak, equity)
        trade["result"] = "win" if float(trade.get("pnl") or 0) > 0 else "loss" if float(trade.get("pnl") or 0) < 0 else "break_even"
        trade["gross_return_pct"] = round((float(trade["exit_price"]) / float(trade["entry_price"]) - 1) * 100, 2)
        trade["net_return_pct"] = trade["return_pct"]
        trade["running_equity"] = round(equity, 2)
        trade["drawdown_after_trade_pct"] = round((peak - equity) / peak * 100, 2) if peak else 0
    filtered = [trade for trade in trades if (
        (result_filter == "all" or result_filter == "wins" and trade["result"] == "win"
         or result_filter == "losses" and trade["result"] == "loss"
         or result_filter in {"stop_loss", "take_profit"} and trade.get("exit_reason") == result_filter)
        and (start_date is None or trade["entry_date"] >= start_date.isoformat())
        and (end_date is None or trade["exit_date"] <= end_date.isoformat())
    )]
    offset = (page - 1) * page_size
    return {"items": filtered[offset:offset + page_size], "page": page, "page_size": page_size,
            "total": len(filtered), "pages": (len(filtered) + page_size - 1) // page_size}


@router.get("/backtests/v2/results/{result_id}/chart")
async def read_backtest_v2_result_chart(result_id: int, db: Session = Depends(get_db)):
    from utils.backtesting.v2_query import ResultQueryError, result_detail, result_trades
    try:
        detail = result_detail(db, result_id, owner_id="local")
    except ResultQueryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    trades = result_trades(db, result_id, owner_id="local")
    capital = float((detail.get("assumptions") or {}).get("initial_capital") or 100000)
    equity = capital
    curve = []
    for trade in trades:
        equity += float(trade.get("pnl") or 0)
        curve.append({"date": trade["exit_date"], "equity": round(equity, 2), "trade_return_pct": trade["return_pct"]})
    return {"symbol": detail["symbol"], "equity_curve": curve, "trades": trades}


@router.get("/backtests/v2/results/{result_id}/robustness")
async def read_backtest_v2_result_robustness(result_id: int, db: Session = Depends(get_db)):
    from utils.backtesting.monte_carlo import block_bootstrap
    from utils.backtesting.v2_query import result_trades
    trades = result_trades(db, result_id, owner_id="local")
    return block_bootstrap([float(trade["return_pct"]) for trade in trades], samples=1000, block_size=5, seed=result_id)


@router.post("/backtests/v2/results/{result_id}/promote-to-paper", status_code=201)
async def promote_backtest_v2_result_to_paper(result_id: int, body: BacktestV2PromoteRequest, db: Session = Depends(get_db)):
    from models.strategy_plan import StrategyPlan
    from utils.backtesting.presets import build_preset_query, get_backtest_presets
    from utils.backtesting.v2_query import ResultQueryError, result_detail
    from utils.strategy_builder.strategy_parser import retarget_strategy_query
    try:
        detail = result_detail(db, result_id, owner_id="local")
    except ResultQueryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    assumptions = detail.get("assumptions") or {}
    persisted_query = assumptions.get("strategy_query") or assumptions.get("strategy_query_template")
    if persisted_query:
        try:
            query_text = retarget_strategy_query(str(persisted_query), [detail["symbol"]])
        except StrategyQueryError as exc:
            raise HTTPException(status_code=409, detail=f"The saved strategy query is no longer valid: {exc}") from exc
    else:
        preset = next((item for item in get_backtest_presets() if item["id"] == detail["preset_id"]), None)
        if not preset:
            raise HTTPException(status_code=409, detail="The source strategy version is no longer available.")
        query_text = build_preset_query(preset, detail["symbol"])
    created = await create_plan(StrategyPlanCreateRequest(
        name=body.name or f"Paper · {detail['symbol']} · {detail['preset_name']}", client_id=body.client_id,
        user_id=body.client_id, execution_mode="paper", strategy_type="Custom Query Backtest Paper Candidate",
        query_text=query_text, form_symbol=detail["symbol"], skip_live_checks=True,
    ), db)
    plan = db.query(StrategyPlan).filter(StrategyPlan.id == created["id"]).one()
    plan.portfolio_limits = {
        **(plan.portfolio_limits or {}), "source_backtest_run_id": detail["run_id"],
        "source_backtest_result_id": result_id, "engine_version": "nepse-daily-v2",
        "robust_score": detail["robust_score"], "selected_symbols": [detail["symbol"]],
        "strategy_source_hash": assumptions.get("preset_source_hash"),
    }
    db.commit()
    return {**created, "execution_mode": "paper", "activation_required": True,
            "query_text": query_text, "same_query_for_execution": True,
            "live_requires_separate_confirmation": True,
            "message": "The exact backtested query was created as a paper draft. Live execution requires separate account, holdings, balance, and risk confirmation."}


@router.get("/backtests/v2/runs/{run_id}/portfolios")
async def read_backtest_v2_portfolios(run_id: str, db: Session = Depends(get_db)):
    from sqlalchemy import text
    rows = db.execute(text(
        """SELECT p.preset_id,p.preset_name,p.summary,p.equity_curve,p.allocation_config
           FROM backtest_portfolio_results p JOIN backtest_runs r ON r.run_id=p.run_id
           WHERE p.run_id=:run_id AND r.owner_id='local' ORDER BY (p.summary->>'net_return_pct')::double precision DESC"""
    ), {"run_id": run_id}).mappings().all()
    return {"items": [dict(row) for row in rows]}


@router.post("/backtests/v2/runs/{run_id}/ai-query")
async def ask_backtest_v2_ai(run_id: str, body: BacktestV2AiQueryRequest, db: Session = Depends(get_db)):
    from sqlalchemy import text
    from utils.backtesting.ai_analysis import build_plan_prompt, compile_display_query, parse_plan
    from utils.backtesting.v2_query import ResultQueryError, query_results
    from utils.llm_chat import LlmChatError, call_llm_chat
    try:
        system, prompt = build_plan_prompt(body.message, symbol=body.symbol)
        raw, provider = await run_in_threadpool(call_llm_chat, system, prompt)
        plan = parse_plan(raw, symbol=body.symbol, ordinary_only=not body.include_non_equities,
                          max_listing_age_days=body.max_listing_age_days, min_volume=body.min_volume,
                          extra_filters=body.manual_filters)
        query = {"filters": {"join": "and", "conditions": plan["filters"]}, "include_non_equities": body.include_non_equities,
                 "sort_by": plan["sort_by"], "sort_direction": plan["sort_direction"], "page": 1, "page_size": 10}
        results = query_results(db, run_id, query, owner_id="local")
        audit = {"filters": plan["filters"], "sort_by": plan["sort_by"], "sort_direction": plan["sort_direction"]}
        db.execute(text(
            """INSERT INTO backtest_ai_audits(run_id,owner_id,action,provider,prompt_version,user_message,generated_plan,validation_result)
               VALUES (:run_id,'local','result_query',:provider,'backtest-result-query-v2',:message,CAST(:plan AS JSONB),CAST(:validation AS JSONB))"""
        ), {"run_id": run_id, "provider": provider, "message": body.message, "plan": json.dumps(audit),
            "validation": json.dumps({"valid": True, "matches": results["total"]})})
        db.commit()
        return {"generated_query": compile_display_query(plan), "validated_plan": audit, "explanation": plan["explanation"],
                "items": results["items"], "matches_returned": len(results["items"]), "total_matches": results["total"],
                "suggested_relaxations": [] if results["total"] else ["Reduce the minimum trade count or robust-score threshold.", "Broaden the selected sector or listing-age range."],
                "note": "Explicit filters were preserved. No generated SQL was executed."}
    except LlmChatError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (ValueError, ResultQueryError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/backtests/v2/strategies/draft")
async def draft_backtest_v2_strategy(body: BacktestV2StrategyDraftRequest, db: Session = Depends(get_db)):
    request = StrategyAiGenerateRequest(message=body.message, side=body.side, form_symbol=body.symbol)
    result = await generate_strategy_query(request, db)
    query_v2 = result["generated_query"].replace("STRATEGY_VERSION 1", "STRATEGY_VERSION 2", 1)
    plan_v2 = parse_strategy_query(query_v2)
    validation_v2 = validate_strategy_plan(plan_v2, strategy_type="Backtest Research Draft", form_symbol=body.symbol)
    result["generated_query"] = format_strategy_query(plan_v2)
    result["compiled_plan"] = plan_v2.model_dump()
    result["validation"] = validation_v2.model_dump()
    result["draft_only"] = True
    result["next_action"] = "Review the language and explicitly run a backtest. This draft cannot place or schedule orders."
    return result


@router.post("/backtest/run")
async def run_strategy_backtest(body: BacktestRequest):
    from utils.backtesting.service import BacktestError, run_backtest

    try:
        return await run_in_threadpool(
            run_backtest,
            symbol=body.symbol,
            query_text=body.query_text,
            start_date=body.start_date,
            end_date=body.end_date,
            initial_capital=body.initial_capital,
            charge_model=body.charge_model,
            investor_type=body.investor_type,
            apply_cgt=body.apply_cgt,
            dp_charge=body.dp_charge,
            stop_loss_pct=body.stop_loss_pct,
            take_profit_pct=body.take_profit_pct,
            min_holding_days=body.min_holding_days,
            max_holding_days=body.max_holding_days,
            fee_pct=body.fee_pct,
            fixed_fee=body.fixed_fee,
            slippage_pct=body.slippage_pct,
            position_size_pct=body.position_size_pct,
            trailing_stop_pct=body.trailing_stop_pct,
            max_volume_participation_pct=body.max_volume_participation_pct,
            risk_free_rate_pct=body.risk_free_rate_pct,
            data_source=body.data_source,
        )
    except BacktestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/backtest/presets")
async def list_backtest_presets():
    from utils.backtesting.presets import get_backtest_presets

    presets = get_backtest_presets()
    return {"presets": presets, "count": len(presets)}


@router.get("/technical-indicators/refresh")
async def technical_indicator_refresh_status():
    from utils.technical_indicators.refresh import get_indicator_refresh_status
    return await run_in_threadpool(get_indicator_refresh_status)


@router.post("/technical-indicators/refresh", status_code=202)
async def start_technical_indicator_refresh():
    from utils.technical_indicators.refresh import get_indicator_refresh_status, start_indicator_refresh_background
    started = start_indicator_refresh_background()
    return {"started": started, **await run_in_threadpool(get_indicator_refresh_status)}


@router.get("/backtest/gpt-prompt")
async def get_backtest_gpt_prompt(symbol: str = "NABIL"):
    from utils.backtesting.presets import build_backtest_gpt_prompt

    return {"prompt": build_backtest_gpt_prompt(symbol)}


@router.post("/backtest/batch")
async def run_batch_backtest(body: BacktestBatchRequest):
    from utils.backtesting.batch import run_market_batch_backtest
    from utils.backtesting.service import BacktestError

    try:
        return await run_in_threadpool(
            run_market_batch_backtest,
            start_date=body.start_date, end_date=body.end_date,
            preset_ids=body.preset_ids, symbols=body.symbols,
            data_source=body.data_source, max_workers=body.max_workers,
            initial_capital=body.initial_capital, fee_pct=body.fee_pct,
            charge_model=body.charge_model, investor_type=body.investor_type,
            apply_cgt=body.apply_cgt, dp_charge=body.dp_charge,
            fixed_fee=body.fixed_fee, slippage_pct=body.slippage_pct,
            position_size_pct=body.position_size_pct,
            min_holding_days=body.min_holding_days,
            max_holding_days=body.max_holding_days,
            trailing_stop_pct=body.trailing_stop_pct,
            max_volume_participation_pct=body.max_volume_participation_pct,
            risk_free_rate_pct=body.risk_free_rate_pct,
            ordinary_shares_only=body.ordinary_shares_only,
            max_listing_age_days=body.max_listing_age_days,
            min_volume=body.min_volume,
        )
    except BacktestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/backtest/batch/jobs", status_code=202)
async def start_batch_backtest_job(body: BacktestBatchRequest, background_tasks: BackgroundTasks):
    """Start a long all-stock scan without holding the browser request open."""
    from utils.backtesting.jobs import create_batch_job, run_batch_job
    from utils.backtesting.service import BacktestError

    parameters = body.model_dump()
    try:
        job = create_batch_job(parameters)
    except BacktestError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    background_tasks.add_task(run_batch_job, job["job_id"], parameters)
    return job


@router.get("/backtest/batch/jobs")
async def list_batch_backtest_jobs():
    from utils.backtesting.jobs import list_batch_jobs

    return {"jobs": await run_in_threadpool(list_batch_jobs)}


@router.get("/backtest/batch/jobs/{job_id}")
async def read_batch_backtest_job(job_id: str):
    from utils.backtesting.jobs import get_batch_job
    from utils.backtesting.service import BacktestError

    try:
        return await run_in_threadpool(get_batch_job, job_id)
    except BacktestError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/backtest/batch/jobs/{job_id}/symbols/{symbol}")
async def read_batch_backtest_job_symbol(job_id: str, symbol: str):
    from utils.backtesting.jobs import get_batch_job_symbol
    from utils.backtesting.service import BacktestError
    try:
        return await run_in_threadpool(get_batch_job_symbol, job_id, symbol)
    except BacktestError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/backtest/batch/jobs/{job_id}/ask")
async def ask_batch_backtest_analysis(job_id: str, body: BacktestAnalysisAskRequest):
    """Generate, validate, and execute a structured plan over stored rows."""
    import re
    from utils.backtesting.ai_analysis import (
        build_plan_prompt, compile_display_query, execute_plan, parse_plan,
    )
    from utils.backtesting.jobs import get_batch_job_rankings
    from utils.llm_chat import LlmChatError, call_llm_chat
    try:
        rows = await run_in_threadpool(get_batch_job_rankings, job_id)
        system, prompt = build_plan_prompt(body.message, symbol=body.symbol)
        raw_plan, provider = await run_in_threadpool(call_llm_chat, system, prompt)
        wants_non_equities = body.include_non_equities or bool(re.search(r"\b(all instruments?|mutual funds?|debentures?|bonds?)\b", body.message, re.IGNORECASE))
        plan = parse_plan(
            raw_plan, symbol=body.symbol, ordinary_only=not wants_non_equities,
            max_listing_age_days=body.max_listing_age_days,
            min_volume=body.min_volume,
            extra_filters=body.manual_filters,
        )
        results = execute_plan(rows, plan)
        if not results:
            retry_prompt = prompt + "\nThe first validated plan matched zero stored rows. Return a broader JSON plan: keep explicit user limits, but relax inferred thresholds so useful matches are likely."
            retry_raw, retry_provider = await run_in_threadpool(call_llm_chat, system, retry_prompt)
            retry_plan = parse_plan(
                retry_raw, symbol=body.symbol, ordinary_only=not wants_non_equities,
                max_listing_age_days=body.max_listing_age_days, min_volume=body.min_volume,
                extra_filters=body.manual_filters,
            )
            retry_results = execute_plan(rows, retry_plan)
            if retry_results:
                plan, results, provider = retry_plan, retry_results, retry_provider
        return {
            "generated_query": compile_display_query(plan),
            "explanation": plan["explanation"], "results": results,
            "provider": provider, "rows_analyzed": len(rows), "matches_returned": len(results),
            "note": "Validated structured plan; no AI-generated SQL was executed directly. Simulations are not financial advice.",
        }
    except LlmChatError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/backtest/batch/jobs/{job_id}", status_code=204)
async def remove_batch_backtest_job(job_id: str):
    from utils.backtesting.jobs import delete_batch_job
    from utils.backtesting.service import BacktestError

    try:
        await run_in_threadpool(delete_batch_job, job_id)
    except BacktestError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/strategy-builder/strategies")
async def strategy_builder_strategies(side: Optional[str] = None):
    from utils.strategies.strategy_query_catalog import get_delegatable_strategies

    return {"strategies": get_delegatable_strategies(side)}


@router.get("/strategy-builder/functions")
async def strategy_builder_functions():
    return {"functions": get_supported_functions()}


@router.get("/strategy-builder/llm-prompt")
async def strategy_builder_llm_prompt(side: str = "buy", form_symbol: Optional[str] = None):
    return {"prompt": build_strategy_query_copy_prompt(side=side, form_symbol=form_symbol)}


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
async def generate_strategy_query(body: StrategyAiGenerateRequest, db: Session = Depends(get_db)):
    message = (body.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required.")
    if body.current_query and body.current_query.strip():
        message = (
            f"{message.strip()}\n\n"
            f"Refine or replace this draft query if helpful:\n```\n{body.current_query.strip()}\n```"
        )
    message = _append_ai_symbol_context(message, body.known_symbols, body.form_symbol)
    try:
        return await execute_strategy_query_ai_with_retries(
            message,
            side=body.side,
            form_symbol=body.form_symbol,
            strategy_type=body.strategy_type,
            client_id=body.client_id,
            db=db,
            holdings_by_symbol=body.holdings_by_symbol,
            known_symbols=body.known_symbols,
            require_schedule_preflight=False,
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
                "ai_attempts": getattr(exc, "ai_attempts", None),
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
    preview_holdings = body.holdings_by_symbol
    holdings_failed = False
    if plan.side == "SELL" and body.client_id and not preview_holdings:
        preview_holdings, holdings_checked = await _resolve_validate_holdings(
            body.model_copy(update={"check_holdings": True}),
            db,
        )
        holdings_failed = not holdings_checked
    validation["preview"] = await build_rule_previews(
        plan,
        client_id=body.client_id,
        db=db,
        preview_references=body.preview_references,
        holdings_by_symbol=preview_holdings,
        holding_retrieval_failed=holdings_failed,
    )
    from utils.strategy_builder.schedule_preview_capture import (
        _snapshot_missing_trigger,
        capture_batch_preview_snapshots,
        snapshots_from_preview_rows,
    )

    preview_snapshots = snapshots_from_preview_rows(validation["preview"])
    missing_trigger_symbols = [
        symbol
        for symbol, snapshot in preview_snapshots.items()
        if _snapshot_missing_trigger(snapshot)
    ]
    if missing_trigger_symbols and body.client_id:
        retry_request = OrderCreateRequest(
            client_id=body.client_id,
            script_name=missing_trigger_symbols[0],
            order_type=str(plan.side or body.side or "buy").lower(),
            price=0,
            qty=0,
            status="pending",
            strategy_type=body.strategy_type,
            strategy_config={"compiled_plan": validation["compiled_plan"]},
        )
        retried = await capture_batch_preview_snapshots(
            retry_request,
            db,
            missing_trigger_symbols,
            holdings_by_symbol=preview_holdings,
            holding_retrieval_failed=holdings_failed,
        )
        preview_snapshots.update(retried)
    validation["schedule_preview_snapshots_by_symbol"] = preview_snapshots
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
