import logging
import json
import uuid
import aiohttp
import time as monotonic_time
from pathlib import Path
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import asyncio
import sys
from typing import Dict, List, Optional, Type
from fastapi import FastAPI, HTTPException, Depends, Query, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
import websockets
from database import ensure_performance_indexes, get_db
from sqlalchemy import cast, DateTime, or_, and_
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
from utils.log_sender import is_transient_monitor_log_line
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
from datetime import datetime

from utils.tms_user_loader import load_tms_users_instances
from utils.api_time import format_api_timestamp, get_server_time_payload
from utils.market_status import (
    format_nepal_datetime,
    get_market_hours_status,
    get_nepal_now,
    is_market_live,
    nepal_date_utc_bounds,
    outside_market_hours_message,
    parse_session_check_response,
)
import config.tms_config as tms_config
from config.app_build_info import get_app_build_info
from utils.external_data_sources.nepse_alpha.ai_query import ScreenerAiError, execute_ai_screener_with_retries
from utils.external_data_sources.nepse_alpha.query_parser import ScreenerQueryError, parse_screener_query
from utils.external_data_sources.nepse_alpha.screener import get_field_catalog, get_screener_query_spec, run_stock_screener
from utils.stock_screener_symbols import resolve_screener_symbols, screener_universe_label
from utils.strategy_builder.api import router as strategy_builder_router
from utils.strategy_builder.reference_display import (
    display_values_for_scheduled_order,
    display_values_from_strategy_config,
)

app = FastAPI(debug=True)
app.include_router(strategy_builder_router)
SECRET_KEY = "your_secret_key_here"
FRONTEND_BUILD_DIR = Path(__file__).resolve().parent / "frontend" / "build"

# Store running tasks and updates
running_tasks: Dict[str, asyncio.Task] = {}
scheduled_supervisor_task: Optional[asyncio.Task] = None
running_grabbers: Dict[str, TmsUser] = {}
stock_grabber_updates: Dict[str, List[Dict]] = {}
tms_user_cache: Dict[str, TmsUser] = {}
tms_user_cache_touched: Dict[str, float] = {}
tms_user_cache_ttl = 300.0
market_status_cache: Optional[tuple[float, dict]] = None

async def invalidate_cached_tms_user(client_id: str) -> None:
    cached = tms_user_cache.pop(client_id, None)
    tms_user_cache_touched.pop(client_id, None)
    if cached:
        await cached.close()

async def get_cached_tms_user(user: User, *, request_per_sec: float = 5) -> TmsUser:
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
        await tms_user.try_cached_login()
    except Exception:
        await tms_user.close()
        raise

    tms_user_cache[user.client_id] = tms_user
    tms_user_cache_touched[user.client_id] = now
    return tms_user

@app.on_event("shutdown")
async def close_cached_tms_users() -> None:
    global scheduled_supervisor_task
    if scheduled_supervisor_task is not None and not scheduled_supervisor_task.done():
        scheduled_supervisor_task.cancel()
        try:
            await scheduled_supervisor_task
        except asyncio.CancelledError:
            pass
    scheduled_supervisor_task = None
    await stop_scheduled_order_monitor()
    for client_id in list(tms_user_cache.keys()):
        await invalidate_cached_tms_user(client_id)

@app.on_event("startup")
async def ensure_database_indexes() -> None:
    global scheduled_supervisor_task
    from config.portal_settings import load_portal_settings

    await asyncio.to_thread(ensure_performance_indexes)
    await asyncio.to_thread(load_portal_settings)
    scheduled_supervisor_task = asyncio.create_task(scheduled_monitor_supervisor_loop())

async def _run_stock_grabber_task(
    tms_user: TmsUser,
    session_id: str,
    order_quantity: int,
    max_order_limit: int,
    stop_buy_after_percent: float,
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
                await asyncio.sleep(tms_config.monitor_interval)
                continue

            try:
                result = await tms_user.stock_grabber(
                    order_quantity=order_quantity,
                    session_id=session_id,
                    max_order_limit=max_order_limit,
                    stop_buy_after_percent=stop_buy_after_percent,
                )
                placed = len(result.get("totalOrders") or [])
                if placed > 0 or result.get("message") == "ACCESS_TOKEN_EXPIRED" or result.get("stop_reason"):
                    break
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
async def stock_grabber(request: StockGrabberRequest, db: Session = Depends(get_db)):
    session_id = str(uuid.uuid4())
    stock_grabber_updates[session_id] = []
    user = db.query(User).filter(User.client_id == request.client_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

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

    tms_user = TmsUser(
        broker_no=user.broker_no,
        username=user.client_id,
        password=user.password,
        stock_symbol=request.stock_symbol,
        request_per_sec=request.request_per_sec,
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
        )
    )
    running_tasks[session_id] = task
    running_grabbers[session_id] = tms_user

    def _on_grabber_done(done_task: asyncio.Task) -> None:
        running_tasks.pop(session_id, None)
        running_grabbers.pop(session_id, None)
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

@app.post("/stop_stock_grabber/{session_id}")
async def stop_stock_grabber(session_id: str):
    task = running_tasks.get(session_id)
    if task:
        task.cancel()
        del running_tasks[session_id]
        running_grabbers.pop(session_id, None)
        tms_config.grabber_started_at.pop(session_id, None)
        tms_config.grabber_phase.pop(session_id, None)
        tms_config.grabber_status_message.pop(session_id, None)
        stock_grabber_updates[session_id].append({"status": "stopped", "message": "Stock grabber stopped"})
        return {"message": f"Stock grabber {session_id} stopped"}
    raise HTTPException(status_code=404, detail="Stock grabber not found")


@app.get("/get_stock_grabber_updates/{session_id}")
async def get_stock_grabber_updates(session_id: str):
    updates = list(stock_grabber_updates.get(session_id, []))
    stock_grabber_updates[session_id] = []

    tms_user = running_grabbers.get(session_id)
    if tms_user and tms_user.updates:
        updates.extend(tms_user.updates)
        tms_user.updates = []

    task = running_tasks.get(session_id)
    scanner_active = task is not None and not task.done()

    return {"updates": updates, "scanner_active": scanner_active}


@app.get("/active_stock_grabbers/")
@app.get("/active_stock_grabbers")
async def active_stock_grabbers():
    grabbers = []
    for session_id, tms_user in running_grabbers.items():
        task = running_tasks.get(session_id)
        started_at = tms_config.grabber_started_at.get(session_id)
        grabbers.append({
            "session_id": session_id,
            "client_id": tms_user.client_id,
            "stock_symbol": tms_user.stock_symbol,
            "scan_count": getattr(tms_user, "scan_count", 0),
            "scanner_active": task is not None and not task.done(),
            "request_per_sec": tms_user.request_per_sec,
            "stop_buy_after_percent": getattr(tms_user, "stop_buy_after_percent", 15.0),
            "stable_rate": tms_user.stable_rate,
            "phase": tms_config.grabber_phase.get(session_id, "armed"),
            "status_message": tms_config.grabber_status_message.get(session_id, ""),
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


@app.get("/market-status/")
async def get_market_status(db: Session = Depends(get_db)):
    global market_status_cache
    cache_now = monotonic_time.monotonic()
    if market_status_cache and cache_now - market_status_cache[0] < 4.0:
        return market_status_cache[1]

    now = get_nepal_now()
    hours = get_market_hours_status(now)
    nepal = format_nepal_datetime(now)

    tms_session_active = False
    tms_session_message = "DNA logged off"
    market_live_from_api = None
    client_id = None
    broker_no = None
    session_data = None

    logged_in = (
        db.query(LoggedInUsers)
        .filter(LoggedInUsers.status == "logged_in")
        .order_by(LoggedInUsers.last_updated.desc())
        .first()
    )

    if not hours["market_hours_open"]:
        tms_session_message = outside_market_hours_message()
    elif logged_in and logged_in.tokens:
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
                session_payload = await tms_user.check_exchange_session()
                parsed = parse_session_check_response(session_payload)
                tms_session_active = parsed["session_active"]
                tms_session_message = parsed["session_message"]
                market_live_from_api = parsed["market_live_from_api"]
                session_data = parsed["session_data"]
        except TimeoutError:
            tms_session_message = "Session check timed out"
        except LoginFailedException as exc:
            tms_session_message = exc.message
        except Exception as exc:
            tms_session_message = f"Unable to check TMS session: {exc}"
        finally:
            if temp_tms_user:
                await temp_tms_user.close()
    elif hours["market_hours_open"]:
        tms_session_message = "No TMS client logged in"

    market_live = is_market_live(hours, tms_session_active)

    if not hours["is_trading_day"]:
        market_phase = "closed_weekend"
    elif hours["is_pre_open"]:
        market_phase = "pre_open"
    elif hours["is_continuous"]:
        market_phase = "open"
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
        "is_trading_day": hours["is_trading_day"],
        "is_pre_open": hours["is_pre_open"],
        "is_continuous_session": hours["is_continuous"],
        "market_hours_open": hours["market_hours_open"],
        "market_phase": market_phase,
        "tms_session_active": tms_session_active,
        "tms_session_message": tms_session_message,
        "market_live": market_live,
        "market_live_from_api": market_live_from_api,
        "client_id": client_id,
        "broker_no": broker_no,
        "session_data": session_data,
    }
    market_status_cache = (cache_now, payload)
    return payload


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

    if not monitoring_active or monitor_phase == "stopped":
        return {
            "live_status": "monitor stopped",
            "is_scanning": False,
            "display_error": "Monitor stopped",
        }

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
async def list_tms_accounts(db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.client_id).all()
    sessions = {
        session.client_id: session
        for session in db.query(LoggedInUsers).all()
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
async def refresh_tms_account_collateral(db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.client_id).all()
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
async def create_tms_account(payload: TmsAccountCreate, db: Session = Depends(get_db)):
    client_id = payload.client_id.strip()
    if not client_id:
        raise HTTPException(status_code=400, detail="client_id is required")
    if db.query(User).filter(User.client_id == client_id).first():
        raise HTTPException(status_code=409, detail=f"TMS account {client_id} already exists")

    encoded_password = TmsUser.to_tms_password_payload(payload.password)
    user = User(
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
):
    user = db.query(User).filter(User.client_id == client_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="TMS account not found")

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
async def delete_tms_account(client_id: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.client_id == client_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="TMS account not found")

    db.query(LoggedInUsers).filter(LoggedInUsers.client_id == client_id).delete()
    db.delete(user)
    db.commit()
    await invalidate_cached_tms_user(client_id)
    return {"message": f"TMS account {client_id} deleted"}


@app.post("/tms-accounts/{client_id}/login")
async def login_tms_account(client_id: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.client_id == client_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="TMS account not found")

    try:
        await invalidate_cached_tms_user(client_id)
        tms_instance = await get_cached_tms_user(user, request_per_sec=5)
        try:
            await tms_instance.get_client_collateral(force_refresh=True)
        except Exception:
            pass
        login_status = {
            "status": "success",
            "message": "token loaded and session cached",
            "password_expiry": getattr(tms_instance, "login_response", {}).get("password_expiry"),
            "password_rotated": False,
        }
    except LoginFailedException as e:
        _record_tms_login_failure(db, client_id=client_id, broker_no=user.broker_no, message=e.message)
        raise HTTPException(status_code=401, detail=e.message)

    if login_status.get("status") != "success":
        raise HTTPException(status_code=401, detail="Login failed")

    session = db.query(LoggedInUsers).filter(LoggedInUsers.client_id == client_id).first()
    if session:
        session.status = "logged_in"
        session.message = summarize_login_message(login_status.get("message") or "Logged in")
        session.last_login_at = datetime.utcnow()
        db.commit()
        db.refresh(session)
    return {
        "message": login_status,
        "account": _serialize_tms_account(user, session),
    }


@app.post("/login/")
async def login(login_request: LoginRequest, db: Session = Depends(get_db)):
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
async def cancel_order(client_id: str, exchange_order_id: str, db: Session = Depends(get_db)):
    try:
        # Retrieve user from the database based on client_id
        user = db.query(User).filter(User.client_id == client_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

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


@app.post("/add_order/")
async def add_order(order_data: OrderCreateRequest, db: Session = Depends(get_db)):
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
    db.add(order)
    db.flush()
    await _persist_order_field_references(db, order, order_data)
    order.strategy_config = dict(order.strategy_config or {})
    order.strategy_config["schedule_dedup_key"] = _scheduled_order_dedup_key(order_data)
    from utils.strategy_builder.schedule_preview_capture import apply_schedule_preview_snapshot

    await apply_schedule_preview_snapshot(order, order_data, db)
    db.commit()
    return {"message": "Order added successfully"}


@app.get("/logged_in_clients/")
async def get_logged_in_clients(db: Session = Depends(get_db)):
    try:
        stale_sessions = (
            db.query(LoggedInUsers)
            .filter(LoggedInUsers.status != "logged_in", LoggedInUsers.tokens.isnot(None))
            .all()
        )
        for session in stale_sessions:
            if not session.tokens:
                continue
            user = db.query(User).filter(User.client_id == session.client_id).first()
            if not user or not user.auto_login:
                continue
            try:
                await get_cached_tms_user(user)
            except LoginFailedException:
                continue
            except Exception:
                continue

        logged_in_users = db.query(LoggedInUsers).filter(
            LoggedInUsers.status == "logged_in").all()
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
    db: Session = Depends(get_db)
):
    if order_id:
        orders_to_delete = db.query(ScheduledOrder).filter(
            ScheduledOrder.order_id == order_id).all()
    elif client_id and script_name:
        orders_to_delete = db.query(ScheduledOrder).filter(
            ScheduledOrder.client_id == client_id,
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
    db.commit()

    return {"message": "Order deleted successfully"}


@app.delete("/scheduled_orders/batch/{batch_id}")
async def delete_scheduled_order_batch(batch_id: str, db: Session = Depends(get_db)):
    normalized_batch_id = str(batch_id or "").strip()
    if not normalized_batch_id:
        raise HTTPException(status_code=400, detail="batch_id is required.")

    orders_to_delete = [
        order
        for order in db.query(ScheduledOrder).all()
        if str((order.strategy_config or {}).get("schedule_batch_id") or "").strip() == normalized_batch_id
    ]
    if not orders_to_delete:
        raise HTTPException(status_code=404, detail="Batch not found.")

    deleted_ids: list[int] = []
    for order in orders_to_delete:
        db.add(_order_status_log_from_order(order, status="cancelled"))
        deleted_ids.append(order.order_id)
        db.delete(order)
    db.commit()

    return {
        "message": f"Deleted {len(deleted_ids)} scheduled order(s) from batch.",
        "batch_id": normalized_batch_id,
        "deleted_order_ids": deleted_ids,
        "deleted_count": len(deleted_ids),
    }


@app.get("/scheduled_orders/")
async def list_scheduled_orders(db: Session = Depends(get_db)):
    orders = db.query(ScheduledOrder).order_by(ScheduledOrder.order_id).all()
    return {"scheduled_orders": [_serialize_scheduled_order(order) for order in orders]}


@app.get("/scheduled_orders/{order_id}")
async def get_scheduled_order(order_id: int, db: Session = Depends(get_db)):
    order = db.query(ScheduledOrder).filter(ScheduledOrder.order_id == order_id).first()
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
        await _validate_sell_lot_against_holdings(order_data, tms_user_instance)


@app.post("/scheduled_orders/")
async def create_scheduled_order(order_data: OrderCreateRequest, db: Session = Depends(get_db)):
    await _validate_scheduled_order_payload(order_data, db)
    duplicate_result = await _reject_duplicate_scheduled_order(db, order_data)
    if duplicate_result:
        return duplicate_result
    order = ScheduledOrder(order_data)
    db.add(order)
    db.flush()
    await _persist_order_field_references(db, order, order_data)
    order.strategy_config = dict(order.strategy_config or {})
    order.strategy_config["schedule_dedup_key"] = _scheduled_order_dedup_key(order_data)
    from utils.strategy_builder.schedule_preview_capture import apply_schedule_preview_snapshot

    await apply_schedule_preview_snapshot(order, order_data, db)
    db.commit()
    db.refresh(order)
    return {"message": "Scheduled order created", "order": _serialize_scheduled_order(order)}


@app.post("/scheduled_orders/{order_id}/references/refresh")
async def refresh_scheduled_order_references(
    order_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    order = db.query(ScheduledOrder).filter(ScheduledOrder.order_id == order_id).first()
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
async def update_scheduled_order(order_id: int, order_data: OrderCreateRequest, db: Session = Depends(get_db)):
    order = db.query(ScheduledOrder).filter(ScheduledOrder.order_id == order_id).first()
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
    db.commit()
    db.refresh(order)
    return {"message": "Scheduled order updated", "order": _serialize_scheduled_order(order)}


@app.delete("/scheduled_orders/")
async def clear_scheduled_orders(db: Session = Depends(get_db)):
    deleted_count = db.query(ScheduledOrder).delete(synchronize_session=False)
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
    db: Session = Depends(get_db)
):
    query = db.query(OrderStatusLog)

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

    scheduled_query = db.query(ScheduledOrder)
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
            for scan_log in db.query(OrderLog).filter(or_(*pair_filters)).all():
                scan_logs[(scan_log.client_id, scan_log.script_name)] = scan_log

    scheduled_payload = []
    monitor_phase = tms_config.scheduled_phase if tms_config.is_running else "stopped"
    for order in scheduled_orders:
        scan_log = scan_logs.get((order.client_id, order.script_name))
        scanning_count = int(scan_log.scanning_count or 0) if scan_log else 0
        current_price_val = (
            float(scan_log.current_price)
            if scan_log and scan_log.current_price is not None
            else None
        )
        last_monitor_message = _last_monitor_log_line(scan_log, current_price=current_price_val)
        live_status_fields = _compute_scheduled_live_status(
            monitoring_active=tms_config.is_running,
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
            "strategy_config": order.strategy_config,
            "nepse_alpha_scan_count": int((order.strategy_config or {}).get("nepse_alpha_scan_count") or 0),
            "nepse_alpha_last_source": (order.strategy_config or {}).get("nepse_alpha_last_source"),
            "nepse_alpha_last_fetched_at": (order.strategy_config or {}).get("nepse_alpha_last_fetched_at"),
            "tms_scan_count": int((order.strategy_config or {}).get("tms_scan_count") or scanning_count),
            "security_details": order.security_details or {},
            "editable": _is_scheduled_order_editable(order),
            "failed_reason": order.failed_reason,
            "cancelled_reason": order.cancelled_reason,
            "scanning_count": scanning_count,
            "current_price": int(round(current_price_val)) if current_price_val is not None else None,
            "last_scan_at": format_api_timestamp(scan_log.timestamp if scan_log else None),
            **live_status_fields,
            "last_monitor_message": last_monitor_message,
            "monitor_logs": scan_log.logs if scan_log and scan_log.logs else None,
        })

    combined_results = {
        "order_logs": [serialize_order_status_log(log) for log in order_logs],
        "scheduled_orders": scheduled_payload,
        "monitoring_active": tms_config.is_running,
        "monitor_phase": monitor_phase,
        "monitor_status_message": tms_config.scheduled_status_message,
        "scheduled_started_at": format_api_timestamp(tms_config.scheduled_started_at),
        "monitor_interval": tms_config.monitor_interval,
        "server_time": get_server_time_payload()["now"],
    }

    return combined_results


@app.delete("/order_status_logs/clear")
async def clear_order_status_logs(client_ids: str = Query(...), db: Session = Depends(get_db)):
    if not client_ids or not client_ids.strip():
        raise HTTPException(status_code=400, detail="Client IDs cannot be empty.")

    parsed_client_ids = [item.strip() for item in client_ids.split(",") if item.strip()]
    if not parsed_client_ids:
        raise HTTPException(status_code=400, detail="Client IDs cannot be empty.")

    try:
        updated_count = (
            db.query(OrderStatusLog)
            .filter(OrderStatusLog.client_id.in_(parsed_client_ids))
            .filter(OrderStatusLog.deleted_at.is_(None))
            .update({OrderStatusLog.deleted_at: datetime.utcnow()}, synchronize_session=False)
        )
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
async def get_order_history(client_id: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.client_id == client_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

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
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.client_id == client_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        tms_user = await get_cached_tms_user(user)
        history_rows = await tms_user.get_tradebook_history(from_date, to_date)
        return history_rows
    except LoginFailedException as e:
        await invalidate_cached_tms_user(client_id)
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/dp_holdings")
async def get_dp_holdings(client_id: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.client_id == client_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        tms_user = await get_cached_tms_user(user)
        dp_holdings = await tms_user.get_user_stock_details()  # Await the async call
        return dp_holdings
    except LoginFailedException as e:
        await invalidate_cached_tms_user(client_id)
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stock_quote")
async def get_stock_quote(client_id: str, symbol: str, db: Session = Depends(get_db)):
    try:
        user = db.query(User).filter(User.client_id == client_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        tms_user_instance = await get_cached_tms_user(user)

        security = await tms_user_instance.get_security_id(symbol)
        if not security or not security.get("id"):
            raise HTTPException(status_code=404, detail=f"Security not found for {symbol}")

        quote = await tms_user_instance.get_stock_details_async(
            str(security["id"]),
            max_retries=3,
            retry_backoff=True,
        )
        if not quote:
            return {"security": security, "quote": None}

        return {"security": security, "quote": quote}

    except LoginFailedException as e:
        await invalidate_cached_tms_user(client_id)
        raise HTTPException(status_code=401, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/get_order_book")
async def get_order_book(client_id: str, db: Session = Depends(get_db)):
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
async def get_daily_order_book(client_id: str, db: Session = Depends(get_db)):
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
async def get_script_details(client_id: str, db: Session = Depends(get_db)):
    try:
        user = db.query(User).filter(User.client_id == client_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        tms_user_instance = await get_cached_tms_user(user)

        stock_data = await tms_user_instance.fetch_securities_details()  # Await the async call
        return stock_data

    except LoginFailedException as e:
        await invalidate_cached_tms_user(client_id)
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stock_screener/fields")
async def stock_screener_fields():
    return {
        "fields": get_field_catalog(),
        "cache_ttl_seconds": 300,
        "query_spec": get_screener_query_spec(),
    }


async def _resolve_screener_symbols_for_request(body, db: Session) -> List[str]:
    return await resolve_screener_symbols(
        universe=getattr(body, "universe", "nepse") or "nepse",
        client_id=body.client_id,
        client_ids=body.client_ids,
        symbols=body.symbols,
        db=db,
    )


@app.post("/stock_screener/parse")
async def stock_screener_parse(body: StockScreenerRequest):
    if not body.query or not body.query.strip():
        raise HTTPException(status_code=400, detail="Query text is required")
    try:
        parsed = parse_screener_query(body.query)
    except ScreenerQueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return parsed


@app.post("/stock_screener/screen")
async def stock_screener_screen(body: StockScreenerRequest, db: Session = Depends(get_db)):
    symbols = await _resolve_screener_symbols_for_request(body, db)

    filters = [item.model_dump() for item in body.filters]
    rank_by = body.rank_by
    rank_direction = body.rank_direction
    limit = body.limit
    parsed_query = None

    if body.query and body.query.strip():
        try:
            parsed_query = parse_screener_query(body.query)
        except ScreenerQueryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        filters = parsed_query["filters"]
        rank_by = parsed_query["rank_by"]
        rank_direction = parsed_query["rank_direction"]
        limit = parsed_query["limit"]

    try:
        payload = await run_stock_screener(
            symbols,
            filters,
            rank_by=rank_by,
            rank_direction=rank_direction,
            limit=limit,
            force_refresh=body.force_refresh,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if parsed_query:
        payload["parsed_query"] = parsed_query
    payload["universe"] = body.universe
    payload["universe_label"] = screener_universe_label(
        body.universe,
        client_id=body.client_id,
        symbol_count=len(symbols),
    )
    return payload


@app.post("/stock_screener/ai_screen")
async def stock_screener_ai_screen(body: StockScreenerAiRequest, db: Session = Depends(get_db)):
    message = (body.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required")

    symbols = await _resolve_screener_symbols_for_request(body, db)

    async def _run(parsed_query: dict) -> dict:
        return await run_stock_screener(
            symbols,
            parsed_query["filters"],
            rank_by=parsed_query["rank_by"],
            rank_direction=parsed_query["rank_direction"],
            limit=parsed_query["limit"],
            force_refresh=body.force_refresh,
        )

    try:
        payload = await execute_ai_screener_with_retries(message, _run)
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
        logging.exception("AI screener failed for message=%r", message[:120])
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    payload["universe"] = body.universe
    payload["universe_label"] = screener_universe_label(
        body.universe,
        client_id=body.client_id,
        symbol_count=len(symbols),
    )
    return payload


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
async def monitoring_status():
    hours = get_market_hours_status(get_nepal_now())
    scheduler = get_scheduler_display_status()
    grabbers = []
    scanning_count = 0
    for session_id, tms_user in running_grabbers.items():
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
async def stop_all_stock_grabbers():
    stopped = []
    for session_id in list(running_tasks.keys()):
        task = running_tasks.get(session_id)
        if task:
            task.cancel()
            stopped.append(session_id)
            del running_tasks[session_id]
            running_grabbers.pop(session_id, None)
            tms_config.grabber_started_at.pop(session_id, None)
            tms_config.grabber_phase.pop(session_id, None)
            tms_config.grabber_status_message.pop(session_id, None)
            if session_id in stock_grabber_updates:
                stock_grabber_updates[session_id].append(
                    {"status": "stopped", "message": "Stock grabber stopped"}
                )
    return {"message": f"Stopped {len(stopped)} stock grabber(s)", "stopped": stopped}


@app.delete("/logs/")
async def clear_logs(client_ids:str = Query(...), db: Session = Depends(get_db)):
    if not client_ids:
        raise HTTPException(status_code=400, detail="Client IDs cannot be empty.")
    client_ids=client_ids.split(',')
    try:
        # Check if logs exist before deleting
        existing_logs = db.query(OrderLog).filter(OrderLog.client_id.in_(client_ids)).count()
        if existing_logs == 0:
            raise HTTPException(status_code=404, detail="No logs found for the specified client IDs.")

        # Proceed with deletion
        deleted_count = db.query(OrderLog).filter(OrderLog.client_id.in_(client_ids)).delete(synchronize_session=False)
        db.commit()

        return {"message": f"Logs cleared successfully for {deleted_count} client IDs."}
    
    except Exception as e:
        db.rollback()  # Rollback in case of error
        raise HTTPException(status_code=500, detail=f"Failed to clear logs: {str(e)}")
    
    finally:
        db.close()

@app.get("/logs/")
async def get_order_logs(client_ids: List[str] = Query(...), db: Session = Depends(get_db)):
    try:
        # Querying the OrderLog table for the list of client_ids
        client_ids = list(map(str.strip, client_ids))
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

    # Generate JWT token
    timestamp = datetime.utcnow().timestamp()
    payload = {
        "username": username,
        "password": password,
        "timestamp": timestamp
    }
    access_token = jwt.encode(payload, SECRET_KEY, algorithm="HS256")

    return {"message": "Login successful", "user_id": user.id, "access_token": access_token}

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
