import logging
import json
import os
import re
import uuid
import aiohttp
import time as monotonic_time
from pathlib import Path
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import asyncio
import sys
from typing import Dict, List, Optional, Type
from fastapi import FastAPI, HTTPException, Depends, Query, WebSocket, WebSocketDisconnect, Body
from fastapi.responses import FileResponse, JSONResponse
import websockets
from database import SessionLocal, ensure_performance_indexes, ensure_read_session, get_db, get_db_session
from sqlalchemy import cast, DateTime, or_, and_, text
from exceptions.login_exceptions import LoginFailedException
from models.frontend_user import FrontendUser
from models.logged_in_user import LoggedInUsers
from models.order_log import OrderLog
from models.scheduled_order import ScheduledOrder
from models.order_status_log import OrderStatusLog
from models.user import User
from schemas.schemas import (
    LoginRequest,
    OrderCreateRequest,
    StockGrabberFetchTestRequest,
    StockGrabberRequest,
    StockScreenerAiRequest,
    StockScreenerRequest,
    TmsAccountCreate,
    TmsAccountUpdate,
    UserLogin,
)
from utils.base_functions import is_within_time_range, truncate_to_one_decimal_place
from utils.base_functions import summarize_login_message, get_persisted_collateral
from utils.lot_size import get_board_lot_size, is_regular_lot_qty, normalize_sell_qty
from utils.log_sender import (
    delete_order_log_scan_count,
    delete_order_log_scan_counts_for_client_ids,
    is_transient_monitor_log_line,
    reset_scan_count_after_scheduled_order_removed,
)
from utils.monitor_scan_settings import order_requires_nepse_alpha
from utils.order_status_log_serializer import serialize_order_status_log, status_log_from_scheduled_order
from utils.scheduled_monitor_control import (
    get_scheduler_display_status,
    scheduled_monitor_supervisor_loop,
    start_scheduled_order_monitor,
    stop_scheduled_order_monitor,
)
from utils.market_gate import resolve_market_gate
from utils.tms import TmsUser
import uvicorn
import jwt
from fastapi import FastAPI, Request, HTTPException
from sqlalchemy.orm import Session
from datetime import date, datetime, timedelta

from utils.tms_user_loader import (
    auto_login_retry_allowed,
    load_tms_users_instances,
    record_auto_login_failure,
    record_auto_login_success,
)
from utils.api_time import format_api_timestamp, get_server_time_payload, is_continuous_market_timestamp
from utils.market_status import (
    MARKET_HOURS_LABEL,
    MARKET_LIVE_POLL_INTERVAL_SECONDS,
    MARKET_POLL_HOURS_LABEL,
    format_nepal_datetime,
    get_market_hours_status,
    get_next_market_poll_start,
    get_nepal_now,
    is_market_polling_window,
    nepal_date_utc_bounds,
    outside_market_hours_message,
)
from utils.market_live_state import get_shared_dna_session, get_shared_dna_session_snapshot
import config.tms_config as tms_config
from config.app_build_info import get_app_build_info
from utils.external_data_sources.nepse_alpha.ai_query import ScreenerAiError, test_all_llm_connections
from utils.market_data.sql_screener import MarketSqlError
from utils.market_data.analysis_ai_query import execute_combined_ai_screener
from utils.market_data.ai_quick_screens import (
    build_quick_ai_screen_payload,
    list_quick_ai_screens,
    match_quick_ai_screen,
)
from utils.market_data.repository import get_cache_status
from utils.auth_api import router as auth_router
from utils.auth import authenticate_request, authenticate_token, create_access_token, owned_client_ids, require_owned_client, require_permission, resolved_permissions
from utils.market_data.symbols import resolve_analysis_symbols, screener_universe_label
from utils.strategy_builder.api import router as strategy_builder_router
from utils.strategy_builder.reference_display import (
    display_values_for_scheduled_order,
    display_values_from_strategy_config,
)
from utils.live_quote_socket import is_live_socket_snapshot, live_quote_manager

app = FastAPI(debug=True)
app.include_router(strategy_builder_router)
app.include_router(auth_router)
SECRET_KEY = "your_secret_key_here"
FRONTEND_BUILD_DIR = Path(__file__).resolve().parent / "frontend" / "build"

API_PERMISSION_PREFIXES = (
    (("/stock_grabber", "/stop_stock_grabber", "/get_stock_grabber", "/active_stock_grabbers", "/stop_all_stock_grabbers"), "stock_grabber"),
    (("/tms-accounts", "/logged_in_clients", "/login/", "/get_order_book", "/get_daily_order_book", "/get_script_details"), "tms_login"),
    (("/scheduled_orders", "/add_order", "/cancel_order", "/check_orders", "/stop_check_orders", "/monitoring-status"), "schedule_orders"),
    (("/order_status_logs", "/order_history", "/logs/"), "order_logs"),
    (("/dp_holdings", "/tradebook_history"), "portfolio"),
    (("/market_analysis", "/stock_screener"), "market_analysis"),
    (("/api/backtest", "/api/backtests", "/api/technical-indicators"), "backtest"),
    (("/api/market-recommendations",), "recommendations"),
    (("/api/strategy-plans",), "schedule_orders"),
    (("/api/strategy-builder",), "strategy_details"),
    (("/api/portal-settings", "/update_monitor_interval", "/get_monitor_interval"), "settings"),
)


@app.middleware("http")
async def enforce_feature_access(request: Request, call_next):
    path = request.url.path
    required = next((permission for prefixes, permission in API_PERMISSION_PREFIXES if path.startswith(prefixes)), None)
    if not required:
        return await call_next(request)
    try:
        def authorize() -> int:
            db = SessionLocal()
            try:
                user = authenticate_request(request, db)
                if required not in resolved_permissions(user):
                    raise HTTPException(status_code=403, detail=f"Access to {required.replace('_', ' ')} is not allowed.")
                return int(user.id)
            finally:
                db.close()

        # Authentication performs a database lookup. Never run it on the
        # asyncio event loop: a busy backtest/database pool must not freeze
        # health checks, navigation, monitoring or other lightweight APIs.
        request.state.frontend_user_id = await asyncio.to_thread(authorize)
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return await call_next(request)

# Store running tasks and updates
running_tasks: Dict[str, asyncio.Task] = {}
tms_login_tasks: Dict[str, asyncio.Task] = {}
scheduled_supervisor_task: Optional[asyncio.Task] = None
market_data_scheduler_task: Optional[asyncio.Task] = None
running_grabbers: Dict[str, TmsUser] = {}
stock_grabber_updates: Dict[str, List[Dict]] = {}
stock_grabber_owners: Dict[str, int] = {}
stock_grabber_fetch_tests: Dict[str, Dict] = {}
ai_screen_jobs: Dict[str, Dict] = {}
ai_screen_tasks: Dict[str, asyncio.Task] = {}
AI_SCREEN_JOB_TTL_SECONDS = 600.0
tms_user_cache: Dict[str, TmsUser] = {}
tms_user_cache_touched: Dict[str, float] = {}
tms_user_cache_ttl = 300.0
market_status_cache: Optional[tuple[float, dict]] = None
MARKET_STATUS_CACHE_TTL_SECONDS = float(MARKET_LIVE_POLL_INTERVAL_SECONDS)

async def invalidate_cached_tms_user(client_id: str) -> None:
    cached = tms_user_cache.pop(client_id, None)
    tms_user_cache_touched.pop(client_id, None)
    if cached:
        await cached.close()

async def get_cached_tms_user(
    user: User,
    *,
    request_per_sec: float = 5,
    allow_full_login: bool = False,
) -> TmsUser:
    from utils.tms_broker import normalize_broker_no

    broker_no = normalize_broker_no(user.broker_no)
    now = monotonic_time.monotonic()
    cached = tms_user_cache.get(user.client_id)
    touched = tms_user_cache_touched.get(user.client_id, 0)
    if (
        cached
        and now - touched < tms_user_cache_ttl
        and str(cached.broker_no) == str(broker_no)
        and cached.password == user.password
        and cached.session is not None
        and not cached.session.closed
    ):
        tms_user_cache_touched[user.client_id] = now
        return cached

    if cached:
        await invalidate_cached_tms_user(user.client_id)

    tms_user = TmsUser(
        broker_no=broker_no,
        username=user.client_id,
        password=user.password,
        request_per_sec=request_per_sec,
    )
    try:
        await tms_user.try_cached_login(allow_full_login=allow_full_login)
    except Exception:
        await tms_user.close()
        raise

    tms_user_cache[user.client_id] = tms_user
    tms_user_cache_touched[user.client_id] = now
    return tms_user


TRADEBOOK_CACHE_REFRESH_DAYS = 2
TRADEBOOK_HISTORY_START_DATE = date(2010, 10, 1)


def _parse_trade_date(value) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text_value = str(value).strip()
    if not text_value:
        return None
    for separator in ("T", " "):
        if separator in text_value:
            text_value = text_value.split(separator, 1)[0]
            break
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text_value, fmt).date()
        except ValueError:
            continue
    return None


def _trade_float(value, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return default


def _trade_symbol(row: dict) -> str:
    return str(
        row.get("symbol")
        or row.get("script_name")
        or row.get("securitySymbol")
        or (row.get("security") or {}).get("symbol")
        or ""
    ).strip().upper()


def _trade_side(row: dict) -> str:
    raw = str(row.get("buyOrSell") or row.get("side") or row.get("order_type") or "").strip().upper()
    if raw in {"1", "BUY", "B"} or "BUY" in raw:
        return "BUY"
    if raw in {"2", "SELL", "S"} or "SELL" in raw:
        return "SELL"
    return raw


def _trade_price(row: dict) -> float:
    return _trade_float(row.get("tradePrice") or row.get("orderPrice") or row.get("price"))


def _trade_qty(row: dict) -> float:
    return _trade_float(row.get("tradedQuantity") or row.get("quantity") or row.get("qty"))


def _trade_date(row: dict) -> Optional[date]:
    return _parse_trade_date(row.get("tradeTime") or row.get("orderTime") or row.get("created_at") or row.get("date"))


def _trade_uid(client_id: str, row: dict) -> str:
    trade_id = str(row.get("exchangeTradeId") or "").strip()
    order_id = str(row.get("exchangeOrderId") or "").strip()
    if trade_id or order_id:
        return f"{client_id}:{trade_id}:{order_id}"
    return f"{client_id}:{_trade_symbol(row)}:{_trade_side(row)}:{_trade_date(row)}:{_trade_price(row)}:{_trade_qty(row)}"


def _trade_timestamp(row: dict) -> Optional[datetime]:
    raw_value = str(
        row.get("tradeTime")
        or row.get("orderTime")
        or row.get("created_at")
        or row.get("date")
        or ""
    ).strip()
    if not raw_value:
        return None
    normalized = raw_value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        pass
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S.%f",
    ):
        try:
            return datetime.strptime(raw_value, fmt)
        except ValueError:
            continue
    parsed_date = _trade_date(row)
    if parsed_date:
        return datetime.combine(parsed_date, datetime.min.time())
    return None


def _trade_order_key(row: dict) -> tuple:
    return (
        _trade_timestamp(row) or datetime.min,
        _trade_date(row) or date.min,
        str(row.get("exchangeTradeId") or "").strip(),
        str(row.get("exchangeOrderId") or "").strip(),
        str(row.get("id") or "").strip(),
    )


def _date_label(start: Optional[date], end: Optional[date]) -> str:
    if not start:
        return "-"
    start_text = f"{start.year}-{start.month}-{start.day}"
    if not end:
        return f"{start_text} - Open"
    return f"{start_text} - {end.year}-{end.month}-{end.day}"


def _holding_days(start: Optional[date], end: Optional[date]) -> Optional[int]:
    if not start:
        return None
    finish = end or date.today()
    return max(0, (finish - start).days)


def _iter_week_ranges(start: date, end: date):
    current = start
    while current <= end:
        week_end = min(current + timedelta(days=6), end)
        yield current, week_end
        current = week_end + timedelta(days=1)


def _should_refresh_trade_range(db: Session, client_id: str, start: date, end: date, force: bool = False) -> bool:
    if force:
        return True
    refreshed_at = db.execute(
        text(
            """
            SELECT refreshed_at
            FROM tradebook_history_refreshes
            WHERE client_id = :client_id AND from_date = :from_date AND to_date = :to_date
            """
        ),
        {"client_id": client_id, "from_date": start, "to_date": end},
    ).scalar()
    if not refreshed_at:
        return True
    if isinstance(refreshed_at, str):
        refreshed_at = datetime.fromisoformat(refreshed_at)
    return datetime.utcnow() - refreshed_at >= timedelta(days=TRADEBOOK_CACHE_REFRESH_DAYS)


def _cache_trade_rows(db: Session, client_id: str, rows: List[dict], start: date, end: date) -> None:
    for row in rows:
        if not isinstance(row, dict):
            continue
        traded_on = _trade_date(row)
        symbol = _trade_symbol(row)
        side = _trade_side(row)
        qty = _trade_qty(row)
        if not traded_on or not symbol or side not in {"BUY", "SELL"} or qty <= 0:
            continue
        db.execute(
            text(
                """
                INSERT INTO tradebook_history_cache (
                    client_id, trade_uid, symbol, side, trade_date, trade_price, quantity, raw_row, fetched_at, updated_at
                )
                VALUES (
                    :client_id, :trade_uid, :symbol, :side, :trade_date, :trade_price, :quantity,
                    CAST(:raw_row AS JSON), NOW(), NOW()
                )
                ON CONFLICT (trade_uid) DO UPDATE SET
                    symbol = EXCLUDED.symbol,
                    side = EXCLUDED.side,
                    trade_date = EXCLUDED.trade_date,
                    trade_price = EXCLUDED.trade_price,
                    quantity = EXCLUDED.quantity,
                    raw_row = EXCLUDED.raw_row,
                    updated_at = NOW()
                """
            ),
            {
                "client_id": client_id,
                "trade_uid": _trade_uid(client_id, row),
                "symbol": symbol,
                "side": side,
                "trade_date": traded_on,
                "trade_price": _trade_price(row),
                "quantity": qty,
                "raw_row": json.dumps({**row, "client_id": client_id}),
            },
        )
    for chunk_start, chunk_end in _iter_week_ranges(start, end):
        db.execute(
            text(
                """
                INSERT INTO tradebook_history_refreshes (client_id, from_date, to_date, refreshed_at)
                VALUES (:client_id, :from_date, :to_date, NOW())
                ON CONFLICT (client_id, from_date, to_date) DO UPDATE SET refreshed_at = NOW()
                """
            ),
            {"client_id": client_id, "from_date": chunk_start, "to_date": chunk_end},
        )
    db.commit()


def _stale_trade_ranges(db: Session, client_id: str, start: date, end: date, force: bool = False) -> List[tuple[date, date]]:
    ranges: List[tuple[date, date]] = []
    current_start: Optional[date] = None
    current_end: Optional[date] = None
    for chunk_start, chunk_end in _iter_week_ranges(start, end):
        if not _should_refresh_trade_range(db, client_id, chunk_start, chunk_end, force=force):
            if current_start and current_end:
                ranges.append((current_start, current_end))
                current_start = None
                current_end = None
            continue
        if current_start is None:
            current_start = chunk_start
        current_end = chunk_end
    if current_start and current_end:
        ranges.append((current_start, current_end))
    return ranges


async def _refresh_tradebook_cache(
    db: Session,
    tms_user: TmsUser,
    client_id: str,
    start: date,
    end: date,
    force: bool = False,
) -> None:
    for chunk_start, chunk_end in _stale_trade_ranges(db, client_id, start, end, force=force):
        rows = await tms_user.get_tradebook_history(chunk_start.isoformat(), chunk_end.isoformat())
        _cache_trade_rows(db, client_id, rows, chunk_start, chunk_end)


def _cached_trade_rows(db: Session, client_id: str, start: date, end: date) -> List[dict]:
    result = db.execute(
        text(
            """
            SELECT raw_row
            FROM tradebook_history_cache
            WHERE client_id = :client_id
              AND trade_date BETWEEN :from_date AND :to_date
            ORDER BY trade_date DESC, id DESC
            """
        ),
        {"client_id": client_id, "from_date": start, "to_date": end},
    )
    rows: List[dict] = []
    for (raw_row,) in result:
        if isinstance(raw_row, str):
            row = json.loads(raw_row)
        elif isinstance(raw_row, dict):
            row = raw_row
        else:
            continue
        trade_date = _trade_date(row)
        if trade_date:
            row["tradeDate"] = trade_date.isoformat()
        rows.append(row)
    return rows


def _normalize_cached_dp_holdings(holdings: List[dict], client_id: str) -> List[dict]:
    normalized: List[dict] = []
    for holding in holdings or []:
        if not isinstance(holding, dict):
            continue
        row = dict(holding)
        if not row.get("clientID"):
            row["clientID"] = client_id
        normalized.append(row)
    return normalized


def _load_dp_holdings_cache(db: Session, client_id: str) -> List[dict]:
    row = db.execute(
        text(
            """
            SELECT holdings_json
            FROM dp_holdings_cache
            WHERE client_id = :client_id
            """
        ),
        {"client_id": client_id},
    ).first()
    if not row:
        return []
    payload = row[0]
    if isinstance(payload, str):
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            return []
    else:
        parsed = payload
    if not isinstance(parsed, list):
        return []
    return _normalize_cached_dp_holdings(parsed, client_id)


def _save_dp_holdings_cache(db: Session, client_id: str, holdings: List[dict], *, source: str, market_phase: str) -> None:
    db.execute(
        text(
            """
            INSERT INTO dp_holdings_cache (client_id, holdings_json, source, market_phase, refreshed_at, updated_at)
            VALUES (:client_id, CAST(:holdings_json AS JSON), :source, :market_phase, NOW(), NOW())
            ON CONFLICT (client_id) DO UPDATE SET
                holdings_json = EXCLUDED.holdings_json,
                source = EXCLUDED.source,
                market_phase = EXCLUDED.market_phase,
                refreshed_at = NOW(),
                updated_at = NOW()
            """
        ),
        {
            "client_id": client_id,
            "holdings_json": json.dumps(_normalize_cached_dp_holdings(holdings, client_id)),
            "source": source,
            "market_phase": market_phase,
        },
    )
    db.commit()


async def _build_live_dp_holdings(db: Session, tms_user: TmsUser, client_id: str) -> List[dict]:
    dp_holdings = await tms_user.get_user_stock_details()
    await _ensure_full_trade_history_cache(db, tms_user, client_id)
    cached_start, cached_end = _cached_trade_date_bounds(db, client_id)
    history_rows = _cached_trade_rows(db, client_id, cached_start, cached_end) if cached_start and cached_end else []
    basis = _build_trade_cost_basis(history_rows)
    enriched_holdings = []
    for holding in dp_holdings or []:
        symbol = str(holding.get("scrip") or holding.get("symbolName") or "").strip().upper()
        item = basis.get(symbol)
        if item:
            avg_buy = item.get("average_buy_price")
            quantity = _trade_float(holding.get("currentBalance"))
            ltp = _trade_float(holding.get("ltp") or holding.get("previousCloseprice"))
            holding["averageBuyPrice"] = avg_buy
            holding["buyValue"] = (avg_buy or 0) * quantity
            holding["actualProfitLoss"] = (ltp - (avg_buy or ltp)) * quantity if avg_buy else None
            holding["buyPriceSource"] = "history_db"
            first_buy_date = item.get("first_buy_date")
            holding["holdingDays"] = _holding_days(first_buy_date, None) if first_buy_date else None
            holding["dateRange"] = _date_label(first_buy_date, None) if first_buy_date else "-"
        else:
            holding["buyPriceSource"] = "missing_history_db"
        enriched_holdings.append(holding)
    return enriched_holdings


def _build_trade_cost_basis(rows: List[dict]) -> Dict[str, dict]:
    lots_by_symbol: Dict[str, List[dict]] = {}
    for row in sorted(rows or [], key=_trade_order_key):
        symbol = _trade_symbol(row)
        side = _trade_side(row)
        qty = _trade_qty(row)
        price = _trade_price(row)
        traded_on = _trade_date(row)
        if not symbol or side not in {"BUY", "SELL"} or qty <= 0 or price <= 0:
            continue

        if side == "BUY":
            lots_by_symbol.setdefault(symbol, []).append({
                "qty": qty,
                "price": price,
                "date": traded_on,
            })
            continue

        remaining = qty
        lots = lots_by_symbol.get(symbol, [])
        while remaining > 0 and lots:
            lot = lots[0]
            matched_qty = min(remaining, lot["qty"])
            lot["qty"] -= matched_qty
            remaining -= matched_qty
            if lot["qty"] <= 0.00001:
                lots.pop(0)
        if not lots:
            lots_by_symbol.pop(symbol, None)

    basis: Dict[str, dict] = {}
    for symbol, lots in lots_by_symbol.items():
        quantity = 0.0
        cost = 0.0
        first_buy_date: Optional[date] = None
        for lot in lots:
            lot_qty = float(lot.get("qty") or 0)
            lot_price = float(lot.get("price") or 0)
            if lot_qty <= 0 or lot_price <= 0:
                continue
            quantity += lot_qty
            cost += lot_qty * lot_price
            lot_date = lot.get("date")
            if lot_date and (first_buy_date is None or lot_date < first_buy_date):
                first_buy_date = lot_date
        if quantity <= 0:
            continue
        basis[symbol] = {
            "quantity": quantity,
            "cost": cost,
            "average_buy_price": cost / quantity if quantity else None,
            "first_buy_date": first_buy_date,
            "open_lots": len(lots),
        }
    return basis


def _build_trade_positions(rows: List[dict], current_prices: Optional[Dict[str, float]] = None) -> List[dict]:
    lots: Dict[str, List[dict]] = {}
    positions: List[dict] = []
    current_prices = current_prices or {}
    sorted_rows = sorted(rows, key=_trade_order_key)

    for row in sorted_rows:
        symbol = _trade_symbol(row)
        side = _trade_side(row)
        qty = _trade_qty(row)
        price = _trade_price(row)
        traded_on = _trade_date(row)
        if not symbol or side not in {"BUY", "SELL"} or qty <= 0 or price <= 0:
            continue
        if side == "BUY":
            lots.setdefault(symbol, []).append({
                "qty": qty,
                "price": price,
                "date": traded_on,
                "client_id": row.get("client_id", ""),
            })
            continue

        remaining = qty
        while remaining > 0 and lots.get(symbol):
            lot = lots[symbol][0]
            matched_qty = min(remaining, lot["qty"])
            buy_price = lot["price"]
            profit_loss = (price - buy_price) * matched_qty
            buy_date = lot.get("date")
            positions.append({
                "symbol": symbol,
                "client_id": row.get("client_id", ""),
                "tradeDate": traded_on.isoformat() if traded_on else "",
                "dateRange": _date_label(buy_date, traded_on),
                "holdingDays": _holding_days(buy_date, traded_on),
                "quantity": matched_qty,
                "buyPrice": buy_price,
                "sellPrice": price,
                "profitLoss": profit_loss,
                "status": "Closed",
            })
            lot["qty"] -= matched_qty
            remaining -= matched_qty
            if lot["qty"] <= 0.00001:
                lots[symbol].pop(0)

    for symbol, symbol_lots in lots.items():
        market_price = current_prices.get(symbol)
        for lot in symbol_lots:
            if lot["qty"] <= 0:
                continue
            profit_loss = ((market_price or lot["price"]) - lot["price"]) * lot["qty"]
            positions.append({
                "symbol": symbol,
                "client_id": lot.get("client_id", ""),
                "tradeDate": lot.get("date").isoformat() if lot.get("date") else "",
                "dateRange": _date_label(lot.get("date"), None),
                "holdingDays": _holding_days(lot.get("date"), None),
                "quantity": lot["qty"],
                "buyPrice": lot["price"],
                "sellPrice": market_price,
                "profitLoss": profit_loss,
                "status": "Open",
            })

    positions.sort(key=lambda row: (row.get("status") != "Open", row.get("dateRange") or ""))
    return positions


def _portfolio_cost_basis(positions: List[dict]) -> Dict[str, dict]:
    basis: Dict[str, dict] = {}
    for position in positions:
        if position.get("status") != "Open":
            continue
        symbol = str(position.get("symbol") or "").upper()
        qty = _trade_float(position.get("quantity"))
        buy_price = _trade_float(position.get("buyPrice"))
        if not symbol or qty <= 0 or buy_price <= 0:
            continue
        item = basis.setdefault(symbol, {"quantity": 0.0, "cost": 0.0, "first_buy_date": None})
        item["quantity"] += qty
        item["cost"] += qty * buy_price
        buy_date = _parse_trade_date(str(position.get("dateRange") or "").split(" - ", 1)[0])
        if buy_date and (item["first_buy_date"] is None or buy_date < item["first_buy_date"]):
            item["first_buy_date"] = buy_date
    for item in basis.values():
        item["average_buy_price"] = item["cost"] / item["quantity"] if item["quantity"] else None
    return basis


def _cached_trade_date_bounds(db: Session, client_id: str) -> tuple[Optional[date], Optional[date]]:
    row = db.execute(
        text(
            """
            SELECT MIN(trade_date), MAX(trade_date)
            FROM tradebook_history_cache
            WHERE client_id = :client_id
            """
        ),
        {"client_id": client_id},
    ).first()
    if not row:
        return None, None
    return row[0], row[1]


def _trade_cache_covers_history(db: Session, client_id: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT MIN(trade_date) AS min_trade_date, MAX(trade_date) AS max_trade_date
            FROM tradebook_history_cache
            WHERE client_id = :client_id
            """
        ),
        {"client_id": client_id},
    ).first()
    if not row or row[0] is None or row[1] is None:
        return False
    return row[0] <= TRADEBOOK_HISTORY_START_DATE and row[1] >= date.today() - timedelta(days=1)


async def _ensure_full_trade_history_cache(db: Session, tms_user: TmsUser, client_id: str) -> None:
    if _trade_cache_covers_history(db, client_id):
        return
    await _refresh_tradebook_cache(
        db,
        tms_user,
        client_id,
        TRADEBOOK_HISTORY_START_DATE,
        date.today(),
        force=False,
    )


async def _refresh_trade_cache_background(
    client_id: str,
    from_date: date,
    to_date: date,
) -> None:
    db = get_db_session()
    try:
        user = db.query(User).filter(User.client_id == client_id).first()
        if not user:
            return
        tms_user = await get_cached_tms_user(user)
        await _refresh_tradebook_cache(db, tms_user, client_id, from_date, to_date, force=True)
    except Exception:
        return
    finally:
        db.close()


@app.on_event("shutdown")
async def close_cached_tms_users() -> None:
    global scheduled_supervisor_task, market_data_scheduler_task
    login_tasks = list(tms_login_tasks.values())
    for task in login_tasks:
        if not task.done():
            task.cancel()
    if login_tasks:
        await asyncio.gather(*login_tasks, return_exceptions=True)
    tms_login_tasks.clear()
    if scheduled_supervisor_task is not None and not scheduled_supervisor_task.done():
        scheduled_supervisor_task.cancel()
        try:
            await scheduled_supervisor_task
        except asyncio.CancelledError:
            pass
    if market_data_scheduler_task is not None and not market_data_scheduler_task.done():
        market_data_scheduler_task.cancel()
        try:
            await market_data_scheduler_task
        except asyncio.CancelledError:
            pass
    scheduled_supervisor_task = None
    await stop_scheduled_order_monitor()
    await live_quote_manager.close_all()
    for client_id in list(tms_user_cache.keys()):
        await invalidate_cached_tms_user(client_id)
    if os.getenv("BACKTEST_V2", "true").strip().lower() in {"1", "true", "yes", "on"}:
        from utils.backtesting.v2_jobs import stop_worker as stop_backtest_v2_worker
        await asyncio.to_thread(stop_backtest_v2_worker)

@app.on_event("startup")
async def ensure_database_indexes() -> None:
    global scheduled_supervisor_task, market_data_scheduler_task
    from config.portal_settings import load_portal_settings
    from utils.market_data.scheduler import market_data_scheduler_loop

    await asyncio.to_thread(ensure_performance_indexes)
    from utils.backtesting.jobs import resume_persisted_batch_jobs
    await asyncio.to_thread(resume_persisted_batch_jobs)
    if os.getenv("BACKTEST_V2", "true").strip().lower() in {"1", "true", "yes", "on"}:
        from utils.backtesting.v2_jobs import start_worker as start_backtest_v2_worker
        start_backtest_v2_worker()
    from utils.technical_indicators.refresh import start_indicator_refresh_background
    start_indicator_refresh_background()
    await asyncio.to_thread(_seed_market_screen_presets)
    await asyncio.to_thread(load_portal_settings)
    scheduled_supervisor_task = asyncio.create_task(scheduled_monitor_supervisor_loop())
    market_data_scheduler_task = asyncio.create_task(market_data_scheduler_loop())
    asyncio.create_task(_warm_market_cache_on_startup())


async def _warm_market_cache_on_startup() -> None:
    from utils.market_data.nonblocking_cache import kickoff_cache_bootstrap_if_empty

    try:
        result = await kickoff_cache_bootstrap_if_empty()
        logging.getLogger(__name__).info("Market cache warm-up kickoff: %s", result)
    except Exception:
        logging.getLogger(__name__).exception("Market cache warm-up kickoff failed")


def _seed_market_screen_presets() -> None:
    from utils.market_data.screen_presets import ensure_market_screen_presets

    db = get_db_session()
    try:
        ensure_market_screen_presets(db)
    finally:
        db.close()

async def _run_stock_grabber_task(
    tms_user: TmsUser,
    session_id: str,
    order_quantity: int,
    max_order_limit: int,
    stop_buy_after_percent: float,
    stop_buy_after_volume: float,
) -> None:
    from datetime import timezone

    tms_config.grabber_started_at[session_id] = datetime.now(timezone.utc)
    tms_config.grabber_phase[session_id] = "waiting_hours"
    tms_config.grabber_status_message[session_id] = "Armed — waiting for market"

    try:
        while True:
            gate = await resolve_market_gate({tms_user.client_id: tms_user})
            tms_config.grabber_phase[session_id] = gate["phase"]
            tms_config.grabber_status_message[session_id] = gate["message"]

            if not gate["can_scan"]:
                stock_grabber_updates[session_id].append(
                    {"status": "waiting", "message": gate["message"]}
                )
                await asyncio.sleep(MARKET_LIVE_POLL_INTERVAL_SECONDS)
                continue

            try:
                result = await tms_user.stock_grabber(
                    order_quantity=order_quantity,
                    session_id=session_id,
                    max_order_limit=max_order_limit,
                    stop_buy_after_percent=stop_buy_after_percent,
                    stop_buy_after_volume=stop_buy_after_volume,
                )
                placed = len(result.get("totalOrders") or [])
                if placed > 0 or result.get("message") == "ACCESS_TOKEN_EXPIRED" or result.get("stop_reason"):
                    break
                if result.get("message") == "MARKET_NOT_LIVE":
                    await asyncio.sleep(MARKET_LIVE_POLL_INTERVAL_SECONDS)
                    continue
                tms_user.updates.append({
                    "status": "scanning",
                    "message": "Scan interrupted — resuming price watch…",
                })
                await asyncio.sleep(2)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                stock_grabber_updates[session_id].append(
                    {"status": "warn", "message": f"Grabber error ({exc}) — resuming scan…"}
                )
                await asyncio.sleep(2)
    except asyncio.CancelledError:
        raise
    finally:
        tms_config.grabber_started_at.pop(session_id, None)
        tms_config.grabber_phase.pop(session_id, None)
        tms_config.grabber_status_message.pop(session_id, None)
        await tms_user.close()


@app.post("/stock_grabber/")
async def stock_grabber(request: StockGrabberRequest, db: Session = Depends(get_db), current_user: FrontendUser = Depends(require_permission("stock_grabber"))):
    session_id = str(uuid.uuid4())
    stock_grabber_updates[session_id] = []
    user = require_owned_client(db, current_user, request.client_id)
    stock_grabber_owners[session_id] = current_user.id

    symbol = (request.stock_symbol or "").strip().upper()
    for tms_user in running_grabbers.values():
        existing_symbol = (tms_user.stock_symbol or "").strip().upper()
        if tms_user.client_id == request.client_id and existing_symbol == symbol:
            raise HTTPException(
                status_code=409,
                detail=f"{symbol} is already being monitored for {request.client_id}",
            )

    max_order_limit = int(request.max_order_limit) if request.max_order_limit and int(request.max_order_limit) > 0 else 4
    configured_stop = 15.0 if request.stop_buy_after_percent is None else float(request.stop_buy_after_percent)
    stop_buy_after_percent = min(15.0, max(0.0, configured_stop))
    configured_volume_stop = 5000.0 if request.stop_buy_after_volume is None else float(request.stop_buy_after_volume)
    stop_buy_after_volume = max(0.0, configured_volume_stop)

    tms_user = TmsUser(
        broker_no=user.broker_no,
        username=user.client_id,
        password=user.password,
        stock_symbol=request.stock_symbol,
        request_per_sec=request.request_per_sec,
        scan_mode=request.scan_mode or "socket",
        resume_scan_count=int(request.resume_scan_count or 0),
        resume_previous_ltp=float(request.resume_previous_ltp or 0.0),
        resume_stable_rate=request.resume_stable_rate,
    )
    await tms_user.try_cached_login()

    task = asyncio.create_task(
        _run_stock_grabber_task(
            tms_user,
            session_id,
            request.order_quantity,
            max_order_limit,
            stop_buy_after_percent,
            stop_buy_after_volume,
        )
    )
    running_tasks[session_id] = task
    running_grabbers[session_id] = tms_user

    def _on_grabber_done(done_task: asyncio.Task) -> None:
        running_tasks.pop(session_id, None)
        running_grabbers.pop(session_id, None)
        stock_grabber_owners.pop(session_id, None)
        tms_config.grabber_started_at.pop(session_id, None)
        tms_config.grabber_phase.pop(session_id, None)
        tms_config.grabber_status_message.pop(session_id, None)
        if done_task.cancelled():
            return
        exc = done_task.exception()
        if exc:
            stock_grabber_updates[session_id].append(
                {"status": "failed", "message": f"Stock grabber crashed: {exc}"}
            )

    task.add_done_callback(_on_grabber_done)
    return {"session_id": session_id, "message": "Stock grabber started"}


async def _run_stock_grabber_fetch_speed_test(
    test_id: str,
    tms_user_instance: TmsUser,
    security: Dict,
    symbol: str,
    duration_seconds: float,
    request_per_sec: float,
    tms_api_url: str,
) -> None:
    interval_seconds = 1.0 / request_per_sec
    started_at = monotonic_time.monotonic()
    deadline = started_at + duration_seconds

    state = stock_grabber_fetch_tests[test_id]
    while monotonic_time.monotonic() < deadline:
        call_started_at = monotonic_time.monotonic()
        try:
            quote = await tms_user_instance.get_stock_details_async(
                str(security["id"]),
                max_retries=1,
                force_refresh=True,
            )
            if not quote:
                raise RuntimeError("Quote missing")
            state["ok_count"] = int(state.get("ok_count") or 0) + 1
            state["last_ltp"] = quote.get("ltp")
        except Exception as exc:
            state["fail_count"] = int(state.get("fail_count") or 0) + 1
            state["last_error"] = str(exc)

        elapsed_seconds = max(0.001, monotonic_time.monotonic() - started_at)
        state["duration_seconds"] = elapsed_seconds
        state["fetch_per_sec"] = int(state.get("ok_count") or 0) / elapsed_seconds

        elapsed_call = monotonic_time.monotonic() - call_started_at
        sleep_for = min(max(0.0, interval_seconds - elapsed_call), max(0.0, deadline - monotonic_time.monotonic()))
        if sleep_for > 0:
            await asyncio.sleep(sleep_for)

    elapsed_seconds = max(0.001, monotonic_time.monotonic() - started_at)
    state.update({
        "running": False,
        "done": True,
        "duration_seconds": elapsed_seconds,
        "fetch_per_sec": int(state.get("ok_count") or 0) / elapsed_seconds,
        "tms_api_url": tms_api_url,
    })


@app.post("/stock_grabber/test_fetch_speed")
async def test_stock_grabber_fetch_speed(
    request: StockGrabberFetchTestRequest,
    db: Session = Depends(get_db),
    current_user: FrontendUser = Depends(require_permission("stock_grabber")),
):
    user = require_owned_client(db, current_user, request.client_id)

    symbol = (request.stock_symbol or "").strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="Stock symbol is required")

    duration_seconds = min(30.0, max(1.0, float(request.duration_seconds or 10.0)))
    request_per_sec = min(200.0, max(0.2, float(request.request_per_sec or 2.0)))

    tms_user_instance = await get_cached_tms_user(user)
    security = await tms_user_instance.get_security_id(symbol)
    if not security or not security.get("id"):
        raise HTTPException(status_code=404, detail=f"Security not found for {symbol}")
    tms_api_url = (
        f"https://tms{tms_user_instance.broker_no}.nepsetms.com.np"
        f"/tmsapi/rtApi/ws/stockQuote/{security['id']}"
    )
    test_id = str(uuid.uuid4())
    stock_grabber_fetch_tests[test_id] = {
        "test_id": test_id,
        "mode": "fixed",
        "source": "tms_http",
        "cache_bypassed": True,
        "non_live_cache_bypassed": True,
        "tms_api_url": tms_api_url,
        "symbol": symbol,
        "security": security,
        "duration_seconds": 0.0,
        "requested_per_sec": request_per_sec,
        "ok_count": 0,
        "fail_count": 0,
        "fetch_per_sec": 0.0,
        "last_ltp": None,
        "last_error": None,
        "running": True,
        "done": False,
        "owner_user_id": current_user.id,
    }
    asyncio.create_task(_run_stock_grabber_fetch_speed_test(
        test_id,
        tms_user_instance,
        security,
        symbol,
        duration_seconds,
        request_per_sec,
        tms_api_url,
    ))
    return stock_grabber_fetch_tests[test_id]


@app.get("/stock_grabber/test_fetch_speed/{test_id}")
async def get_stock_grabber_fetch_speed_status(test_id: str, current_user: FrontendUser = Depends(require_permission("stock_grabber"))):
    state = stock_grabber_fetch_tests.get(test_id)
    if not state or state.get("owner_user_id") != current_user.id:
        raise HTTPException(status_code=404, detail="Fetch speed test not found")
    return state

@app.post("/stop_stock_grabber/{session_id}")
async def stop_stock_grabber(session_id: str, current_user: FrontendUser = Depends(require_permission("stock_grabber"))):
    if stock_grabber_owners.get(session_id) != current_user.id:
        raise HTTPException(status_code=404, detail="Stock grabber not found")
    task = running_tasks.get(session_id)
    if task:
        task.cancel()
        del running_tasks[session_id]
        running_grabbers.pop(session_id, None)
        stock_grabber_owners.pop(session_id, None)
        tms_config.grabber_started_at.pop(session_id, None)
        tms_config.grabber_phase.pop(session_id, None)
        tms_config.grabber_status_message.pop(session_id, None)
        stock_grabber_updates[session_id].append({"status": "stopped", "message": "Stock grabber stopped"})
        return {"message": f"Stock grabber {session_id} stopped"}
    raise HTTPException(status_code=404, detail="Stock grabber not found")


@app.get("/get_stock_grabber_updates/{session_id}")
async def get_stock_grabber_updates(session_id: str, current_user: FrontendUser = Depends(require_permission("stock_grabber"))):
    if stock_grabber_owners.get(session_id) != current_user.id:
        raise HTTPException(status_code=404, detail="Stock grabber not found")
    updates = list(stock_grabber_updates.get(session_id, []))
    stock_grabber_updates[session_id] = []

    tms_user = running_grabbers.get(session_id)
    if tms_user and tms_user.updates:
        updates.extend(tms_user.updates)
        tms_user.updates = []
    if tms_user:
        live_snapshot = live_quote_manager.get_snapshot(tms_user.stock_symbol or "")
        quote = (live_snapshot or {}).get("quote") or {}
        if live_snapshot:
            updates.append({
                "status": "socket",
                "symbol": tms_user.stock_symbol,
                "quote_source": "socket" if is_live_socket_snapshot(live_snapshot) else "http",
                "socket_status": live_snapshot.get("status"),
                "socket_last_received_at": live_snapshot.get("last_received_at"),
                "socket_message_count": live_snapshot.get("message_count"),
                "ltp": quote.get("ltp"),
                "change_percentage": quote.get("changePercentage"),
                "topBuy": quote.get("topBuy") or [],
                "topSell": quote.get("topSell") or [],
                "volume": quote.get("volume"),
                "lastTradedTime": quote.get("lastTradedTime"),
            })

    task = running_tasks.get(session_id)
    scanner_active = task is not None and not task.done()

    return {"updates": updates, "scanner_active": scanner_active}


@app.get("/active_stock_grabbers/")
@app.get("/active_stock_grabbers")
async def active_stock_grabbers(current_user: FrontendUser = Depends(require_permission("stock_grabber"))):
    grabbers = []
    for session_id, tms_user in running_grabbers.items():
        if stock_grabber_owners.get(session_id) != current_user.id:
            continue
        task = running_tasks.get(session_id)
        started_at = tms_config.grabber_started_at.get(session_id)
        live_snapshot = live_quote_manager.get_snapshot(tms_user.stock_symbol or "")
        grabbers.append({
            "session_id": session_id,
            "client_id": tms_user.client_id,
            "stock_symbol": tms_user.stock_symbol,
            "scan_count": getattr(tms_user, "scan_count", 0),
            "scanner_active": task is not None and not task.done(),
            "request_per_sec": tms_user.request_per_sec,
            "scan_mode": getattr(tms_user, "scan_mode", "socket"),
            "stop_buy_after_percent": getattr(tms_user, "stop_buy_after_percent", 15.0),
            "stop_buy_after_volume": getattr(tms_user, "stop_buy_after_volume", 5000.0),
            "stable_rate": tms_user.stable_rate,
            "phase": tms_config.grabber_phase.get(session_id, "armed"),
            "status_message": tms_config.grabber_status_message.get(session_id, ""),
            "socket_status": (live_snapshot or {}).get("status"),
            "socket_last_received_at": (live_snapshot or {}).get("last_received_at"),
            "socket_message_count": (live_snapshot or {}).get("message_count"),
            "started_at": started_at.isoformat() if started_at else None,
        })
    return {"grabbers": grabbers}


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

if (FRONTEND_BUILD_DIR / "static").exists():
    app.mount(
        "/static",
        StaticFiles(directory=str(FRONTEND_BUILD_DIR / "static")),
        name="static",
    )
# Load user credentials
# to disable the warnings in the logs
logging.disable(logging.WARNING)
# user_file_path = '/Users/pkafle/tms-automation/users.txt'
# if not user_file_path:
#     print("User credential file not found, exiting... ")
#     sys.exit()
# user = load_users(user_file_path)[0]

# Create an instance of Tms
# tms = TmsUser(
#     username=user['username'], password=user['password'], stock_symbol=user['stock_symbol'],
#     request_per_sec=user['request_per_sec'],broker_no= user['broker_no']
# )

# Define your routes


# Define your routes
@app.get("/")
async def read_root():
    index_path = FRONTEND_BUILD_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {"message": "Hello, FastAPI"}


@app.get("/app-info/")
async def get_app_info():
    info = get_app_build_info()
    deployed = info.get("deployed_at")
    if deployed:
        try:
            parsed = datetime.fromisoformat(str(deployed).replace("Z", "+00:00"))
            formatted = format_api_timestamp(parsed)
            if formatted:
                info["deployed_at"] = formatted
        except ValueError:
            pass
    return info


@app.get("/api/time/")
async def get_api_time():
    return get_server_time_payload()


@app.get("/health")
@app.get("/api/health")
async def health_check():
    return {"status": "ok"}


@app.get("/market-status/")
async def get_market_status(db: Session = Depends(get_db)):
    global market_status_cache
    cache_now = monotonic_time.monotonic()
    if market_status_cache and cache_now - market_status_cache[0] < MARKET_STATUS_CACHE_TTL_SECONDS:
        return market_status_cache[1]

    now = get_nepal_now()
    hours = get_market_hours_status(now)
    polling_window = is_market_polling_window(now)
    nepal = format_nepal_datetime(now)
    next_poll = format_nepal_datetime(get_next_market_poll_start(now))

    tms_session_active = False
    tms_session_message = "DNA logged off"
    dna_status = None
    market_live_from_api = None
    exchange_market_phase = None
    exchange_current_sessions = []
    client_id = None
    broker_no = None
    session_data = None

    logged_in = (
        db.query(LoggedInUsers)
        .filter(LoggedInUsers.status == "logged_in")
        .order_by(LoggedInUsers.last_updated.desc())
        .first()
    )

    if logged_in and logged_in.tokens:
        client_id = logged_in.client_id
        broker_no = logged_in.broker_no
        temp_tms_user = None
        try:
            user = db.query(User).filter(User.client_id == logged_in.client_id).first()
            temp_tms_user = None if user else TmsUser(
                username=logged_in.client_id,
                password="",
                broker_no=logged_in.broker_no,
            )
            tms_user = await get_cached_tms_user(user) if user else temp_tms_user
            async with asyncio.timeout(8):
                if not user:
                    await tms_user.try_cached_login()
                if polling_window:
                    dna = await get_shared_dna_session([tms_user])
                    tms_session_active = dna["session_active"]
                    tms_session_message = dna["session_message"]
                    dna_status = dna.get("dna_status")
                    session_data = dna["session_data"]
                    market_live_from_api = tms_session_active
                    exchange_market_phase = "open" if tms_session_active else "closed"
                else:
                    tms_session_message = f"Waiting for DNA market-check window ({MARKET_POLL_HOURS_LABEL})"
        except TimeoutError:
            tms_session_message = "Session check timed out"
        except LoginFailedException as exc:
            tms_session_message = exc.message
        except Exception as exc:
            tms_session_message = f"Unable to check TMS session: {exc}"
        finally:
            if temp_tms_user:
                await temp_tms_user.close()
    elif polling_window:
        tms_session_message = "No TMS client logged in"
    else:
        tms_session_message = f"Waiting for DNA market-check window ({MARKET_POLL_HOURS_LABEL})"

    market_live = market_live_from_api is True

    if exchange_market_phase in {"open", "pre_open", "closed"}:
        market_phase = exchange_market_phase
    elif polling_window:
        market_phase = "checking"
    else:
        market_phase = "closed"

    payload = {
        "server_time": nepal,
        "today_npt": nepal["date"],
        "nepal_time": nepal["npt"],
        "nepal_time_formatted": nepal["time"],
        "nepal_date_formatted": nepal["date"],
        "nepal_time_display": nepal["display"],
        "timezone": nepal["timezone"],
        "market_hours_label": MARKET_HOURS_LABEL,
        "market_poll_hours_label": MARKET_POLL_HOURS_LABEL,
        "next_market_poll_at": next_poll,
        "is_trading_day": hours["is_trading_day"],
        "is_pre_open": hours["is_pre_open"],
        "is_continuous_session": hours["is_continuous"],
        "market_hours_open": hours["market_hours_open"],
        "market_polling_window": polling_window,
        "market_live_poll_interval_seconds": MARKET_LIVE_POLL_INTERVAL_SECONDS,
        "market_status_source": "shared_tms_dna_session",
        "dna_status_source": "shared_tms_dna_session",
        "market_phase": market_phase,
        "tms_session_active": tms_session_active,
        "tms_session_message": tms_session_message,
        "dna_status": dna_status,
        "market_live": market_live,
        "market_live_from_api": market_live_from_api,
        "exchange_market_phase": exchange_market_phase,
        "exchange_current_sessions": exchange_current_sessions,
        "client_id": client_id,
        "broker_no": broker_no,
        "session_data": session_data,
        "tms_request_cache": TmsUser.tms_request_cache_status(),
    }
    market_status_cache = (cache_now, payload)
    return payload


@app.get("/api/monitor-diagnostics")
async def get_monitor_diagnostics(
    db: Session = Depends(get_db),
    current_user: FrontendUser = Depends(require_permission("order_logs")),
):
    """Read-only production diagnostics for scheduled-order monitoring."""
    now = get_nepal_now()
    polling_window = is_market_polling_window(now)
    dna = get_shared_dna_session_snapshot()
    scheduler = get_scheduler_display_status()
    orders = (
        db.query(ScheduledOrder)
        .filter(ScheduledOrder.owner_user_id == current_user.id)
        .filter(ScheduledOrder.status.notin_(("Executed", "Cancelled", "Failed", "Expired")))
        .order_by(ScheduledOrder.updated_at.desc())
        .all()
    )
    order_diagnostics = []
    for order in orders:
        scan_log = (
            db.query(OrderLog)
            .filter(OrderLog.client_id == order.client_id, OrderLog.script_name == order.script_name)
            .order_by(OrderLog.timestamp.desc())
            .first()
        )
        diagnostic_events = [
            line for line in str(scan_log.logs or "").splitlines()
            if line.startswith("DIAGNOSTIC:")
        ] if scan_log else []
        order_diagnostics.append({
            "order_id": order.order_id,
            "client_id": order.client_id,
            "script_name": order.script_name,
            "status": order.status,
            "last_monitor_update": format_api_timestamp(scan_log.timestamp) if scan_log else None,
            "last_price": scan_log.current_price if scan_log else None,
            "scan_count": int(scan_log.scanning_count or 0) if scan_log else 0,
            "recent_diagnostics": diagnostic_events[-10:],
        })

    return {
        "server_time": format_nepal_datetime(now),
        "market_polling_window": polling_window,
        "next_market_poll_at": format_nepal_datetime(get_next_market_poll_start(now)),
        "scheduler": scheduler,
        "market_live_decision": dna,
        "tms_request_cache": TmsUser.tms_request_cache_status(),
        "orders": order_diagnostics,
    }


def _decode_tms_account_password(password: Optional[str]) -> str:
    if not password:
        return ""
    try:
        return TmsUser.decode_password_payload(password)
    except Exception:
        return password


def _first_string_value(data: object, keys: set[str]) -> Optional[str]:
    if isinstance(data, dict):
        for key, value in data.items():
            if key in keys and isinstance(value, str) and value.strip():
                return value.strip()
        for value in data.values():
            found = _first_string_value(value, keys)
            if found:
                return found
    elif isinstance(data, list):
        for value in data:
            found = _first_string_value(value, keys)
            if found:
                return found
    return None


def _extract_tms_display_name(session: Optional[LoggedInUsers]) -> Optional[str]:
    if not session or not session.tokens:
        return None
    tokens = session.tokens if isinstance(session.tokens, dict) else {}
    login_response = tokens.get("login_response") if isinstance(tokens.get("login_response"), dict) else {}
    client_dealer_member = (
        login_response.get("clientDealerMember")
        if isinstance(login_response.get("clientDealerMember"), dict)
        else {}
    )
    preferred_roots = [
        tokens.get("client_details"),
        client_dealer_member,
        client_dealer_member.get("client"),
        login_response,
    ]
    name_keys = {
        "displayName",
        "clientName",
        "clientDealerName",
        "fullName",
        "name",
    }
    for root in preferred_roots:
        found = _first_string_value(root, name_keys)
        if found:
            return " ".join(found.split())

    if isinstance(login_response, dict):
        user = login_response.get("user")
        if isinstance(user, dict):
            parts = [
                str(user.get(key, "")).strip()
                for key in ("firstName", "middleName", "lastName")
                if str(user.get(key, "")).strip()
            ]
            if parts:
                return " ".join(parts)
    return None


def _serialize_tms_account(user: User, session: Optional[LoggedInUsers]) -> dict:
    display_name = _extract_tms_display_name(session)
    session_updated_at = session.last_updated.isoformat() if session and session.last_updated else None
    last_login_at = session.last_login_at.isoformat() if session and session.last_login_at else None
    return {
        "client_id": user.client_id,
        "display_name": display_name,
        "broker_no": user.broker_no,
        "password": _decode_tms_account_password(user.password),
        "auto_login": bool(user.auto_login),
        "session_status": session.status if session else "logged_out",
        "session_message": session.message if session else None,
        "last_updated": session_updated_at,
        "last_login_at": last_login_at,
        "session_updated_at": session_updated_at,
        "collateral": session.collateral if session and session.collateral else None,
        "collateral_error": None,
    }


def _resolve_account_collateral(client_id: str, session: Optional[LoggedInUsers]) -> Optional[dict]:
    collateral = TmsUser.get_cached_collateral_for_client(client_id)
    if collateral:
        return collateral
    if session and session.collateral:
        return session.collateral
    return get_persisted_collateral(client_id)


async def _attach_tms_account_collateral(
    account: dict,
    user: Optional[User],
    session: Optional[LoggedInUsers] = None,
) -> None:
    if not user:
        return
    collateral = _resolve_account_collateral(user.client_id, session)
    account["collateral"] = collateral
    account["collateral_error"] = None if collateral else "Collateral not loaded"


async def _refresh_tms_account_collateral(user: User) -> dict:
    try:
        await invalidate_cached_tms_user(user.client_id)
        tms_user = await get_cached_tms_user(user, request_per_sec=5)
        collateral = await tms_user.get_client_collateral(force_refresh=True)
        return {
            "client_id": user.client_id,
            "status": "success",
            "collateral": collateral,
            "message": "Collateral refreshed",
        }
    except Exception as exc:
        return {
            "client_id": user.client_id,
            "status": "failed",
            "collateral": None,
            "message": str(exc),
        }


def _record_tms_login_failure(
    db: Session,
    *,
    client_id: str,
    broker_no: Optional[str],
    message: str,
) -> None:
    session = db.query(LoggedInUsers).filter(LoggedInUsers.client_id == client_id).first()
    if not session:
        session = LoggedInUsers(client_id=client_id, tokens={}, broker_no=broker_no or "", status="logged_out")
        db.add(session)
    session.status = "logged_out"
    session.broker_no = broker_no or session.broker_no
    session.message = summarize_login_message(message)
    session.tokens = {}
    db.commit()


def _record_tms_login_pending(db: Session, *, client_id: str, broker_no: Optional[str]) -> None:
    session = db.query(LoggedInUsers).filter(LoggedInUsers.client_id == client_id).first()
    if not session:
        session = LoggedInUsers(
            client_id=client_id,
            tokens={},
            broker_no=broker_no or "",
        )
        db.add(session)
    session.status = "logging_in"
    session.broker_no = broker_no or session.broker_no
    session.message = "Login in progress"
    db.commit()


async def _run_tms_account_login(client_id: str, *, automatic: bool = False) -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.client_id == client_id).first()
        if not user:
            return

        await invalidate_cached_tms_user(client_id)
        tms_instance = await get_cached_tms_user(user, request_per_sec=5, allow_full_login=True)
        try:
            await tms_instance.get_client_collateral(force_refresh=True)
        except Exception:
            pass

        db.expire_all()
        session = db.query(LoggedInUsers).filter(LoggedInUsers.client_id == client_id).first()
        if not session:
            session = LoggedInUsers(client_id=client_id, tokens={}, broker_no=user.broker_no)
            db.add(session)
        session.status = "logged_in"
        session.message = "Logged in"
        session.last_login_at = datetime.utcnow()
        db.commit()
        record_auto_login_success(client_id)
    except asyncio.CancelledError:
        raise
    except LoginFailedException as exc:
        if automatic:
            record_auto_login_failure(client_id)
        _record_tms_login_failure(
            db,
            client_id=client_id,
            broker_no=getattr(locals().get("user"), "broker_no", None),
            message=exc.message,
        )
    except Exception as exc:
        if automatic:
            record_auto_login_failure(client_id)
        logging.exception("Background TMS login failed for %s", client_id)
        _record_tms_login_failure(
            db,
            client_id=client_id,
            broker_no=getattr(locals().get("user"), "broker_no", None),
            message=str(exc) or "Login failed",
        )
    finally:
        db.close()


def _remove_finished_tms_login_task(client_id: str, task: asyncio.Task) -> None:
    if tms_login_tasks.get(client_id) is task:
        tms_login_tasks.pop(client_id, None)


def _queue_tms_account_login(
    user: User,
    db: Session,
    *,
    automatic: bool,
    force: bool = False,
) -> bool:
    """Start one deduplicated background login for a saved TMS account."""
    if automatic and not auto_login_retry_allowed(user.client_id):
        return False

    current_task = tms_login_tasks.get(user.client_id)
    if current_task and not current_task.done():
        return False

    session = db.query(LoggedInUsers).filter(LoggedInUsers.client_id == user.client_id).first()
    if not force and session and session.status == "logged_in":
        return False

    _record_tms_login_pending(db, client_id=user.client_id, broker_no=user.broker_no)
    login_coro = (
        _run_tms_account_login(user.client_id, automatic=True)
        if automatic
        else _run_tms_account_login(user.client_id)
    )
    task = asyncio.create_task(login_coro)
    tms_login_tasks[user.client_id] = task
    task.add_done_callback(
        lambda finished, client_id=user.client_id: _remove_finished_tms_login_task(client_id, finished)
    )
    return True


def _queue_ui_auto_logins(db: Session, users: List[User]) -> None:
    """UI activity keeps all explicitly auto-login-enabled accounts warm."""
    for user in users:
        _queue_tms_account_login(user, db, automatic=True)


async def _reconcile_logged_in_sessions(db: Session, client_ids: Optional[List[str]] = None) -> None:
    if client_ids is not None and not client_ids:
        return
    session_query = db.query(LoggedInUsers)
    if client_ids is not None:
        session_query = session_query.filter(LoggedInUsers.client_id.in_(client_ids))
    interrupted_sessions = [
        session
        for session in session_query.all()
        if session.status == "logging_in"
    ]
    for session in interrupted_sessions:
        task = tms_login_tasks.get(session.client_id)
        if not task or task.done():
            session.status = "logged_out"
            session.message = summarize_login_message("Login interrupted; please try again")
    if interrupted_sessions:
        db.commit()

    sessions_query = db.query(LoggedInUsers).filter(LoggedInUsers.status == "logged_in")
    if client_ids is not None:
        sessions_query = sessions_query.filter(LoggedInUsers.client_id.in_(client_ids))
    sessions = sessions_query.all()
    if not sessions:
        return

    for session in sessions:
        user = db.query(User).filter(User.client_id == session.client_id).first()
        if not user:
            session.status = "logged_out"
            session.tokens = {}
            session.message = summarize_login_message("Account removed")
            continue

        try:
            await get_cached_tms_user(user, allow_full_login=False)
        except LoginFailedException as exc:
            _queue_tms_account_login(user, db, automatic=True, force=True)
        except Exception as exc:
            _queue_tms_account_login(user, db, automatic=True, force=True)

    db.commit()


def _compute_scheduled_live_status(
    *,
    monitoring_active: bool,
    monitor_phase: str,
    scanning_count: int,
    last_monitor_message: str | None = None,
    current_price: float | None = None,
) -> dict:
    has_valid_price = current_price is not None and float(current_price) > 0

    if monitor_phase == "waiting_hours":
        return {
            "live_status": "waiting for market",
            "is_scanning": False,
            "display_error": None,
        }

    if monitor_phase == "waiting_session":
        return {
            "live_status": "waiting for TMS session",
            "is_scanning": False,
            "display_error": None,
        }

    if not monitoring_active or monitor_phase == "stopped":
        return {
            "live_status": "monitor stopped",
            "is_scanning": False,
            "display_error": "Monitor stopped",
        }

    is_scanning = monitor_phase in ("active", "armed") and has_valid_price
    display_error = None

    if not has_valid_price and last_monitor_message:
        detail = last_monitor_message.strip().splitlines()[-1]
        if detail.startswith("TRACKING:"):
            detail = detail.replace("TRACKING:", "", 1).strip()
        display_error = detail[:120] if detail else None

    if is_scanning:
        live_status = "scanning"
    elif display_error:
        live_status = display_error
    else:
        live_status = "scanning"

    return {
        "live_status": live_status,
        "is_scanning": is_scanning,
        "display_error": display_error if not is_scanning else None,
    }


def _last_monitor_log_line(scan_log, *, current_price: float | None = None) -> str | None:
    if not scan_log or not scan_log.logs:
        return None
    lines = [line.strip() for line in str(scan_log.logs).splitlines() if line.strip()]
    has_valid_price = current_price is not None and float(current_price) > 0
    if has_valid_price:
        lines = [line for line in lines if not is_transient_monitor_log_line(line)]
    return lines[-1] if lines else None


def _order_status_log_from_order(order: ScheduledOrder, status: Optional[str] = None) -> OrderStatusLog:
    return status_log_from_scheduled_order(order, status=status)


NON_EDITABLE_SCHEDULED_STATUSES = frozenset({
    "completed",
    "complete",
    "executed",
    "cancelled",
    "canceled",
    "failed",
    "expired",
    "order_placed",
    "order placed",
    "partially executed",
})


def _is_scheduled_order_editable(order: ScheduledOrder) -> bool:
    if order.executed_at:
        return False
    status = (order.status or "").strip().lower()
    return status not in NON_EDITABLE_SCHEDULED_STATUSES


def _scheduled_order_dedup_key(order_data: OrderCreateRequest) -> str:
    strategy_config = dict(order_data.strategy_config or {})
    compiled_plan = strategy_config.get("compiled_plan")
    key_payload = {
        "client_id": (order_data.client_id or "").strip().upper(),
        "script_name": (order_data.script_name or "").strip().upper(),
        "order_type": (order_data.order_type or "").strip().lower(),
        "strategy_type": (order_data.strategy_type or "Fixed Price").strip(),
        "price": float(order_data.price or 0),
        "qty": int(order_data.qty or 0),
        "side": (order_data.side or order_data.order_type or "").strip().lower(),
        "query_text": str(strategy_config.get("query_text") or "").strip(),
        "compiled_plan": compiled_plan or {},
    }
    return json.dumps(key_payload, sort_keys=True, default=str)


def _find_duplicate_scheduled_order(db: Session, order_data: OrderCreateRequest) -> Optional[ScheduledOrder]:
    dedup_key = _scheduled_order_dedup_key(order_data)
    query = db.query(ScheduledOrder).filter(
        ScheduledOrder.client_id == order_data.client_id,
        ScheduledOrder.script_name == order_data.script_name,
        ScheduledOrder.order_type == order_data.order_type,
        ScheduledOrder.strategy_type == (order_data.strategy_type or "Fixed Price"),
    )
    for existing in query.all():
        existing_config = dict(existing.strategy_config or {})
        if existing_config.get("schedule_dedup_key") == dedup_key:
            return existing
        if (
            existing.price == order_data.price
            and existing.qty == order_data.qty
            and str(existing_config.get("query_text") or "").strip() == str((order_data.strategy_config or {}).get("query_text") or "").strip()
        ):
            return existing
    return None


async def _reject_duplicate_scheduled_order(db: Session, order_data: OrderCreateRequest) -> Optional[dict]:
    duplicate = _find_duplicate_scheduled_order(db, order_data)
    if not duplicate:
        return None
    return {
        "message": (
            f"Skipped duplicate order for {order_data.script_name}. "
            f"An equivalent scheduled order already exists (order_id={duplicate.order_id})."
        ),
        "skipped": True,
        "existing_order_id": duplicate.order_id,
        "order": _serialize_scheduled_order(duplicate),
    }


def _serialize_scheduled_order(order: ScheduledOrder) -> dict:
    def ts(value):
        return format_api_timestamp(value)

    reference_display = display_values_from_strategy_config(
        strategy_config=dict(order.strategy_config or {}),
        symbol=order.symbol or order.script_name,
    )
    display_reference_ltp = order.reference_ltp
    if display_reference_ltp is None:
        display_reference_ltp = reference_display.reference_ltp
    display_trigger_price = order.trigger_price
    if display_trigger_price is None:
        display_trigger_price = reference_display.trigger_price
    display_reference_captured_at = order.reference_ltp_captured_at
    if display_reference_captured_at is None:
        display_reference_captured_at = reference_display.reference_ltp_captured_at
    market_open = get_market_hours_status()["market_hours_open"]
    live_snapshot = live_quote_manager.get_snapshot(order.script_name)
    if not market_open and not live_snapshot:
        live_snapshot = {
            "status": "paused_market_closed",
            "last_received_at": None,
            "message_count": None,
            "quote": None,
        }
    live_quote = (live_snapshot or {}).get("quote") or {}

    return {
        "order_id": order.order_id,
        "client_id": order.client_id,
        "security_details": order.security_details or {},
        "script_name": order.script_name,
        "price": order.price,
        "qty": order.qty,
        "status": order.status,
        "order_type": order.order_type,
        "strategy_type": order.strategy_type or "Fixed Price",
        "side": order.side or order.order_type,
        "symbol": order.symbol or order.script_name,
        "company_name": order.company_name,
        "remaining_quantity": order.remaining_quantity,
        "limit_price": order.limit_price,
        "stop_loss_price": order.stop_loss_price,
        "stop_limit_price": order.stop_limit_price,
        "book_profit_price": order.book_profit_price,
        "profit_target_price": order.profit_target_price,
        "trailing_drop_percent": order.trailing_drop_percent,
        "stable_band_percent": order.stable_band_percent,
        "minimum_wait_minutes": order.minimum_wait_minutes,
        "consecutive_drop_checks": order.consecutive_drop_checks,
        "activation_price": order.activation_price,
        "target_reached": order.target_reached,
        "target_reached_at": ts(order.target_reached_at),
        "highest_tracked_price": order.highest_tracked_price,
        "highest_tracked_at": ts(order.highest_tracked_at),
        "protected_price": order.protected_price,
        "average_buy_price": order.average_buy_price,
        "partial_legs": order.partial_legs,
        "executed_legs": order.executed_legs,
        "execution_price": order.execution_price,
        "execution_price_source": order.execution_price_source,
        "execution_reason": order.execution_reason,
        "executed_at": ts(order.executed_at),
        "cancelled_reason": order.cancelled_reason,
        "failed_reason": order.failed_reason,
        "expiry_time": ts(order.expiry_time),
        "expiry_action": order.expiry_action,
        "reference_ltp": display_reference_ltp,
        "trigger_price": display_trigger_price,
        "reference_ltp_captured_at": ts(display_reference_captured_at),
        "drop_percent": order.drop_percent,
        "max_allowed_slippage_percent": order.max_allowed_slippage_percent,
        "emergency_execution": order.emergency_execution,
        "user_allocation": order.user_allocation,
        "last_checked_ltp": order.last_checked_ltp,
        "last_checked_at": ts(order.last_checked_at),
        "socket_quote": live_quote or None,
        "socket_status": (live_snapshot or {}).get("status"),
        "socket_last_received_at": (live_snapshot or {}).get("last_received_at"),
        "socket_message_count": (live_snapshot or {}).get("message_count"),
        "socket_top_buy": live_quote.get("topBuy") or [],
        "socket_top_sell": live_quote.get("topSell") or [],
        "below_stop_loss_check_count": order.below_stop_loss_check_count,
        "consecutive_drop_count": order.consecutive_drop_count,
        "strategy_config": order.strategy_config,
        "scan_price_history": order.scan_price_history,
        "scan_volume_history": order.scan_volume_history,
        "editable": _is_scheduled_order_editable(order),
        "created_at": ts(order.created_at),
        "updated_at": ts(order.updated_at),
        "last_updated": ts(order.last_updated),
    }


def _validate_strategy_order(order_data: OrderCreateRequest) -> None:
    from utils.strategies.aliases import BUY_STRATEGIES, SELL_STRATEGIES, canonical_strategy_name

    strategy = (order_data.strategy_type or "Fixed Price").strip()
    canonical = canonical_strategy_name(strategy, order_data.order_type or "buy")
    side = (order_data.order_type or "buy").lower()
    if side == "buy" and canonical not in BUY_STRATEGIES:
        raise HTTPException(status_code=400, detail=f"{canonical} is not a valid BUY strategy.")
    if side == "sell" and canonical not in SELL_STRATEGIES:
        raise HTTPException(status_code=400, detail=f"{canonical} is not a valid SELL strategy.")

    strategy_config = order_data.strategy_config or {}
    rule_plan = strategy_config.get("compiled_plan") or strategy_config.get("rule_plan")
    is_rule_based = canonical in {
        "Technical Buy", "Technical Sell", "Custom Query Buy", "Custom Query Sell",
    }
    if is_rule_based and not rule_plan and not strategy_config.get("query_text"):
        raise HTTPException(status_code=400, detail="Rule-based strategies require a compiled plan or query text.")
    security_details = order_data.security_details or {}
    odd_lot_allowed = bool(security_details.get("odd_lot_allowed") or security_details.get("oddLotAllowed"))
    lot_size = get_board_lot_size(security_details)
    if order_data.qty <= 0 and not is_rule_based:
        raise HTTPException(status_code=400, detail="Quantity must be greater than zero.")
    if is_rule_based:
        from utils.strategy_builder.constants import DEFAULT_RULE_ORDER_QUANTITY
        from utils.strategy_builder.execution_quantity import plan_uses_holding_dependent_quantity
        from utils.strategy_builder.plan_helpers import extract_planned_quantity_from_compiled_plan

        if isinstance(rule_plan, dict) and plan_uses_holding_dependent_quantity(rule_plan):
            order_data.qty = 0
            order_data.remaining_quantity = 0
        elif order_data.qty <= 0:
            plan_qty = None
            if isinstance(rule_plan, dict):
                plan_qty = extract_planned_quantity_from_compiled_plan(
                    rule_plan,
                    order_data.script_name,
                )
            order_data.qty = plan_qty or DEFAULT_RULE_ORDER_QUANTITY
    if (
        not is_rule_based
        and not odd_lot_allowed
        and order_data.order_type.lower() == "buy"
        and not is_regular_lot_qty(order_data.qty, lot_size)
    ):
        raise HTTPException(status_code=400, detail=f"Quantity must be a board-lot multiple of {lot_size} kitta.")
    if order_data.order_type.lower() == "buy":
        if not is_rule_based and not odd_lot_allowed and order_data.qty < lot_size:
            raise HTTPException(
                status_code=400,
                detail=f"Amount is not enough to buy minimum board lot of {lot_size} kitta.",
            )
        buy_needs_price = {
            "Fixed Price Buy",
            "Smart Pullback Buy",
            "Confirmed Breakout Buy",
            "Buy Below Price",
            "Dip Buy",
            "Breakout Buy",
        }
        if canonical in buy_needs_price and order_data.price <= 0:
            raise HTTPException(status_code=400, detail="Buy trigger price must be greater than zero.")
        if canonical == "Time-Based Buy" and not order_data.expiry_time:
            raise HTTPException(status_code=400, detail="Expiry time is required.")
    if order_data.order_type.lower() == "sell":
        if canonical == "Fixed Price Sell" and order_data.price <= 0:
            raise HTTPException(status_code=400, detail="Sell price must be greater than zero.")
        if canonical == "Capital Protection Sell" and not order_data.stop_loss_price and not order_data.average_buy_price:
            raise HTTPException(status_code=400, detail="Stop-loss trigger or average buy price is required.")
        if strategy == "Stop Limit Sell" and (not order_data.stop_loss_price or not order_data.stop_limit_price):
            raise HTTPException(status_code=400, detail="Stop trigger and limit price are required.")
        if canonical == "Trailing Runner Sell" and (order_data.trailing_drop_percent or 0) <= 0:
            raise HTTPException(status_code=400, detail="Trailing drop percent must be greater than zero.")
        if canonical == "Profit Ladder Sell" and not order_data.partial_legs and not order_data.profit_target_price:
            raise HTTPException(status_code=400, detail="Profit ladder targets are required.")
        if canonical == "Time-Based Exit" and not order_data.expiry_time:
            raise HTTPException(status_code=400, detail="Expiry time is required.")
        if canonical == "Emergency Exit by Top Buyer" and not order_data.emergency_execution:
            raise HTTPException(status_code=400, detail="Emergency exit requires confirmation.")


async def _validate_sell_lot_against_holdings(order_data: OrderCreateRequest, tms_user: TmsUser) -> None:
    from utils.strategy_builder.execution_quantity import is_holding_dependent_mode
    from utils.strategy_builder.execution_sizing import resolve_order_quantity
    from utils.strategy_builder.strategy_models import StrategyPlanAST

    security_details = order_data.security_details or {}
    odd_lot_allowed = bool(security_details.get("odd_lot_allowed") or security_details.get("oddLotAllowed"))
    if odd_lot_allowed:
        return

    lot_size = get_board_lot_size(security_details)
    holdings = await tms_user.get_user_stock_details()
    normalized_symbol = order_data.script_name.strip().upper()
    holding_qty = 0
    for holding in holdings or []:
        scrip = str(holding.get("scrip") or "").strip().upper()
        name = str(holding.get("symbolName") or "").strip().upper()
        if scrip == normalized_symbol or name == normalized_symbol:
            holding_qty = int(float(holding.get("currentBalance") or 0))
            break

    if holding_qty <= 0:
        raise HTTPException(status_code=400, detail=f"{order_data.script_name} is not available in DP holdings.")

    desired_qty = int(order_data.qty or 0)
    config = dict(order_data.strategy_config or {})
    compiled_plan = config.get("compiled_plan")
    dynamic_mode = False
    if compiled_plan:
        try:
            plan = StrategyPlanAST.model_validate(compiled_plan)
            symbol = normalized_symbol
            for rule in plan.rules:
                if symbol not in {item.upper() for item in rule.symbols} or not rule.order:
                    continue
                order_mode = str(rule.order.mode or "quantity").lower()
                if is_holding_dependent_mode(order_mode):
                    dynamic_mode = True
                    break
                desired_qty = resolve_order_quantity(
                    order_mode=order_mode,
                    order_value=rule.order.value,
                    ltp=None,
                    holding_qty=holding_qty,
                    board_lot=lot_size,
                    form_qty=int(order_data.qty or 0),
                )
                break
        except Exception:
            desired_qty = int(order_data.qty or 0)

    if dynamic_mode:
        return

    if desired_qty <= 0:
        return
    if desired_qty > holding_qty:
        raise HTTPException(status_code=400, detail=f"Sell quantity cannot exceed DP holding quantity ({holding_qty}).")

    normalized = normalize_sell_qty(desired_qty, holding_qty, lot_size)
    if not normalized.get("is_sell_all") and normalized.get("qty") != desired_qty:
        raise HTTPException(
            status_code=400,
            detail=normalized.get("error") or normalized.get("warning") or "Sell quantity violates board-lot rules.",
        )


async def _get_script_high(tms_user: TmsUser, script_name: str) -> Optional[float]:
    normalized = script_name.strip().upper()
    security = await tms_user.get_security_id(normalized)
    if security and security.get("id"):
        quote = await tms_user.get_stock_details_async(str(security["id"]), max_retries=2)
        if quote and quote.get("high") is not None:
            return float(quote["high"])

    stock_data = await tms_user.fetch_securities_details()
    for stock in (stock_data or {}).get("payload", {}).get("data", []) or []:
        if str(stock.get("symbol", "")).upper() == normalized and stock.get("high") is not None:
            return float(stock["high"])
    return None


@app.get("/tms-accounts/")
async def list_tms_accounts(db: Session = Depends(get_db), current_user: FrontendUser = Depends(require_permission("tms_login"))):
    users = db.query(User).filter(User.owner_user_id == current_user.id).order_by(User.client_id).all()
    await _reconcile_logged_in_sessions(db, [user.client_id for user in users])
    _queue_ui_auto_logins(db, users)
    sessions = {
        session.client_id: session
        for session in db.query(LoggedInUsers).filter(LoggedInUsers.client_id.in_([user.client_id for user in users])).all()
    }
    account_ids = {user.client_id for user in users}
    user_by_client_id = {user.client_id: user for user in users}
    accounts = [_serialize_tms_account(user, sessions.get(user.client_id)) for user in users]

    for client_id, session in sessions.items():
        if client_id not in account_ids:
            accounts.append({
                "client_id": session.client_id,
                "display_name": _extract_tms_display_name(session),
                "broker_no": session.broker_no or "",
                "auto_login": True,
                "session_status": session.status,
                "session_message": session.message,
                "last_updated": session.last_updated.isoformat() if session.last_updated else None,
                "last_login_at": session.last_login_at.isoformat() if session.last_login_at else None,
                "session_updated_at": session.last_updated.isoformat() if session.last_updated else None,
                "collateral": session.collateral,
                "collateral_error": None if session.collateral else "Collateral not loaded",
            })

    await asyncio.gather(*[
        _attach_tms_account_collateral(
            account,
            user_by_client_id.get(account["client_id"]),
            sessions.get(account["client_id"]),
        )
        for account in accounts
    ])
    accounts.sort(key=lambda account: account["client_id"])
    logged_in = [a for a in accounts if a["session_status"] == "logged_in"]
    return {"accounts": accounts, "logged_in_count": len(logged_in)}


@app.post("/tms-accounts/refresh-collateral")
async def refresh_tms_account_collateral(db: Session = Depends(get_db), current_user: FrontendUser = Depends(require_permission("tms_login"))):
    users = db.query(User).filter(User.owner_user_id == current_user.id).order_by(User.client_id).all()
    results = await asyncio.gather(*[
        _refresh_tms_account_collateral(user)
        for user in users
    ])
    refreshed_count = sum(1 for result in results if result["status"] == "success")
    return {
        "message": f"Refreshed collateral for {refreshed_count} account(s)",
        "refreshed_count": refreshed_count,
        "results": results,
    }


@app.post("/tms-accounts/")
async def create_tms_account(payload: TmsAccountCreate, db: Session = Depends(get_db), current_user: FrontendUser = Depends(require_permission("tms_login"))):
    client_id = payload.client_id.strip()
    if not client_id:
        raise HTTPException(status_code=400, detail="client_id is required")
    if db.query(User).filter(User.client_id == client_id).first():
        raise HTTPException(status_code=409, detail=f"TMS account {client_id} already exists")

    encoded_password = TmsUser.to_tms_password_payload(payload.password)
    user = User(
        owner_user_id=current_user.id,
        client_id=client_id,
        broker_no=payload.broker_no.strip(),
        password=encoded_password,
        auto_login=payload.auto_login,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"message": "TMS account created", "account": _serialize_tms_account(user, None)}


@app.put("/tms-accounts/{client_id}")
async def update_tms_account(
    client_id: str,
    payload: TmsAccountUpdate,
    db: Session = Depends(get_db),
    current_user: FrontendUser = Depends(require_permission("tms_login")),
):
    user = require_owned_client(db, current_user, client_id)

    if payload.broker_no is not None:
        user.broker_no = payload.broker_no.strip()
    if payload.auto_login is not None:
        user.auto_login = payload.auto_login
    if payload.password:
        user.password = TmsUser.to_tms_password_payload(payload.password)
        await invalidate_cached_tms_user(client_id)

    db.commit()
    db.refresh(user)
    session = db.query(LoggedInUsers).filter(LoggedInUsers.client_id == client_id).first()
    return {"message": "TMS account updated", "account": _serialize_tms_account(user, session)}


@app.delete("/tms-accounts/{client_id}")
async def delete_tms_account(client_id: str, db: Session = Depends(get_db), current_user: FrontendUser = Depends(require_permission("tms_login"))):
    user = require_owned_client(db, current_user, client_id)

    login_task = tms_login_tasks.pop(client_id, None)
    if login_task and not login_task.done():
        login_task.cancel()
        await asyncio.gather(login_task, return_exceptions=True)

    db.query(LoggedInUsers).filter(LoggedInUsers.client_id == client_id).delete()
    db.delete(user)
    db.commit()
    await invalidate_cached_tms_user(client_id)
    return {"message": f"TMS account {client_id} deleted"}


@app.post("/tms-accounts/{client_id}/login")
async def login_tms_account(client_id: str, db: Session = Depends(get_db), current_user: FrontendUser = Depends(require_permission("tms_login"))):
    user = require_owned_client(db, current_user, client_id)

    if not _queue_tms_account_login(user, db, automatic=False, force=True):
        return JSONResponse(
            status_code=202,
            content={
                "status": "accepted",
                "message": "TMS login is already in progress",
                "client_id": client_id,
            },
        )

    return JSONResponse(
        status_code=202,
        content={
            "status": "accepted",
            "message": "TMS login started",
            "client_id": client_id,
        },
    )


@app.post("/login/")
async def login(login_request: LoginRequest, db: Session = Depends(get_db), current_user: FrontendUser = Depends(require_permission("tms_login"))):
    require_owned_client(db, current_user, login_request.username)
    enc_password = TmsUser.to_tms_password_payload(login_request.password)
    tms_instance = TmsUser(
        username=login_request.username,
        password=enc_password,
        stock_symbol=login_request.stock_symbol,
        broker_no=login_request.broker_no,
        request_per_sec=login_request.request_per_sec,
    )
    try:
        login_status = await tms_instance.try_cached_login()  # Await the async call
    except LoginFailedException as e:
        _record_tms_login_failure(
            db,
            client_id=login_request.username,
            broker_no=login_request.broker_no,
            message=e.message,
        )
        await tms_instance.close()
        raise HTTPException(status_code=401, detail=e.message)

    if login_status.get("status") == "success":
        await invalidate_cached_tms_user(login_request.username)
        tms_user_cache[login_request.username] = tms_instance
        tms_user_cache_touched[login_request.username] = monotonic_time.monotonic()
        return {"message": login_status}, 200

    failure_detail = (
        login_status.get("message")
        or login_status.get("detail")
        or "Login failed"
    )
    raise HTTPException(status_code=401, detail=failure_detail)


@app.delete("/cancel_order/")
async def cancel_order(client_id: str, exchange_order_id: str, db: Session = Depends(get_db), current_user: FrontendUser = Depends(require_permission("schedule_orders"))):
    try:
        # Retrieve user from the database based on client_id
        user = require_owned_client(db, current_user, client_id)

        tms_user_instance = await get_cached_tms_user(user)

        # Cancel the order
        # Await the async call
        response = await tms_user_instance.cancel_order(exchange_order_id)

        # Return the response
        return response

    except LoginFailedException as e:
        await invalidate_cached_tms_user(client_id)
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def _apply_schedule_baseline_if_requested(order_data: OrderCreateRequest, db: Session) -> None:
    from utils.tms_client_resolver import get_tms_user_for_client
    from utils.strategy_builder.schedule_baseline import (
        ScheduleBaselineError,
        apply_fixed_trigger_to_compiled_plan,
        capture_symbol_baseline_from_tms,
        compile_baseline_strategy_config,
        merge_baseline_into_order_fields,
        normalize_expiration_config,
        reject_self_referential_drop_query,
        validate_expiration_timestamp,
    )
    from utils.strategy_builder.screener_drop_schedule import recalculate_trigger_from_reference
    from utils.strategy_builder.strategy_parser import parse_strategy_query

    strategy_config = dict(order_data.strategy_config or {})
    query_text = str(strategy_config.get("query_text") or "")

    from utils.strategy_builder.reference_dependencies import plan_uses_reference
    from utils.strategy_builder.strategy_models import StrategyPlanAST

    compiled_plan = strategy_config.get("compiled_plan")
    if compiled_plan and plan_uses_reference(StrategyPlanAST.model_validate(compiled_plan)):
        strategy_config["uses_field_references"] = True
        order_data.strategy_config = strategy_config
        if query_text:
            reject_self_referential_drop_query(query_text)
        return

    if strategy_config.get("schedule_baseline") and strategy_config.get("compiled_plan"):
        if not strategy_config.get("refresh_reference_ltp"):
            merge_baseline_into_order_fields(order_data, strategy_config["schedule_baseline"])
            if query_text:
                reject_self_referential_drop_query(query_text)
            return

    if (
        strategy_config.get("capture_reference_ltp")
        and strategy_config.get("recalc_drop_percent_only")
        and order_data.reference_ltp
        and query_text
    ):
        symbol = (order_data.script_name or order_data.symbol or "").strip().upper()
        drop_percent = float(strategy_config.get("drop_percent") or order_data.drop_percent or 10.0)
        trigger_price = recalculate_trigger_from_reference(float(order_data.reference_ltp), drop_percent)
        plan = parse_strategy_query(query_text)
        compiled = apply_fixed_trigger_to_compiled_plan(
            plan.model_dump(),
            symbol=symbol,
            trigger_price=trigger_price,
        )
        baseline = dict(strategy_config.get("schedule_baseline") or {})
        baseline.update(
            {
                "symbol": symbol,
                "reference_ltp": float(order_data.reference_ltp),
                "drop_percent": drop_percent,
                "trigger_price": trigger_price,
            }
        )
        strategy_config["compiled_plan"] = compiled
        strategy_config["schedule_baseline"] = baseline
        strategy_config["drop_percent"] = drop_percent
        order_data.strategy_config = strategy_config
        order_data.trigger_price = trigger_price
        order_data.drop_percent = drop_percent
        return

    if not strategy_config.get("capture_reference_ltp"):
        if query_text:
            reject_self_referential_drop_query(query_text)
        return

    validate_expiration_timestamp(order_data.expiry_time)
    if not query_text:
        raise HTTPException(status_code=400, detail="Strategy query text is required for baseline capture.")

    symbol = (order_data.script_name or order_data.symbol or "").strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="Script name is required for baseline capture.")

    drop_percent = float(strategy_config.get("drop_percent") or 10.0)
    fixed_symbols = strategy_config.get("fixed_symbols")
    if isinstance(fixed_symbols, list) and fixed_symbols:
        if symbol not in {str(item).strip().upper() for item in fixed_symbols}:
            raise HTTPException(
                status_code=400,
                detail=f"{symbol} is not in the fixed symbol list for this schedule.",
            )

    try:
        tms_user = await get_tms_user_for_client(order_data.client_id, db)
        baseline = await capture_symbol_baseline_from_tms(
            tms_user,
            symbol,
            drop_percent=drop_percent,
        )
    except ScheduleBaselineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    expiration = strategy_config.get("expiration")
    if order_data.expiry_time and isinstance(expiration, dict):
        expiration = {**expiration, "expires_at": order_data.expiry_time.isoformat()}

    order_data.strategy_config = compile_baseline_strategy_config(
        query_text=query_text,
        symbol=symbol,
        baseline=baseline,
        expiration=expiration if isinstance(expiration, dict) else None,
        fixed_symbols=fixed_symbols if isinstance(fixed_symbols, list) else [symbol],
    )
    merge_baseline_into_order_fields(order_data, baseline)
    if not order_data.expiry_action:
        order_data.expiry_action = "CANCEL"


async def _persist_order_field_references(db: Session, order: ScheduledOrder, order_data: OrderCreateRequest) -> None:
    strategy_config = dict(order_data.strategy_config or {})
    compiled_plan = strategy_config.get("compiled_plan")
    if not compiled_plan:
        return
    from utils.strategy_builder.reference_dependencies import plan_uses_reference
    from utils.strategy_builder.reference_capture import ReferenceCaptureError
    from utils.strategy_builder.reference_schedule import capture_and_attach_field_references
    from utils.strategy_builder.strategy_models import StrategyPlanAST
    from utils.tms_client_resolver import get_tms_user_for_client

    plan = StrategyPlanAST.model_validate(compiled_plan)
    if not plan_uses_reference(plan):
        return
    try:
        tms_user = await get_tms_user_for_client(order_data.client_id, db)
        order.strategy_config = await capture_and_attach_field_references(
            db=db,
            tms_user=tms_user,
            order_id=order.order_id,
            symbol=order.script_name,
            plan=plan,
            strategy_config=strategy_config,
        )
    except ReferenceCaptureError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail={"code": exc.code, "message": str(exc)}) from exc


async def _enforce_rule_based_schedule_preflight(order_data: OrderCreateRequest, db: Session) -> None:
    from utils.strategies.aliases import canonical_strategy_name
    from utils.strategy_builder.schedule_preflight import run_schedule_preflight

    canonical = canonical_strategy_name(order_data.strategy_type or "", order_data.order_type or "buy")
    if canonical not in {"Technical Buy", "Technical Sell", "Custom Query Buy", "Custom Query Sell"}:
        return

    strategy_config = order_data.strategy_config or {}
    if strategy_config.get("schedule_preflight_ready"):
        return

    result = await run_schedule_preflight(
        query_text=str(strategy_config.get("query_text") or ""),
        compiled_plan=strategy_config.get("compiled_plan"),
        strategy_type=order_data.strategy_type,
        client_id=order_data.client_id,
        script_name=order_data.script_name,
        db=db,
        capture_reference_ltp=bool(strategy_config.get("capture_reference_ltp")),
        drop_percent=float(strategy_config.get("drop_percent") or 10),
        fixed_symbols=strategy_config.get("fixed_symbols"),
    )
    if not result.get("ready"):
        raise HTTPException(
            status_code=400,
            detail={
                "message": result.get("message") or "Cannot schedule this monitored query.",
                "status": result.get("status"),
                "errors": result.get("errors") or [],
            },
        )


def _materialize_lifecycle_schedule(order_data: OrderCreateRequest) -> None:
    """Make a SIDE LIFECYCLE query self-contained for live scheduling.

    A lifecycle schedules its BUY and dormant SELL monitor together.  Existing
    holdings are intentionally not required here: the SELL monitor verifies the
    linked BUY fill, minimum holding sessions, and sellable DP balance later.
    """
    from utils.strategy_builder.strategy_models import (
        ComparisonNode,
        ExecutionConfig,
        FieldNode,
        LiteralNode,
        OrderSizing,
        PositionLifecycleConfig,
        StrategyPlanAST,
    )
    from utils.strategy_builder.strategy_parser import format_strategy_query

    config = dict(order_data.strategy_config or {})
    compiled = config.get("compiled_plan")
    if not compiled:
        return
    try:
        plan = StrategyPlanAST.model_validate(compiled)
    except Exception:
        return
    if not plan.lifecycle:
        return
    if str(order_data.order_type or "").lower() != "buy":
        raise HTTPException(status_code=400, detail="SIDE LIFECYCLE must be scheduled as a BUY entry.")
    if not plan.position_exit:
        raise HTTPException(
            status_code=400,
            detail="SIDE LIFECYCLE requires POSITION_EXIT rules for the linked SELL monitor.",
        )

    # A lifecycle recommendation represents one linear position cycle.  Even
    # legacy/user-authored MAX-N entry clauses are canonicalized to one entry;
    # re-entry is only possible after the linked SELL has closed the position.
    plan.rules = [rule.model_copy(deep=True, update={
        "execution": rule.execution.model_copy(update={
            "frequency": "once_per_symbol",
            "max_times": None,
        }),
    }) for rule in plan.rules]
    lifecycle_config = plan.position_lifecycle
    backtest = plan.backtest
    min_days = max(0, int(
        lifecycle_config.min_holding_days if lifecycle_config is not None
        else backtest.min_holding_days if backtest is not None
        else config.get("min_holding_days", 5)
    ))
    max_days = max(min_days, int(
        lifecycle_config.max_holding_days if lifecycle_config is not None
        else backtest.max_holding_days if backtest is not None
        else config.get("max_holding_days", 90)
    ), 1)

    # BACKTEST assumptions do not participate in broker execution. Convert
    # legacy lifecycle queries to the small runtime-only contract before they
    # are persisted or displayed in Order Logs.
    runtime_lifecycle = lifecycle_config or PositionLifecycleConfig(
        min_holding_days=min_days,
        max_holding_days=max_days,
    )
    plan.backtest = None
    plan.position_lifecycle = runtime_lifecycle
    config["compiled_plan"] = plan.model_dump()
    config["query_text"] = format_strategy_query(plan)

    paired_compiled = config.get("paired_sell_compiled_plan")
    paired_query = str(config.get("paired_sell_query_text") or "").strip()
    if paired_compiled:
        paired_plan = StrategyPlanAST.model_validate(paired_compiled)
        paired_plan.backtest = None
        paired_plan.position_lifecycle = runtime_lifecycle
        paired_plan.rules = [rule.model_copy(deep=True, update={
            "execution": rule.execution.model_copy(update={
                "frequency": "once_per_symbol",
                "max_times": None,
            }),
        }) for rule in paired_plan.rules]
        paired_compiled = paired_plan.model_dump()
        paired_query = format_strategy_query(paired_plan)
    if not paired_compiled:
        symbol = str(order_data.script_name or order_data.symbol or "").strip().upper()
        source_rule = next(
            (rule for rule in plan.rules if symbol in {item.upper() for item in rule.symbols}),
            plan.rules[0] if plan.rules else None,
        )
        if source_rule is None:
            raise HTTPException(status_code=400, detail="SIDE LIFECYCLE requires at least one BUY rule.")
        never_match = ComparisonNode(
            left=FieldNode(name="ltp"),
            operator="lt",
            right=LiteralNode(value=0),
        )
        dormant_rule = source_rule.model_copy(deep=True, update={
            "name": f"{source_rule.name} linked exit",
            "symbols": [symbol],
            "target_type": "single",
            "when": never_match,
            "signal": never_match,
            "eligibility": None,
            "require": None,
            "use_strategy": None,
            "strategy_params": {},
            "order": OrderSizing(mode="all_available", explicit=True),
            "execution": ExecutionConfig(frequency="once_per_symbol"),
        })
        sell_plan = plan.model_copy(deep=True, update={
            "side": "SELL",
            "lifecycle": False,
            "rules": [dormant_rule],
        })
        paired_compiled = sell_plan.model_dump()
        paired_query = format_strategy_query(sell_plan)

    config.update({
        "linear_position_cycle": True,
        "lifecycle_role": "buy",
        "min_holding_days": min_days,
        "max_holding_days": max_days,
        "paired_sell_query_text": paired_query,
        "paired_sell_compiled_plan": paired_compiled,
        "activation_requires_filled_buy": True,
        "activation_requires_holding": True,
        "reentry_requires_closed_position": True,
        "live_charge_policy": dict(config.get("live_charge_policy") or {
            "charge_model": "nepse_equity_v2024_05_14",
            "investor_type": "individual",
            "apply_cgt": True,
            "dp_charge": 25,
        }),
    })
    order_data.strategy_config = config


async def _create_paired_lifecycle_sell(
    db: Session, buy_order: ScheduledOrder, order_data: OrderCreateRequest, *, owner_user_id: int,
) -> Optional[ScheduledOrder]:
    """Create the dormant SELL monitor carried by a validated lifecycle BUY query."""
    config = dict(order_data.strategy_config or {})
    sell_query = str(config.get("paired_sell_query_text") or "").strip()
    sell_compiled = config.get("paired_sell_compiled_plan")
    if order_data.order_type.lower() != "buy" or not config.get("linear_position_cycle") or not sell_query or not sell_compiled:
        return None
    from utils.strategy_builder.strategy_models import StrategyPlanAST

    sell_plan = StrategyPlanAST.model_validate(sell_compiled)
    if sell_plan.side != "SELL":
        raise HTTPException(status_code=400, detail="Lifecycle exit plan must compile as SIDE SELL.")
    min_days = max(0, int(config.get("min_holding_days", 5) or 0))
    max_days = max(min_days, int(config.get("max_holding_days", 90) or 90))
    sell_config = {
        "query_text": sell_query,
        "compiled_plan": sell_plan.model_dump(),
        "execution_mode": "live",
        "linear_position_cycle": True,
        "lifecycle_role": "sell",
        "paired_buy_order_id": buy_order.order_id,
        "activation_requires_filled_buy": True,
        "activation_requires_holding": True,
        "lifecycle_active": False,
        "min_holding_days": min_days,
        "max_holding_days": max_days,
        "source_backtest_result_id": config.get("source_backtest_result_id"),
        "source_backtest_run_id": config.get("source_backtest_run_id"),
        "live_charge_policy": dict(config.get("live_charge_policy") or {
            "charge_model": "nepse_equity_v2024_05_14",
            "investor_type": "individual",
            "apply_cgt": True,
            "dp_charge": 25,
        }),
    }
    sell_request = OrderCreateRequest(
        client_id=order_data.client_id,
        security_details=order_data.security_details or {},
        script_name=order_data.script_name,
        symbol=order_data.symbol or order_data.script_name,
        company_name=order_data.company_name,
        price=0,
        qty=max(1, int(order_data.qty or 1)),
        remaining_quantity=max(1, int(order_data.qty or 1)),
        order_type="sell",
        side="sell",
        status="Waiting activation",
        strategy_type="Custom Query Sell",
        max_allowed_slippage_percent=order_data.max_allowed_slippage_percent,
        odd_lot_allowed=order_data.odd_lot_allowed,
        strategy_config=sell_config,
    )
    duplicate = _find_duplicate_scheduled_order(db, sell_request)
    if duplicate:
        paired_sell = duplicate
    else:
        paired_sell = ScheduledOrder(sell_request)
        paired_sell.owner_user_id = owner_user_id
        db.add(paired_sell)
        db.flush()
        await _persist_order_field_references(db, paired_sell, sell_request)
        paired_sell.strategy_config = dict(paired_sell.strategy_config or {})
        paired_sell.strategy_config["schedule_dedup_key"] = _scheduled_order_dedup_key(sell_request)
    buy_config = dict(buy_order.strategy_config or {})
    buy_config.update({
        "linear_position_cycle": True,
        "lifecycle_role": "buy",
        "paired_sell_order_id": paired_sell.order_id,
        "min_holding_days": min_days,
        "max_holding_days": max_days,
    })
    buy_order.strategy_config = buy_config
    return paired_sell


@app.post("/add_order/")
async def add_order(order_data: OrderCreateRequest, db: Session = Depends(get_db), current_user: FrontendUser = Depends(require_permission("schedule_orders"))):
    require_owned_client(db, current_user, order_data.client_id)
    _materialize_lifecycle_schedule(order_data)
    incoming_security_details = order_data.security_details or {}
    order_data.security_details = {
        **incoming_security_details,
        "odd_lot_allowed": bool(
            order_data.odd_lot_allowed
            or incoming_security_details.get("odd_lot_allowed")
            or incoming_security_details.get("oddLotAllowed")
        ),
    }
    _validate_strategy_order(order_data)
    await _enforce_rule_based_schedule_preflight(order_data, db)
    await _apply_schedule_baseline_if_requested(order_data, db)
    user = db.query(User).filter(User.client_id == order_data.client_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    duplicate_result = await _reject_duplicate_scheduled_order(db, order_data)
    if duplicate_result:
        return duplicate_result

    if order_data.order_type.lower() == "buy":
        from utils.strategies.aliases import canonical_strategy_name

        canonical = canonical_strategy_name(order_data.strategy_type or "Fixed Price", "buy")
        is_rule_based_buy = canonical in {"Technical Buy", "Custom Query Buy"}
        if not is_rule_based_buy:
            tms_user_instance = await get_cached_tms_user(user)
            script_high = await _get_script_high(tms_user_instance, order_data.script_name)
            if script_high is not None:
                order_price = truncate_to_one_decimal_place(order_data.price)
                day_high = truncate_to_one_decimal_place(script_high)
                if order_price > day_high:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"Buy price ({order_price}) cannot exceed today's high "
                            f"({day_high}) for {order_data.script_name}."
                        ),
                    )
    elif order_data.order_type.lower() == "sell":
        tms_user_instance = await get_cached_tms_user(user)
        from utils.strategies.aliases import canonical_strategy_name

        canonical = canonical_strategy_name(order_data.strategy_type or "Fixed Price", "sell")
        is_rule_based_sell = canonical in {"Technical Sell", "Custom Query Sell"}
        if not is_rule_based_sell:
            await _validate_sell_lot_against_holdings(order_data, tms_user_instance)

    order = ScheduledOrder(order_data)
    order.owner_user_id = current_user.id
    db.add(order)
    db.flush()
    await _persist_order_field_references(db, order, order_data)
    order.strategy_config = dict(order.strategy_config or {})
    order.strategy_config["schedule_dedup_key"] = _scheduled_order_dedup_key(order_data)
    from utils.strategy_builder.schedule_preview_capture import apply_schedule_preview_snapshot

    await apply_schedule_preview_snapshot(order, order_data, db)
    paired_sell = await _create_paired_lifecycle_sell(
        db, order, order_data, owner_user_id=current_user.id,
    )
    db.commit()
    return {
        "message": "Lifecycle BUY and linked SELL monitor scheduled" if paired_sell else "Order added successfully",
        "order_id": order.order_id,
        "paired_sell_order_id": paired_sell.order_id if paired_sell else None,
    }


@app.get("/logged_in_clients/")
async def get_logged_in_clients(db: Session = Depends(get_db), current_user: FrontendUser = Depends(require_permission("tms_login"))):
    try:
        owned_accounts = db.query(User).filter(User.owner_user_id == current_user.id).order_by(User.client_id).all()
        await _reconcile_logged_in_sessions(db, [account.client_id for account in owned_accounts])
        _queue_ui_auto_logins(db, owned_accounts)

        owned_ids = [account.client_id for account in owned_accounts]
        logged_in_users = db.query(LoggedInUsers).filter(
            LoggedInUsers.status == "logged_in", LoggedInUsers.client_id.in_(owned_ids)).all()
        client_ids = [user.client_id for user in logged_in_users]
        sessions = [
            {
                "client_id": user.client_id,
                "display_name": _extract_tms_display_name(user),
                "broker_no": user.broker_no or "",
                "status": user.status,
                "message": user.message,
                "last_updated": user.last_updated.isoformat() if user.last_updated else None,
            }
            for user in logged_in_users
        ]
        return {"logged_in_client_ids": client_ids, "sessions": sessions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/delete_scheduled_order/")
async def delete_scheduled_order(
    order_id: int = Query(None),
    client_id: str = Query(None),
    script_name: str = Query(None),
    db: Session = Depends(get_db),
    current_user: FrontendUser = Depends(require_permission("schedule_orders")),
):
    if order_id:
        orders_to_delete = db.query(ScheduledOrder).filter(
            ScheduledOrder.order_id == order_id, ScheduledOrder.owner_user_id == current_user.id).all()
    elif client_id and script_name:
        orders_to_delete = db.query(ScheduledOrder).filter(
            ScheduledOrder.client_id == client_id,
            ScheduledOrder.owner_user_id == current_user.id,
            ScheduledOrder.script_name == script_name
        ).all()
    else:
        raise HTTPException(
            status_code=400, detail="Invalid parameters. Specify order_id or client_id and script_name.")

    if len(orders_to_delete) == 0:
        raise HTTPException(status_code=404, detail="Order not found")

    for order in orders_to_delete:
        db.add(_order_status_log_from_order(order, status="cancelled"))
        db.delete(order)
    for client_id, script_name in {(order.client_id, order.script_name) for order in orders_to_delete}:
        reset_scan_count_after_scheduled_order_removed(db, client_id, script_name)
    db.commit()

    return {"message": "Order deleted successfully"}


@app.delete("/scheduled_orders/batch/{batch_id}")
async def delete_scheduled_order_batch(batch_id: str, db: Session = Depends(get_db), current_user: FrontendUser = Depends(require_permission("schedule_orders"))):
    normalized_batch_id = str(batch_id or "").strip()
    if not normalized_batch_id:
        raise HTTPException(status_code=400, detail="batch_id is required.")

    orders_to_delete = [
        order
        for order in db.query(ScheduledOrder).filter(ScheduledOrder.owner_user_id == current_user.id).all()
        if str((order.strategy_config or {}).get("schedule_batch_id") or "").strip() == normalized_batch_id
    ]
    if not orders_to_delete:
        raise HTTPException(status_code=404, detail="Batch not found.")

    deleted_ids: list[int] = []
    for order in orders_to_delete:
        db.add(_order_status_log_from_order(order, status="cancelled"))
        deleted_ids.append(order.order_id)
        db.delete(order)
    for client_id, script_name in {(order.client_id, order.script_name) for order in orders_to_delete}:
        reset_scan_count_after_scheduled_order_removed(db, client_id, script_name)
    db.commit()

    return {
        "message": f"Deleted {len(deleted_ids)} scheduled order(s) from batch.",
        "batch_id": normalized_batch_id,
        "deleted_order_ids": deleted_ids,
        "deleted_count": len(deleted_ids),
    }


@app.get("/scheduled_orders/")
async def list_scheduled_orders(db: Session = Depends(get_db), current_user: FrontendUser = Depends(require_permission("schedule_orders"))):
    orders = db.query(ScheduledOrder).filter(ScheduledOrder.owner_user_id == current_user.id).order_by(ScheduledOrder.order_id).all()
    return {"scheduled_orders": [_serialize_scheduled_order(order) for order in orders]}


@app.get("/scheduled_orders/{order_id}")
async def get_scheduled_order(order_id: int, db: Session = Depends(get_db), current_user: FrontendUser = Depends(require_permission("schedule_orders"))):
    order = db.query(ScheduledOrder).filter(ScheduledOrder.order_id == order_id, ScheduledOrder.owner_user_id == current_user.id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return {"order": _serialize_scheduled_order(order)}


async def _validate_scheduled_order_payload(order_data: OrderCreateRequest, db: Session) -> None:
    incoming_security_details = order_data.security_details or {}
    order_data.security_details = {
        **incoming_security_details,
        "odd_lot_allowed": bool(
            order_data.odd_lot_allowed
            or incoming_security_details.get("odd_lot_allowed")
            or incoming_security_details.get("oddLotAllowed")
        ),
    }
    _validate_strategy_order(order_data)
    await _enforce_rule_based_schedule_preflight(order_data, db)
    await _apply_schedule_baseline_if_requested(order_data, db)
    user = db.query(User).filter(User.client_id == order_data.client_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if order_data.order_type.lower() == "buy":
        tms_user_instance = await _get_schedule_validation_tms_user(user)
        script_high = await _get_script_high(tms_user_instance, order_data.script_name)
        if script_high is not None:
            order_price = truncate_to_one_decimal_place(order_data.price)
            day_high = truncate_to_one_decimal_place(script_high)
            if order_price > day_high:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Buy price ({order_price}) cannot exceed today's high "
                        f"({day_high}) for {order_data.script_name}."
                    ),
                )
    elif order_data.order_type.lower() == "sell":
        tms_user_instance = await _get_schedule_validation_tms_user(user)
        await _validate_sell_lot_against_holdings(order_data, tms_user_instance)


async def _get_schedule_validation_tms_user(user: User) -> TmsUser:
    try:
        return await get_cached_tms_user(user, allow_full_login=True)
    except LoginFailedException as exc:
        raise HTTPException(
            status_code=401,
            detail=f"TMS login failed while validating the scheduled order: {exc}",
        ) from exc


@app.post("/scheduled_orders/")
async def create_scheduled_order(order_data: OrderCreateRequest, db: Session = Depends(get_db), current_user: FrontendUser = Depends(require_permission("schedule_orders"))):
    require_owned_client(db, current_user, order_data.client_id)
    _materialize_lifecycle_schedule(order_data)
    await _validate_scheduled_order_payload(order_data, db)
    duplicate_result = await _reject_duplicate_scheduled_order(db, order_data)
    if duplicate_result:
        return duplicate_result
    order = ScheduledOrder(order_data)
    order.owner_user_id = current_user.id
    db.add(order)
    db.flush()
    await _persist_order_field_references(db, order, order_data)
    order.strategy_config = dict(order.strategy_config or {})
    order.strategy_config["schedule_dedup_key"] = _scheduled_order_dedup_key(order_data)
    from utils.strategy_builder.schedule_preview_capture import apply_schedule_preview_snapshot

    await apply_schedule_preview_snapshot(order, order_data, db)
    paired_sell = await _create_paired_lifecycle_sell(
        db, order, order_data, owner_user_id=current_user.id,
    )
    db.commit()
    db.refresh(order)
    return {"message": "Scheduled lifecycle created" if paired_sell else "Scheduled order created",
            "order": _serialize_scheduled_order(order),
            "paired_sell_order": _serialize_scheduled_order(paired_sell) if paired_sell else None}


@app.post("/scheduled_orders/{order_id}/references/refresh")
async def refresh_scheduled_order_references(
    order_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: FrontendUser = Depends(require_permission("schedule_orders")),
):
    order = db.query(ScheduledOrder).filter(ScheduledOrder.order_id == order_id, ScheduledOrder.owner_user_id == current_user.id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    payload = await request.json()
    scope = str(payload.get("scope") or "all")
    from utils.strategy_builder.reference_refresh import ReferenceRefreshError, refresh_field_references

    try:
        result = await refresh_field_references(
            db,
            order_id,
            scope=scope,
            rule_name=payload.get("rule_name"),
            symbol=payload.get("symbol"),
            fields=payload.get("fields"),
            refreshed_by=payload.get("client_id") or order.client_id,
        )
        db.commit()
        db.refresh(order)
        return {"message": "References refreshed", **result, "order": _serialize_scheduled_order(order)}
    except ReferenceRefreshError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail={"code": exc.code, "message": str(exc)}) from exc


@app.put("/scheduled_orders/{order_id}")
async def update_scheduled_order(order_id: int, order_data: OrderCreateRequest, db: Session = Depends(get_db), current_user: FrontendUser = Depends(require_permission("schedule_orders"))):
    order = db.query(ScheduledOrder).filter(ScheduledOrder.order_id == order_id, ScheduledOrder.owner_user_id == current_user.id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if not _is_scheduled_order_editable(order):
        raise HTTPException(status_code=400, detail=f"Order with status '{order.status}' cannot be edited")

    if order_data.client_id and order_data.client_id != order.client_id:
        raise HTTPException(status_code=400, detail="Cannot change client on an existing scheduled order")
    if order_data.script_name and order_data.script_name.strip().upper() != (order.script_name or "").strip().upper():
        raise HTTPException(status_code=400, detail="Cannot change script on an existing scheduled order")

    order_data.client_id = order.client_id
    order_data.script_name = order.script_name
    if not order_data.security_details:
        order_data.security_details = order.security_details or {}

    await _validate_scheduled_order_payload(order_data, db)
    order.update_from_request(order_data)
    db.flush()
    await _persist_order_field_references(db, order, order_data)
    order.strategy_config = dict(order.strategy_config or {})
    order.strategy_config["schedule_dedup_key"] = _scheduled_order_dedup_key(order_data)
    from utils.strategy_builder.schedule_preview_capture import apply_schedule_preview_snapshot

    await apply_schedule_preview_snapshot(order, order_data, db)
    db.commit()
    db.refresh(order)
    return {"message": "Scheduled order updated", "order": _serialize_scheduled_order(order)}


@app.delete("/scheduled_orders/")
async def clear_scheduled_orders(db: Session = Depends(get_db), current_user: FrontendUser = Depends(require_permission("schedule_orders"))):
    orders_to_delete = db.query(ScheduledOrder).filter(ScheduledOrder.owner_user_id == current_user.id).all()
    deleted_count = db.query(ScheduledOrder).filter(ScheduledOrder.owner_user_id == current_user.id).delete(synchronize_session=False)
    for client_id, script_name in {(order.client_id, order.script_name) for order in orders_to_delete}:
        delete_order_log_scan_count(db, client_id, script_name)
    db.commit()
    return {"message": f"Deleted {deleted_count} scheduled order(s)"}


@app.post("/update_monitor_interval")
async def update_monitor_interval(request: Request):
    from config.portal_settings import (
        MAX_SCAN_INTERVAL_SECONDS,
        MIN_SCAN_INTERVAL_SECONDS,
        save_portal_settings,
    )

    data = await request.json()
    monitor_interval = data.get("monitor_interval")
    if monitor_interval is None:
        return JSONResponse({"error": "monitor_interval not provided"}, status_code=400)
    try:
        value = int(monitor_interval)
    except (TypeError, ValueError):
        return JSONResponse({"error": "monitor_interval must be a number"}, status_code=400)
    if value < MIN_SCAN_INTERVAL_SECONDS or value > MAX_SCAN_INTERVAL_SECONDS:
        return JSONResponse(
            {
                "error": f"monitor_interval must be between {MIN_SCAN_INTERVAL_SECONDS} and {MAX_SCAN_INTERVAL_SECONDS}",
            },
            status_code=400,
        )
    settings = save_portal_settings({"monitor_interval_seconds": value})
    return {
        "message": "Monitor interval updated successfully",
        "new_interval": settings["monitor_interval_seconds"],
        "monitor_interval": settings["monitor_interval_seconds"],
    }


@app.get("/get_monitor_interval")
async def get_monitor_interval():
    from config.portal_settings import get_portal_settings

    settings = get_portal_settings()
    return {"monitor_interval": settings["monitor_interval_seconds"]}


@app.get("/api/portal-settings/")
async def read_portal_settings():
    from config.portal_settings import (
        MAX_MAX_DATA_AGE_SECONDS,
        MAX_MAX_PRICE_FETCH_CONCURRENCY,
        MAX_MONITOR_TICK_SECONDS,
        MAX_NEPSE_ALPHA_INTERVAL_SECONDS,
        MAX_SCAN_INTERVAL_SECONDS,
        MIN_MAX_DATA_AGE_SECONDS,
        MIN_MAX_PRICE_FETCH_CONCURRENCY,
        MIN_MONITOR_TICK_SECONDS,
        MIN_NEPSE_ALPHA_INTERVAL_SECONDS,
        MIN_SCAN_INTERVAL_SECONDS,
        get_portal_settings,
    )

    return {
        "settings": get_portal_settings(),
        "limits": {
            "monitor_interval_seconds": {
                "min": MIN_SCAN_INTERVAL_SECONDS,
                "max": MAX_SCAN_INTERVAL_SECONDS,
            },
            "default_max_data_age_seconds": {
                "min": MIN_MAX_DATA_AGE_SECONDS,
                "max": MAX_MAX_DATA_AGE_SECONDS,
            },
            "nepse_alpha_interval_seconds": {
                "min": MIN_NEPSE_ALPHA_INTERVAL_SECONDS,
                "max": MAX_NEPSE_ALPHA_INTERVAL_SECONDS,
            },
            "monitor_tick_seconds": {
                "min": MIN_MONITOR_TICK_SECONDS,
                "max": MAX_MONITOR_TICK_SECONDS,
            },
            "max_price_fetch_concurrency": {
                "min": MIN_MAX_PRICE_FETCH_CONCURRENCY,
                "max": MAX_MAX_PRICE_FETCH_CONCURRENCY,
            },
        },
    }


@app.put("/api/portal-settings/")
async def update_portal_settings(request: Request):
    from config.portal_settings import (
        MAX_MAX_DATA_AGE_SECONDS,
        MAX_MAX_PRICE_FETCH_CONCURRENCY,
        MAX_MONITOR_TICK_SECONDS,
        MAX_NEPSE_ALPHA_INTERVAL_SECONDS,
        MAX_SCAN_INTERVAL_SECONDS,
        MIN_MAX_DATA_AGE_SECONDS,
        MIN_MAX_PRICE_FETCH_CONCURRENCY,
        MIN_MONITOR_TICK_SECONDS,
        MIN_NEPSE_ALPHA_INTERVAL_SECONDS,
        MIN_SCAN_INTERVAL_SECONDS,
        save_portal_settings,
    )

    data = await request.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Invalid settings payload.")
    settings = save_portal_settings(data)
    return {
        "settings": settings,
        "limits": {
            "monitor_interval_seconds": {
                "min": MIN_SCAN_INTERVAL_SECONDS,
                "max": MAX_SCAN_INTERVAL_SECONDS,
            },
            "default_max_data_age_seconds": {
                "min": MIN_MAX_DATA_AGE_SECONDS,
                "max": MAX_MAX_DATA_AGE_SECONDS,
            },
            "nepse_alpha_interval_seconds": {
                "min": MIN_NEPSE_ALPHA_INTERVAL_SECONDS,
                "max": MAX_NEPSE_ALPHA_INTERVAL_SECONDS,
            },
            "monitor_tick_seconds": {
                "min": MIN_MONITOR_TICK_SECONDS,
                "max": MAX_MONITOR_TICK_SECONDS,
            },
            "max_price_fetch_concurrency": {
                "min": MIN_MAX_PRICE_FETCH_CONCURRENCY,
                "max": MAX_MAX_PRICE_FETCH_CONCURRENCY,
            },
        },
    }
    
@app.get("/order_status_logs/")
async def get_order_status_logs(
    client_id: str = Query(None),
    script_name: str = Query(None),
    ordered_date: str = Query(None),
    db: Session = Depends(get_db),
    current_user: FrontendUser = Depends(require_permission("order_logs")),
):
    query = db.query(OrderStatusLog).filter(OrderStatusLog.owner_user_id == current_user.id)

    # Apply filters based on provided parameters
    if client_id:
        query = query.filter(OrderStatusLog.client_id == client_id)
    if script_name:
        query = query.filter(OrderStatusLog.script_name == script_name)

    # Treat ordered_date as a Nepal calendar day, then compare against UTC-naive DB timestamps.
    if ordered_date and ordered_date!='null':
        try:
            parsed_date = datetime.strptime(ordered_date, "%Y-%m-%d").date()
            start_utc, end_utc = nepal_date_utc_bounds(parsed_date)
            query = query.filter(OrderStatusLog.deleted_at.is_(None))
            query = query.filter(
                cast(OrderStatusLog.timestamp, DateTime) >= start_utc)
            query = query.filter(
                cast(OrderStatusLog.timestamp, DateTime) < end_utc)
        except ValueError:
            return {"error": "Invalid date format. Please use YYYY-MM-DD."}
    else:
        start_utc, end_utc = nepal_date_utc_bounds(get_nepal_now().date())
        query = query.filter(OrderStatusLog.deleted_at.is_(None))
        query = query.filter(cast(OrderStatusLog.timestamp, DateTime) >= start_utc)
        query = query.filter(
            cast(OrderStatusLog.timestamp, DateTime) < end_utc)

    order_logs = query.all()

    scheduled_query = db.query(ScheduledOrder).filter(ScheduledOrder.owner_user_id == current_user.id)
    if client_id:
        scheduled_query = scheduled_query.filter(ScheduledOrder.client_id == client_id)
    if script_name:
        scheduled_query = scheduled_query.filter(ScheduledOrder.script_name == script_name)
    scheduled_orders = scheduled_query.all()

    scan_logs: Dict[tuple, OrderLog] = {}
    if scheduled_orders:
        pair_filters = [
            and_(OrderLog.client_id == order.client_id, OrderLog.script_name == order.script_name)
            for order in scheduled_orders
        ]
        if pair_filters:
            for scan_log in db.query(OrderLog).filter(OrderLog.owner_user_id == current_user.id, or_(*pair_filters)).all():
                scan_logs[(scan_log.client_id, scan_log.script_name)] = scan_log

    scheduled_payload = []
    scheduler_status = get_scheduler_display_status()
    monitor_phase = scheduler_status["scheduled_phase"]
    market_open = get_market_hours_status()["market_hours_open"]
    status_checked_at = get_nepal_now()
    for order in scheduled_orders:
        live_snapshot = live_quote_manager.get_snapshot(order.script_name)
        if not market_open and not live_snapshot:
            live_snapshot = {
                "status": "paused_market_closed",
                "last_received_at": None,
                "message_count": None,
                "quote": None,
            }
        live_quote = (live_snapshot or {}).get("quote") or {}
        scan_log = scan_logs.get((order.client_id, order.script_name))
        scanning_count = int(scan_log.scanning_count or 0) if scan_log else 0
        requires_nepse_alpha = order_requires_nepse_alpha(order)
        current_price_val = (
            float(scan_log.current_price)
            if scan_log and scan_log.current_price is not None
            else None
        )
        last_monitor_message = _last_monitor_log_line(scan_log, current_price=current_price_val)
        live_status_fields = _compute_scheduled_live_status(
            monitoring_active=scheduler_status["scheduled_orders_active"],
            monitor_phase=monitor_phase,
            scanning_count=scanning_count,
            last_monitor_message=last_monitor_message,
            current_price=current_price_val,
        )
        reference_display = display_values_for_scheduled_order(db, order)
        display_reference_ltp = order.reference_ltp
        if display_reference_ltp is None:
            display_reference_ltp = reference_display.reference_ltp
        display_trigger_price = order.trigger_price
        if display_trigger_price is None:
            display_trigger_price = reference_display.trigger_price
        display_reference_captured_at = order.reference_ltp_captured_at
        if display_reference_captured_at is None:
            display_reference_captured_at = reference_display.reference_ltp_captured_at
        scheduled_payload.append({
            "order_id": order.order_id,
            "client_id": order.client_id,
            "script_name": order.script_name,
            "price": int(round(order.price)) if order.price is not None else order.price,
            "qty": int(order.qty) if order.qty is not None else order.qty,
            "status": order.status,
            "order_type": order.order_type,
            "strategy_type": order.strategy_type or "Fixed Price",
            "side": order.side or order.order_type,
            "created_at": format_api_timestamp(order.created_at),
            "remaining_quantity": order.remaining_quantity,
            "stop_loss_price": order.stop_loss_price,
            "stop_limit_price": order.stop_limit_price,
            "book_profit_price": order.book_profit_price,
            "profit_target_price": order.profit_target_price,
            "trailing_drop_percent": order.trailing_drop_percent,
            "stable_band_percent": order.stable_band_percent,
            "minimum_wait_minutes": order.minimum_wait_minutes,
            "consecutive_drop_checks": order.consecutive_drop_checks,
            "activation_price": order.activation_price,
            "average_buy_price": order.average_buy_price,
            "highest_tracked_price": order.highest_tracked_price,
            "target_reached_at": format_api_timestamp(order.target_reached_at),
            "execution_price": order.execution_price,
            "execution_price_source": order.execution_price_source,
            "execution_reason": order.execution_reason,
            "executed_at": format_api_timestamp(order.executed_at),
            "expiry_time": format_api_timestamp(order.expiry_time),
            "expiry_action": order.expiry_action,
            "reference_ltp": display_reference_ltp,
            "trigger_price": display_trigger_price,
            "reference_ltp_captured_at": format_api_timestamp(display_reference_captured_at),
            "drop_percent": order.drop_percent,
            "max_allowed_slippage_percent": order.max_allowed_slippage_percent,
            "user_allocation": order.user_allocation,
            "partial_legs": order.partial_legs,
            "requested_price": order.price,
            "last_checked_ltp": order.last_checked_ltp,
            "socket_quote": live_quote or None,
            "socket_status": (live_snapshot or {}).get("status"),
            "socket_last_received_at": (live_snapshot or {}).get("last_received_at"),
            "socket_message_count": (live_snapshot or {}).get("message_count"),
            "socket_top_buy": live_quote.get("topBuy") or [],
            "socket_top_sell": live_quote.get("topSell") or [],
            "strategy_config": order.strategy_config,
            "requires_nepse_alpha": requires_nepse_alpha,
            "nepse_alpha_scan_count": (
                int(
                    getattr(order, "nepse_alpha_scan_count", None)
                    or (order.strategy_config or {}).get("nepse_alpha_scan_count")
                    or 0
                )
                if requires_nepse_alpha
                else None
            ),
            "nepse_alpha_last_source": (
                getattr(order, "nepse_alpha_last_source", None)
                or (order.strategy_config or {}).get("nepse_alpha_last_source")
                if requires_nepse_alpha
                else None
            ),
            "nepse_alpha_last_fetched_at": (
                getattr(order, "nepse_alpha_last_fetched_at", None)
                or (order.strategy_config or {}).get("nepse_alpha_last_fetched_at")
                if requires_nepse_alpha
                else None
            ),
            "tms_scan_count": int(
                getattr(order, "tms_scan_count", None)
                or (order.strategy_config or {}).get("tms_scan_count")
                or scanning_count
            ),
            "security_details": order.security_details or {},
            "editable": _is_scheduled_order_editable(order),
            "failed_reason": order.failed_reason,
            "cancelled_reason": order.cancelled_reason,
            "scanning_count": scanning_count,
            "current_price": int(round(current_price_val)) if current_price_val is not None else None,
            "status_checked_at": format_api_timestamp(status_checked_at),
            "last_monitor_at": format_api_timestamp(scan_log.timestamp)
            if scan_log
            else None,
            "last_scan_at": format_api_timestamp(scan_log.timestamp)
            if scan_log and is_continuous_market_timestamp(scan_log.timestamp)
            else None,
            **live_status_fields,
            "last_monitor_message": last_monitor_message,
            "monitor_logs": scan_log.logs if scan_log and scan_log.logs else None,
        })

    combined_results = {
        "order_logs": [serialize_order_status_log(log) for log in order_logs],
        "scheduled_orders": scheduled_payload,
        "monitoring_active": scheduler_status["scheduled_orders_active"],
        "monitor_phase": monitor_phase,
        "monitor_status_message": scheduler_status["scheduled_status_message"],
        "scheduled_started_at": format_api_timestamp(tms_config.scheduled_started_at),
        "monitor_interval": tms_config.monitor_interval,
        "server_time": get_server_time_payload()["now"],
    }

    return combined_results


@app.delete("/order_status_logs/clear")
async def clear_order_status_logs(client_ids: str = Query(...), db: Session = Depends(get_db), current_user: FrontendUser = Depends(require_permission("order_logs"))):
    if not client_ids or not client_ids.strip():
        raise HTTPException(status_code=400, detail="Client IDs cannot be empty.")

    parsed_client_ids = [item.strip() for item in client_ids.split(",") if item.strip()]
    if not parsed_client_ids:
        raise HTTPException(status_code=400, detail="Client IDs cannot be empty.")

    try:
        updated_count = (
            db.query(OrderStatusLog)
            .filter(OrderStatusLog.owner_user_id == current_user.id)
            .filter(OrderStatusLog.client_id.in_(parsed_client_ids))
            .filter(OrderStatusLog.deleted_at.is_(None))
            .update({OrderStatusLog.deleted_at: datetime.utcnow()}, synchronize_session=False)
        )
        delete_order_log_scan_counts_for_client_ids(db, parsed_client_ids)
        db.commit()
        if updated_count == 0:
            raise HTTPException(status_code=404, detail="No order logs found for the specified client IDs.")
        return {"message": f"Cleared {updated_count} order log(s).", "deleted_count": updated_count}
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to clear order logs: {exc}")


# @app.websocket("/ws")
# async def websocket_endpoint(websocket: WebSocket):
#     await websocket.accept()
#     active_websockets[websocket] = ""
#     try:
#         while True:
#             await asyncio.sleep(5)  # Keep WebSocket connection alive
#     except WebSocketDisconnect:
#         del active_websockets[websocket]
#     except websockets.ConnectionClosedOK:
#         del active_websockets[websocket]


@app.get("/order_history")
async def get_order_history(client_id: str, db: Session = Depends(get_db), current_user: FrontendUser = Depends(require_permission("order_logs"))):
    user = require_owned_client(db, current_user, client_id)

    try:
        tms_user = await get_cached_tms_user(user)
        order_history = await tms_user.get_order_history()  # Await the async call
        return order_history
    except LoginFailedException as e:
        await invalidate_cached_tms_user(client_id)
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/tradebook_history")
async def get_tradebook_history(
    client_id: str,
    from_date: str,
    to_date: str,
    force_refresh: bool = False,
    db: Session = Depends(get_db),
    current_user: FrontendUser = Depends(require_permission("portfolio")),
):
    user = require_owned_client(db, current_user, client_id)

    try:
        start = date.fromisoformat(from_date)
        end = date.fromisoformat(to_date)
        if start > end:
            return {"rows": [], "positions": []}
        tms_user = await get_cached_tms_user(user)
        history_rows = _cached_trade_rows(db, client_id, start, end)
        full_start, full_end = _cached_trade_date_bounds(db, client_id)
        positions_source = _cached_trade_rows(db, client_id, full_start, full_end) if full_start and full_end else history_rows
        if history_rows and not force_refresh:
            if _should_refresh_trade_range(db, client_id, start, end, force=False):
                asyncio.create_task(_refresh_trade_cache_background(client_id, start, end))
            positions = _build_trade_positions(positions_source)
            return {"rows": history_rows, "positions": positions}
        await _refresh_tradebook_cache(db, tms_user, client_id, start, end, force=force_refresh)
        history_rows = _cached_trade_rows(db, client_id, start, end)
        full_start, full_end = _cached_trade_date_bounds(db, client_id)
        positions_source = _cached_trade_rows(db, client_id, full_start, full_end) if full_start and full_end else history_rows
        positions = _build_trade_positions(positions_source)
        return {"rows": history_rows, "positions": positions}
    except LoginFailedException as e:
        await invalidate_cached_tms_user(client_id)
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/dp_holdings")
async def get_dp_holdings(client_id: str, force_refresh: bool = Query(False), db: Session = Depends(get_db), current_user: FrontendUser = Depends(require_permission("portfolio"))):
    user = require_owned_client(db, current_user, client_id)

    hours = get_market_hours_status()
    cached_holdings = _load_dp_holdings_cache(db, client_id)
    should_try_live = force_refresh or hours["market_hours_open"]

    if not should_try_live:
        return cached_holdings

    try:
        tms_user = await get_cached_tms_user(user, allow_full_login=True)
        enriched_holdings = await _build_live_dp_holdings(db, tms_user, client_id)
        _save_dp_holdings_cache(
            db,
            client_id,
            enriched_holdings,
            source="live",
            market_phase="open" if hours["market_hours_open"] else "closed",
        )
        return enriched_holdings
    except LoginFailedException as e:
        if cached_holdings:
            return cached_holdings
        await invalidate_cached_tms_user(client_id)
        return cached_holdings
    except Exception as e:
        if cached_holdings:
            return cached_holdings
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stock_quote")
async def get_stock_quote(
    client_id: str,
    symbol: str,
    fresh: bool = False,
    transport: str = "auto",
    db: Session = Depends(get_db),
    current_user: FrontendUser = Depends(require_permission("stock_table")),
):
    try:
        user = require_owned_client(db, current_user, client_id)

        tms_user_instance = await get_cached_tms_user(user)

        security = await tms_user_instance.get_security_id(symbol)
        if not security or not security.get("id"):
            raise HTTPException(status_code=404, detail=f"Security not found for {symbol}")

        market_open = get_market_hours_status()["market_hours_open"]
        normalized_transport = str(transport or "auto").strip().lower()
        live_snapshot = None
        quote = None
        source = "http"
        if normalized_transport != "http" and market_open:
            await live_quote_manager.ensure_stream(tms_user_instance, symbol, str(security["id"]))
        live_snapshot = await live_quote_manager.wait_for_quote(symbol)
        quote = (live_snapshot or {}).get("quote")
        source = "socket" if is_live_socket_snapshot(live_snapshot) else "http"
        if quote is None:
            quote = await tms_user_instance.get_stock_details_async(
                str(security["id"]),
                max_retries=3,
                retry_backoff=True,
                force_refresh=fresh or normalized_transport == "http",
            )
        if not quote:
            return {
                "security": security,
                "quote": None,
                "quote_source": source,
                "socket": live_quote_manager.get_snapshot(symbol),
            }

        return {
            "security": security,
            "quote": quote,
            "quote_source": source,
            "socket": live_quote_manager.get_snapshot(symbol),
        }

    except LoginFailedException as e:
        await invalidate_cached_tms_user(client_id)
        raise HTTPException(status_code=401, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.websocket("/ws/stock_quote")
async def websocket_stock_quote(
    websocket: WebSocket,
    client_id: str,
    symbol: str,
    token: str = Query(...),
    allow_market_closed: bool = Query(False),
):
    db = SessionLocal()
    normalized_symbol = str(symbol or "").strip().upper()
    try:
        await websocket.accept()
        try:
            frontend_user = authenticate_token(token, db)
            user = require_owned_client(db, frontend_user, client_id)
        except HTTPException as exc:
            await websocket.send_json({"type": "error", "message": str(exc.detail)})
            await websocket.close(code=1008)
            return

        async def close_for_market_closed(snapshot: Optional[dict] = None) -> None:
            live_state = snapshot or live_quote_manager.get_snapshot(normalized_symbol) or {}
            await live_quote_manager.close_symbol(normalized_symbol)
            try:
                await websocket.send_json({
                    "type": "market_closed",
                    "message": outside_market_hours_message(),
                    "socket": live_state,
                })
            except Exception:
                pass
            await websocket.close(code=1001)

        if not allow_market_closed and not get_market_hours_status()["market_hours_open"]:
            await close_for_market_closed()
            return

        tms_user_instance = await get_cached_tms_user(user)
        security = await tms_user_instance.get_security_id(normalized_symbol)
        if not security or not security.get("id"):
            await websocket.send_json({
                "type": "error",
                "message": f"Security not found for {normalized_symbol}",
            })
            await websocket.close(code=1008)
            return

        await live_quote_manager.ensure_stream(
            tms_user_instance,
            normalized_symbol,
            str(security["id"]),
            allow_market_closed=allow_market_closed,
        )
        if not allow_market_closed and not get_market_hours_status()["market_hours_open"]:
            await close_for_market_closed()
            return
        live_snapshot = await live_quote_manager.wait_for_quote(
            normalized_symbol,
            allow_market_closed=allow_market_closed,
        )

        async def send_snapshot(snapshot: Optional[dict]) -> None:
            live_state = snapshot or live_quote_manager.get_snapshot(normalized_symbol)
            quote = (live_state or {}).get("quote")
            source = "socket" if is_live_socket_snapshot(live_state) else "http"
            payload = {
                "type": "quote",
                "security": security,
                "quote": quote,
                "quote_source": source,
                "socket": live_state,
            }
            await websocket.send_json(payload)

        async def close_for_auth_failure(snapshot: Optional[dict]) -> None:
            live_state = snapshot or live_quote_manager.get_snapshot(normalized_symbol) or {}
            message = str(live_state.get("last_error") or "Authentication expired. Please log in again.")
            try:
                await websocket.send_json({
                    "type": "error",
                    "message": message,
                    "socket": live_state,
                })
            except Exception:
                pass
            await live_quote_manager.close_symbol(normalized_symbol)
            await websocket.close(code=1008)

        await send_snapshot(live_snapshot)
        last_message_count = int((live_snapshot or {}).get("message_count") or 0)
        if live_quote_manager.is_authentication_failed(normalized_symbol):
            await close_for_auth_failure(live_snapshot)
            return

        while True:
            if not allow_market_closed and not get_market_hours_status()["market_hours_open"]:
                await close_for_market_closed(live_quote_manager.get_snapshot(normalized_symbol))
                return
            snapshot = await live_quote_manager.wait_for_next_quote(
                normalized_symbol,
                after_message_count=last_message_count,
                timeout=25.0,
                allow_market_closed=allow_market_closed,
            )
            if snapshot and snapshot.get("quote"):
                last_message_count = int(snapshot.get("message_count") or last_message_count)
                await send_snapshot(snapshot)
                continue
            current_snapshot = live_quote_manager.get_snapshot(normalized_symbol) or {}
            if not allow_market_closed and not get_market_hours_status()["market_hours_open"]:
                await close_for_market_closed(current_snapshot)
                return
            if current_snapshot.get("auth_failed") or current_snapshot.get("status") == "auth_failed":
                await close_for_auth_failure(current_snapshot)
                return
            if current_snapshot.get("status") in {"failed", "closed"}:
                await live_quote_manager.close_symbol(normalized_symbol)
                await live_quote_manager.ensure_stream(
                    tms_user_instance,
                    normalized_symbol,
                    str(security["id"]),
                    force_restart=True,
                    allow_market_closed=allow_market_closed,
                )
                restarted_snapshot = await live_quote_manager.wait_for_quote(
                    normalized_symbol,
                    allow_market_closed=allow_market_closed,
                )
                await send_snapshot(restarted_snapshot)
                last_message_count = int((restarted_snapshot or {}).get("message_count") or 0)
                continue
            await websocket.send_json({
                "type": "heartbeat",
                "socket": current_snapshot,
            })
    except WebSocketDisconnect:
        return
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        db.close()


@app.get("/get_order_book")
async def get_order_book(client_id: str, db: Session = Depends(get_db), current_user: FrontendUser = Depends(require_permission("tms_login"))):
    require_owned_client(db, current_user, client_id)
    try:
        user = db.query(User).filter(User.client_id == client_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        tms_user_instance = await get_cached_tms_user(user)

        order_book = await tms_user_instance.get_normalized_order_book()
        return order_book

    except LoginFailedException as e:
        await invalidate_cached_tms_user(client_id)
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/get_daily_order_book")
async def get_daily_order_book(client_id: str, db: Session = Depends(get_db), current_user: FrontendUser = Depends(require_permission("tms_login"))):
    require_owned_client(db, current_user, client_id)
    try:
        user = db.query(User).filter(User.client_id == client_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        tms_user_instance = await get_cached_tms_user(user)
        return await tms_user_instance.get_normalized_daily_order_book()

    except LoginFailedException as e:
        await invalidate_cached_tms_user(client_id)
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/get_script_details")
async def get_script_details(client_id: str, force_refresh: bool = Query(False), db: Session = Depends(get_db), current_user: FrontendUser = Depends(require_permission("tms_login"))):
    require_owned_client(db, current_user, client_id)
    try:
        user = db.query(User).filter(User.client_id == client_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        tms_user_instance = await get_cached_tms_user(
            user,
            allow_full_login=force_refresh or get_market_hours_status()["market_hours_open"],
        )

        stock_data = await tms_user_instance.fetch_securities_details()  # Await the async call
        return stock_data

    except LoginFailedException as e:
        await invalidate_cached_tms_user(client_id)
        return {"payload": {"data": []}, "message": str(e)}
    except Exception as e:
        return {"payload": {"data": []}, "message": str(e)}


@app.post("/tms-accounts/login-all")
async def login_all_tms_accounts(db: Session = Depends(get_db), current_user: FrontendUser = Depends(require_permission("tms_login"))):
    users = db.query(User).filter(User.owner_user_id == current_user.id).order_by(User.client_id).all()
    results = []

    for user in users:
        try:
            await invalidate_cached_tms_user(user.client_id)
            await get_cached_tms_user(user, allow_full_login=True)
            results.append({
                "client_id": user.client_id,
                "status": "logged_in",
                "message": "Login succeeded",
            })
        except LoginFailedException as exc:
            results.append({
                "client_id": user.client_id,
                "status": "failed",
                "message": exc.message,
            })
        except Exception as exc:
            results.append({
                "client_id": user.client_id,
                "status": "failed",
                "message": str(exc),
            })

    logged_in_count = (
        db.query(LoggedInUsers)
        .filter(LoggedInUsers.status == "logged_in")
        .count()
    )
    return {
        "message": f"Login attempt completed for {len(users)} account(s)",
        "attempted_count": len(users),
        "logged_in_count": logged_in_count,
        "results": results,
    }


@app.get("/stock_screener/fields")
async def stock_screener_fields(db: Session = Depends(get_db)):
    from utils.market_data.request_workers import worker_get_fields

    return await asyncio.to_thread(worker_get_fields)


async def _resolve_screener_symbols_for_request(body, db: Session) -> List[str]:
    return await resolve_analysis_symbols(
        universe=getattr(body, "universe", "nepse") or "nepse",
        client_id=body.client_id,
        client_ids=body.client_ids,
        symbols=body.symbols,
        db=db,
    )


@app.get("/market_analysis/status")
async def market_analysis_status(db: Session = Depends(get_db)):
    from utils.market_data.nonblocking_cache import get_bootstrap_status, kickoff_cache_bootstrap_if_empty
    from utils.market_data.refresh_job import get_market_refresh_status
    from utils.market_data.request_workers import worker_get_status

    cache_meta = await kickoff_cache_bootstrap_if_empty()
    payload = await asyncio.to_thread(worker_get_status)
    payload["cache_meta"] = cache_meta
    payload["bootstrap"] = get_bootstrap_status()
    payload["refresh"] = get_market_refresh_status()
    return payload


@app.get("/market_analysis/new_stocks")
async def market_analysis_new_stocks(days: int = Query(15, ge=1, le=365), db: Session = Depends(get_db)):
    from utils.market_data.request_workers import worker_get_new_stocks

    return await asyncio.to_thread(worker_get_new_stocks, days)


@app.post("/market_analysis/new_stocks/{symbol}/remove")
async def market_analysis_remove_new_stock(symbol: str):
    from utils.market_data.request_workers import worker_update_new_stocks_watchlist

    return await asyncio.to_thread(worker_update_new_stocks_watchlist, [symbol], is_watchlist=False)


@app.post("/market_analysis/new_stocks/restore")
async def market_analysis_restore_new_stocks(symbols: List[str] = Body(default_factory=list)):
    from utils.market_data.request_workers import worker_update_new_stocks_watchlist

    return await asyncio.to_thread(worker_update_new_stocks_watchlist, symbols, is_watchlist=True)


@app.get("/market_analysis/data")
async def market_analysis_data(
    source: str = Query("combined", pattern="^(combined|sharesansar|merolagani|nepse_alpha|technical|recommendations)$"),
    db: Session = Depends(get_db),
    current_user: FrontendUser = Depends(require_permission("market_analysis")),
):
    from utils.market_data.nonblocking_cache import kickoff_cache_bootstrap_if_empty
    from utils.market_data.request_workers import worker_get_market_data

    cache_meta = await kickoff_cache_bootstrap_if_empty()
    payload = await asyncio.to_thread(worker_get_market_data, source, str(current_user.id))
    payload["cache_meta"] = cache_meta
    return payload


@app.post("/market_analysis/refresh")
async def market_analysis_refresh(db: Session = Depends(get_db)):
    from utils.market_data.nonblocking_cache import get_bootstrap_status
    from utils.market_data.refresh_job import get_market_refresh_status, start_market_refresh_background

    if get_market_refresh_status().get("running"):
        cache_status = await asyncio.to_thread(_quick_market_cache_status)
        return {
            "status": "already_running",
            "refresh": get_market_refresh_status(),
            "bootstrap": get_bootstrap_status(),
            "cache_status": cache_status,
        }
    started = start_market_refresh_background()
    cache_status = await asyncio.to_thread(_quick_market_cache_status)
    return {
        "status": "started" if started else "already_running",
        "refresh": get_market_refresh_status(),
        "bootstrap": get_bootstrap_status(),
        "cache_status": cache_status,
    }


def _quick_market_cache_status() -> dict:
    db = SessionLocal()
    try:
        return get_cache_status(db)
    finally:
        db.close()


@app.get("/market_analysis/presets")
async def market_analysis_presets(db: Session = Depends(get_db)):
    from utils.market_data.request_workers import worker_get_presets

    return await asyncio.to_thread(worker_get_presets)


@app.get("/market_analysis/fields")
async def market_analysis_fields(db: Session = Depends(get_db)):
    from utils.market_data.request_workers import worker_get_fields

    return await asyncio.to_thread(worker_get_fields)


@app.post("/market_analysis/parse")
async def market_analysis_parse(body: StockScreenerRequest, db: Session = Depends(get_db)):
    from utils.market_data.request_workers import worker_parse_query

    if not body.query or not body.query.strip():
        raise HTTPException(status_code=400, detail="Query text is required")
    try:
        return await asyncio.to_thread(worker_parse_query, body.query.strip())
    except MarketSqlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/market_analysis/screen")
async def market_analysis_screen(body: StockScreenerRequest, db: Session = Depends(get_db)):
    from utils.market_data.nonblocking_cache import kickoff_cache_bootstrap_if_empty
    from utils.market_data.request_workers import worker_parse_query, worker_run_market_screen

    cache_meta = await kickoff_cache_bootstrap_if_empty()
    symbols = await _resolve_screener_symbols_for_request(body, db)

    filters = [item.model_dump() for item in body.filters]
    rank_by = body.rank_by
    rank_direction = body.rank_direction
    limit = body.limit
    sql = None
    parsed_query = None

    if body.query and body.query.strip():
        sql = body.query.strip()
        try:
            parsed_query = await asyncio.to_thread(worker_parse_query, sql)
        except MarketSqlError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        payload = await asyncio.to_thread(
            worker_run_market_screen,
            symbols=symbols,
            sql=sql,
            filters=filters,
            rank_by=rank_by,
            rank_direction=rank_direction,
            limit=limit,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if parsed_query:
        payload["parsed_query"] = parsed_query
    payload["cache_meta"] = cache_meta
    payload["universe"] = body.universe
    payload["universe_label"] = screener_universe_label(
        body.universe,
        client_id=body.client_id,
        symbol_count=len(symbols),
    )
    return payload


@app.get("/market_analysis/ai_quick_screens")
async def market_analysis_ai_quick_screens():
    return {"quick_screens": list_quick_ai_screens()}


@app.get("/market_analysis/llm_health")
async def market_analysis_llm_health(probe: bool = True):
    return await asyncio.to_thread(test_all_llm_connections, probe=probe)


async def _execute_market_analysis_ai_screen(body: StockScreenerAiRequest, db: Session, *, owner_id: Optional[str] = None) -> Dict:
    from utils.market_data.nonblocking_cache import kickoff_cache_bootstrap_if_empty
    from utils.market_data.request_workers import worker_run_market_screen

    message = (body.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required")

    cache_meta = await kickoff_cache_bootstrap_if_empty()
    symbols = await _resolve_screener_symbols_for_request(body, db)

    recommendation_terms = ("recommendation", "backtest", "win rate", "robust score", "buy signal", "best strategy")
    if owner_id and any(term in message.lower() for term in recommendation_terms):
        from utils.backtesting.recommendations import query_recommendations
        min_trades_match = re.search(r"(?:at least|minimum|min)\s+(\d+)\s+(?:oos\s+)?trades?", message, re.IGNORECASE)
        min_win_match = re.search(r"(?:win rate|winning rate)\s+(?:at least|above|over)?\s*(\d+(?:\.\d+)?)", message, re.IGNORECASE)
        min_score_match = re.search(r"(?:robust|combined|recommendation)\s+score\s+(?:at least|above|over)?\s*(\d+(?:\.\d+)?)", message, re.IGNORECASE)
        recommendation_payload = query_recommendations(db, {
            "signal": "all", "minimum_trades": int(min_trades_match.group(1)) if min_trades_match else 5,
            "minimum_win_rate": float(min_win_match.group(1)) if min_win_match else 0,
            "minimum_score": float(min_score_match.group(1)) if min_score_match else 0,
            "search": "", "sort_by": "recommendation_score", "sort_direction": "desc",
            "page": 1, "page_size": 25,
        }, owner_id=owner_id)
        recommendation_payload.update({
            "results": recommendation_payload.pop("items"),
            "result_columns": ["rank", "symbol", "company_name", "sector", "current_signal_status", "signal_date", "preset_name", "recommendation_score", "win_rate_pct", "total_trades", "net_return_pct", "average_holding_days", "buy_zone_low", "buy_zone_high", "protective_stop", "sell_zone_low", "sell_zone_high", "latest_volume"],
            "column_labels": {},
            "generated_query": "Fresh recommendation table · latest completed trading session · ordinary shares · validated numeric thresholds",
            "explanation": "Used the persisted recommendation projection and rejected older trading-session rows before ranking by recommendation score.",
            "cache_meta": cache_meta, "universe": body.universe,
            "universe_label": "Fresh backtest recommendations",
        })
        return recommendation_payload

    quick_screen = match_quick_ai_screen(message)
    if quick_screen is not None:
        try:
            screener_payload = await asyncio.to_thread(
                worker_run_market_screen,
                symbols=symbols,
                sql=quick_screen["query_sql"].strip(),
                filters=None,
                rank_by=None,
                rank_direction="desc",
                limit=25,
            )
        except HTTPException:
            raise
        except Exception as exc:
            logging.exception("Quick AI screen failed for id=%s", quick_screen["id"])
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        payload = build_quick_ai_screen_payload(quick_screen, screener_payload)
        payload["cache_meta"] = cache_meta
        payload["universe"] = body.universe
        payload["universe_label"] = screener_universe_label(
            body.universe,
            client_id=body.client_id,
            symbol_count=len(symbols),
        )
        return payload

    async def _run(ai_payload: dict) -> dict:
        sql = ai_payload.get("generated_query") or (ai_payload.get("parsed_query") or {}).get("sql")
        return await asyncio.to_thread(
            worker_run_market_screen,
            symbols=symbols,
            sql=sql,
            filters=None,
            rank_by=None,
            rank_direction="desc",
            limit=25,
            allow_select_star=False,
        )

    try:
        payload = await execute_combined_ai_screener(message, _run, db=db)
    except ScreenerAiError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "message": str(exc),
                "ai_status": exc.status,
                "generated_query": exc.generated_query,
            },
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("AI market analysis failed for message=%r", message[:120])
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    payload["cache_meta"] = cache_meta
    payload["universe"] = body.universe
    payload["universe_label"] = screener_universe_label(
        body.universe,
        client_id=body.client_id,
        symbol_count=len(symbols),
    )
    return payload


async def _run_ai_screen_job(job_id: str, body_data: Dict, owner_id: str) -> None:
    db = SessionLocal()
    try:
        body = StockScreenerAiRequest(**body_data)
        body.background = False
        ai_screen_jobs[job_id] = {"status": "running", "owner_id": owner_id}
        result = await _execute_market_analysis_ai_screen(body, db, owner_id=owner_id)
        ai_screen_jobs[job_id] = {
            "status": "complete",
            "owner_id": owner_id,
            "result": result,
            "finished_at": monotonic_time.monotonic(),
        }
    except HTTPException as exc:
        ai_screen_jobs[job_id] = {
            "status": "failed",
            "owner_id": owner_id,
            "http_status": exc.status_code,
            "detail": exc.detail,
            "finished_at": monotonic_time.monotonic(),
        }
    except Exception as exc:
        logging.exception("Background AI screen failed for job_id=%s", job_id)
        ai_screen_jobs[job_id] = {
            "status": "failed",
            "owner_id": owner_id,
            "http_status": 500,
            "detail": str(exc),
            "finished_at": monotonic_time.monotonic(),
        }
    finally:
        db.close()


def _prune_ai_screen_jobs() -> None:
    cutoff = monotonic_time.monotonic() - AI_SCREEN_JOB_TTL_SECONDS
    expired = [
        job_id
        for job_id, job in ai_screen_jobs.items()
        if float(job.get("finished_at", cutoff + 1)) < cutoff
    ]
    for job_id in expired:
        ai_screen_jobs.pop(job_id, None)


@app.get("/market_analysis/ai_screen/jobs/{job_id}")
async def market_analysis_ai_screen_job(job_id: str, current_user: FrontendUser = Depends(require_permission("market_analysis"))):
    _prune_ai_screen_jobs()
    job = ai_screen_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="AI screen job was not found or the server restarted.")
    if str(job.get("owner_id") or "") != str(current_user.id):
        raise HTTPException(status_code=404, detail="AI screen job was not found.")
    if job["status"] in {"pending", "running"}:
        return JSONResponse(status_code=202, content={"job_id": job_id, "status": job["status"]})
    if job["status"] == "failed":
        return JSONResponse(
            status_code=int(job.get("http_status", 500)),
            content={"detail": job.get("detail", "AI screener request failed")},
        )
    return job["result"]


@app.post("/market_analysis/ai_screen")
async def market_analysis_ai_screen(body: StockScreenerAiRequest, db: Session = Depends(get_db), current_user: FrontendUser = Depends(require_permission("market_analysis"))):
    message = (body.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required")

    # Pre-built screens are already fast and do not need job orchestration.
    if body.background and match_quick_ai_screen(message) is None:
        _prune_ai_screen_jobs()
        job_id = uuid.uuid4().hex
        ai_screen_jobs[job_id] = {"status": "pending", "owner_id": str(current_user.id)}
        task = asyncio.create_task(_run_ai_screen_job(job_id, body.model_dump(), str(current_user.id)))
        ai_screen_tasks[job_id] = task
        task.add_done_callback(lambda _task, key=job_id: ai_screen_tasks.pop(key, None))
        return JSONResponse(status_code=202, content={"job_id": job_id, "status": "pending"})

    return await _execute_market_analysis_ai_screen(body, db, owner_id=str(current_user.id))


@app.post("/stock_screener/parse")
async def stock_screener_parse(body: StockScreenerRequest):
    return await market_analysis_parse(body)


@app.post("/stock_screener/screen")
async def stock_screener_screen(body: StockScreenerRequest, db: Session = Depends(get_db)):
    return await market_analysis_screen(body, db)


@app.post("/stock_screener/ai_screen")
async def stock_screener_ai_screen(body: StockScreenerAiRequest, db: Session = Depends(get_db), current_user: FrontendUser = Depends(require_permission("market_analysis"))):
    return await market_analysis_ai_screen(body, db, current_user)


@app.get("/check_orders/")
async def check_orders_endpoint(db: Session = Depends(get_db)):
    if tms_config.is_running:
        return JSONResponse(status_code=400, content={"message": "Check orders loop is already running."})

    started = await start_scheduled_order_monitor(reset_logs=True)
    if not started:
        return JSONResponse(status_code=400, content={"message": "Check orders loop is already running."})
    return {"message": "Check orders loop started."}


@app.get("/stop_check_orders/")
async def stop_check_orders_endpoint():
    stopped = await stop_scheduled_order_monitor()
    if not stopped:
        return {"message": "Check orders loop is not running."}
    return {"message": "Check orders loop stopped."}


@app.get("/monitoring-status/")
async def monitoring_status(current_user: FrontendUser = Depends(require_permission("schedule_orders"))):
    hours = get_market_hours_status(get_nepal_now())
    scheduler = get_scheduler_display_status()
    grabbers = []
    scanning_count = 0
    for session_id, tms_user in running_grabbers.items():
        if stock_grabber_owners.get(session_id) != current_user.id:
            continue
        phase = tms_config.grabber_phase.get(session_id, "armed")
        if phase == "active":
            scanning_count += 1
        started_at = tms_config.grabber_started_at.get(session_id)
        grabbers.append({
            "session_id": session_id,
            "client_id": tms_user.client_id,
            "stock_symbol": tms_user.stock_symbol,
            "scan_count": getattr(tms_user, "scan_count", 0),
            "stop_buy_after_percent": getattr(tms_user, "stop_buy_after_percent", 15.0),
            "stop_buy_after_volume": getattr(tms_user, "stop_buy_after_volume", 5000.0),
            "phase": phase,
            "status_message": tms_config.grabber_status_message.get(session_id, ""),
            "started_at": started_at.isoformat() if started_at else None,
        })

    return {
        **scheduler,
        "scheduled_started_at": (
            tms_config.scheduled_started_at.isoformat()
            if tms_config.scheduled_started_at
            else None
        ),
        "market_open": hours["market_hours_open"],
        "monitor_interval": tms_config.monitor_interval,
        "active_grabber_count": len(running_grabbers),
        "grabber_scanning_count": scanning_count,
        "grabbers": grabbers,
    }


@app.post("/stop_all_stock_grabbers/")
async def stop_all_stock_grabbers(current_user: FrontendUser = Depends(require_permission("stock_grabber"))):
    stopped = []
    for session_id in list(running_tasks.keys()):
        if stock_grabber_owners.get(session_id) != current_user.id:
            continue
        task = running_tasks.get(session_id)
        if task:
            task.cancel()
            stopped.append(session_id)
            del running_tasks[session_id]
            running_grabbers.pop(session_id, None)
            stock_grabber_owners.pop(session_id, None)
            tms_config.grabber_started_at.pop(session_id, None)
            tms_config.grabber_phase.pop(session_id, None)
            tms_config.grabber_status_message.pop(session_id, None)
            if session_id in stock_grabber_updates:
                stock_grabber_updates[session_id].append(
                    {"status": "stopped", "message": "Stock grabber stopped"}
                )
    return {"message": f"Stopped {len(stopped)} stock grabber(s)", "stopped": stopped}


@app.delete("/logs/")
async def clear_logs(client_ids:str = Query(...), db: Session = Depends(get_db), current_user: FrontendUser = Depends(require_permission("order_logs"))):
    if not client_ids:
        raise HTTPException(status_code=400, detail="Client IDs cannot be empty.")
    client_ids=client_ids.split(',')
    owned = set(owned_client_ids(db, current_user))
    if any(client_id.strip() not in owned for client_id in client_ids):
        raise HTTPException(status_code=404, detail="One or more TMS accounts were not found.")
    try:
        # Check if logs exist before deleting
        existing_logs = db.query(OrderLog).filter(OrderLog.client_id.in_(client_ids)).count()
        if existing_logs == 0:
            raise HTTPException(status_code=404, detail="No logs found for the specified client IDs.")

        # Proceed with deletion
        deleted_count = delete_order_log_scan_counts_for_client_ids(db, client_ids)
        db.commit()

        return {"message": f"Logs cleared successfully for {deleted_count} log(s)."}
    
    except Exception as e:
        db.rollback()  # Rollback in case of error
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=f"Failed to clear logs: {str(e)}")
    
    finally:
        db.close()

@app.get("/logs/")
async def get_order_logs(client_ids: List[str] = Query(...), db: Session = Depends(get_db), current_user: FrontendUser = Depends(require_permission("order_logs"))):
    try:
        # Querying the OrderLog table for the list of client_ids
        client_ids = list(map(str.strip, client_ids))
        owned = set(owned_client_ids(db, current_user))
        if any(client_id not in owned for client_id in client_ids):
            raise HTTPException(status_code=404, detail="One or more TMS accounts were not found.")
        order_logs = db.query(OrderLog).filter(
            OrderLog.client_id.in_(client_ids)).all()

        if not order_logs:
            raise HTTPException(
                status_code=404, detail="No order logs found for the given client IDs.")

        # Transforming the logs into a serializable format
        logs_list = [{
            "id": log.id,
            "client_id": log.client_id,
            "script_name": log.script_name,
            "scanning_count": log.scanning_count,
            "current_price": log.current_price,
            "order_placed": log.order_placed,
            # Convert datetime to ISO format for JSON
            "timestamp": log.timestamp.isoformat(),
            "logs": log.logs
        } for log in order_logs]

        return {"order_logs": logs_list}

    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/frontend-login")
async def frontend_login(user_login: UserLogin, db: Session = Depends(get_db)):
    username = user_login.username.strip()
    password = user_login.password.strip()
    user = FrontendUser.authenticate(
        username, password, db)
    if not user:
        raise HTTPException(
            status_code=401, detail="Invalid username or password")

    user.last_login_at = datetime.utcnow()
    db.commit()
    return {"message": "Login successful", "user_id": user.id, "access_token": create_access_token(user)}

# @app.post("/start_order_loop/")
# async def start_order_loop(background_tasks: BackgroundTasks):
#     background_tasks.add_task(check_orders)
#     return {"message": "Order loop started"}

# @app.post("/stop_order_loop/")
# async def stop_order_loop():
#     # Add logic to stop the order loop
#     return {"message": "Order loop stopped"}


@app.get("/{path:path}")
async def catch_all(path: str):
    requested_path = (FRONTEND_BUILD_DIR / path).resolve()
    build_root = FRONTEND_BUILD_DIR.resolve()
    if (
        FRONTEND_BUILD_DIR.exists()
        and requested_path.is_file()
        and (requested_path == build_root or build_root in requested_path.parents)
    ):
        return FileResponse(requested_path)

    index_path = FRONTEND_BUILD_DIR / "index.html"
    if index_path.exists() and "." not in Path(path).name:
        return FileResponse(index_path)

    raise HTTPException(status_code=404, detail="Route not found")

# Run the FastAPI application
if __name__ == "__main__":
    host = "0.0.0.0"
    port = 8000
    uvicorn.run(app, host=host, port=port, reload=True)
    print(f"Server is running at {host}:{port} ")
