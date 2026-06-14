import logging
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
    TmsAccountCreate,
    TmsAccountUpdate,
    UserLogin,
)
from utils.base_functions import is_within_time_range, truncate_to_one_decimal_place
from utils.base_functions import summarize_login_message
from utils.monitor_order import monitor_order_task_func
from utils.market_gate import resolve_market_gate
from utils.tms import TmsUser
import uvicorn
import jwt
from fastapi import FastAPI, Request, HTTPException
from sqlalchemy.orm import Session
from datetime import date, time, timedelta, datetime

from utils.tms_user_loader import load_tms_users_instances
from utils.market_status import (
    format_nepal_datetime,
    get_market_hours_status,
    get_nepal_now,
    is_market_live,
    outside_market_hours_message,
    parse_session_check_response,
)
import config.tms_config as tms_config

app = FastAPI(debug=True)
SECRET_KEY = "your_secret_key_here"
FRONTEND_BUILD_DIR = Path(__file__).resolve().parent / "frontend" / "build"

# Store running tasks and updates
running_tasks: Dict[str, asyncio.Task] = {}
check_orders_task: Optional[asyncio.Task] = None
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
    now = monotonic_time.monotonic()
    cached = tms_user_cache.get(user.client_id)
    touched = tms_user_cache_touched.get(user.client_id, 0)
    if (
        cached
        and now - touched < tms_user_cache_ttl
        and str(cached.broker_no) == str(user.broker_no)
        and cached.password == user.password
        and cached.session is not None
        and not cached.session.closed
    ):
        tms_user_cache_touched[user.client_id] = now
        return cached

    if cached:
        await invalidate_cached_tms_user(user.client_id)

    tms_user = TmsUser(
        broker_no=user.broker_no,
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
    for client_id in list(tms_user_cache.keys()):
        await invalidate_cached_tms_user(client_id)

@app.on_event("startup")
async def ensure_database_indexes() -> None:
    await asyncio.to_thread(ensure_performance_indexes)

async def _run_stock_grabber_task(
    tms_user: TmsUser,
    session_id: str,
    order_quantity: int,
    max_order_limit: int,
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
                )
                placed = len(result.get("totalOrders") or [])
                if placed > 0 or result.get("message") == "ACCESS_TOKEN_EXPIRED":
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
        "nepal_time": nepal["iso"],
        "nepal_time_formatted": nepal["time"],
        "nepal_date_formatted": nepal["date"],
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
    return {
        "client_id": user.client_id,
        "display_name": display_name,
        "broker_no": user.broker_no,
        "password": _decode_tms_account_password(user.password),
        "auto_login": bool(user.auto_login),
        "session_status": session.status if session else "logged_out",
        "session_message": session.message if session else None,
        "last_updated": session.last_login_at.isoformat() if session and session.last_login_at else None,
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
) -> str:
    if not monitoring_active:
        return "monitor stopped"
    if monitor_phase == "waiting_hours":
        return "waiting for market"
    if monitor_phase == "waiting_session":
        return "waiting for TMS session"
    if scanning_count > 0:
        return f"scanning ({scanning_count})"
    return "scanning"


def _order_status_log_from_order(order: ScheduledOrder) -> OrderStatusLog:
    return OrderStatusLog(
        order_id=order.order_id,
        client_id=order.client_id,
        security_details=order.security_details,
        script_name=order.script_name,
        qty=order.qty,
        status=order.status,
        price=order.price,
        order_type=order.order_type,
    )


def _serialize_scheduled_order(order: ScheduledOrder) -> dict:
    return {
        "order_id": order.order_id,
        "client_id": order.client_id,
        "security_details": order.security_details or {},
        "script_name": order.script_name,
        "price": order.price,
        "qty": order.qty,
        "status": order.status,
        "order_type": order.order_type,
        "last_updated": order.last_updated.isoformat() if order.last_updated else None,
    }


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
                "last_updated": session.last_login_at.isoformat() if session.last_login_at else None,
            })

    accounts.sort(key=lambda account: account["client_id"])
    logged_in = [a for a in accounts if a["session_status"] == "logged_in"]
    return {"accounts": accounts, "logged_in_count": len(logged_in)}


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


@app.post("/add_order/")
async def add_order(order_data: OrderCreateRequest, db: Session = Depends(get_db)):
    if order_data.order_type.lower() == "buy":
        user = db.query(User).filter(User.client_id == order_data.client_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

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

    order = ScheduledOrder(order_data)
    db.add(order)
    db.commit()
    return {"message": "Order added successfully"}


@app.get("/logged_in_clients/")
async def get_logged_in_clients(db: Session = Depends(get_db)):
    try:
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
        db.add(_order_status_log_from_order(order))
        db.delete(order)
    db.commit()

    return {"message": "Order deleted successfully"}


@app.get("/scheduled_orders/")
async def list_scheduled_orders(db: Session = Depends(get_db)):
    orders = db.query(ScheduledOrder).order_by(ScheduledOrder.order_id).all()
    return {"scheduled_orders": [_serialize_scheduled_order(order) for order in orders]}


@app.post("/scheduled_orders/")
async def create_scheduled_order(order_data: OrderCreateRequest, db: Session = Depends(get_db)):
    if not db.query(User).filter(User.client_id == order_data.client_id).first():
        raise HTTPException(status_code=404, detail="User not found")
    order = ScheduledOrder(order_data)
    db.add(order)
    db.commit()
    db.refresh(order)
    return {"message": "Scheduled order created", "order": _serialize_scheduled_order(order)}


@app.delete("/scheduled_orders/")
async def clear_scheduled_orders(db: Session = Depends(get_db)):
    deleted_count = db.query(ScheduledOrder).delete(synchronize_session=False)
    db.commit()
    return {"message": f"Deleted {deleted_count} scheduled order(s)"}


@app.post("/update_monitor_interval")
async def update_monitor_interval(request: Request):
    data = await request.json()
    monitor_interval = data.get("monitor_interval")
    if monitor_interval is not None:
        tms_config.monitor_interval = monitor_interval
        return {"message": "Monitor interval updated successfully", "new_interval": tms_config.monitor_interval}
    else:
        return {"error": "monitor_interval not provided"}, 400
        
@app.get("/get_monitor_interval")
async def get_monitor_interval():
    return {"monitor_interval": tms_config.monitor_interval}
    
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

    # Handle date filtering
    if ordered_date and ordered_date!='null':
        try:
            parsed_date = datetime.strptime(ordered_date, "%Y-%m-%d").date()
            query = query.filter(
                cast(OrderStatusLog.timestamp, DateTime) >= parsed_date)
            query = query.filter(
                cast(OrderStatusLog.timestamp, DateTime) < parsed_date + timedelta(days=1))
        except ValueError:
            return {"error": "Invalid date format. Please use YYYY-MM-DD."}
    else:
        today = date.today()
        query = query.filter(cast(OrderStatusLog.timestamp, DateTime) >= today)
        query = query.filter(
            cast(OrderStatusLog.timestamp, DateTime) < today + timedelta(days=1))

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
        scheduled_payload.append({
            "order_id": order.order_id,
            "client_id": order.client_id,
            "script_name": order.script_name,
            "price": int(round(order.price)) if order.price is not None else order.price,
            "qty": int(order.qty) if order.qty is not None else order.qty,
            "status": order.status,
            "order_type": order.order_type,
            "scanning_count": scanning_count,
            "current_price": int(round(scan_log.current_price)) if scan_log and scan_log.current_price is not None else None,
            "last_scan_at": scan_log.timestamp.isoformat() if scan_log and scan_log.timestamp else None,
            "live_status": _compute_scheduled_live_status(
                monitoring_active=tms_config.is_running,
                monitor_phase=monitor_phase,
                scanning_count=scanning_count,
            ),
        })

    combined_results = {
        "order_logs": [log.__dict__ for log in order_logs],
        "scheduled_orders": scheduled_payload,
        "monitoring_active": tms_config.is_running,
        "monitor_phase": monitor_phase,
        "monitor_status_message": tms_config.scheduled_status_message,
        "scheduled_started_at": (
            tms_config.scheduled_started_at.isoformat()
            if tms_config.scheduled_started_at
            else None
        ),
        "monitor_interval": tms_config.monitor_interval,
    }

    return combined_results


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

        order_book = await tms_user_instance.get_order_book()  # Await the async call
        return order_book

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


@app.get("/check_orders/")
async def check_orders_endpoint(db: Session = Depends(get_db)):
    if tms_config.is_running:
        return JSONResponse(status_code=400, content={"message": "Check orders loop is already running."})

    pending_orders = db.query(ScheduledOrder).filter_by(status="pending").all()
    for order in pending_orders:
        db.query(OrderLog).filter(
            OrderLog.client_id == order.client_id,
            OrderLog.script_name == order.script_name,
        ).delete(synchronize_session=False)
    db.commit()

    global check_orders_task
    from datetime import timezone

    tms_config.is_running = True
    tms_config.scheduled_started_at = datetime.now(timezone.utc)
    tms_config.scheduled_phase = "waiting_hours"
    tms_config.scheduled_status_message = "Armed — waiting for market"
    check_orders_task = asyncio.create_task(monitor_order_task_func())
    return {"message": "Check orders loop started."}


@app.get("/stop_check_orders/")
async def stop_check_orders_endpoint():
    global check_orders_task

    tms_config.is_running = False
    tms_config.scheduled_started_at = None
    tms_config.scheduled_phase = "stopped"
    tms_config.scheduled_status_message = ""
    task = check_orders_task
    if task is not None and not task.done():
        task.cancel()
    check_orders_task = None
    return {"message": "Check orders loop stopped."}


@app.get("/monitoring-status/")
async def monitoring_status():
    hours = get_market_hours_status(get_nepal_now())
    monitor_phase = tms_config.scheduled_phase if tms_config.is_running else "stopped"
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
            "phase": phase,
            "status_message": tms_config.grabber_status_message.get(session_id, ""),
            "started_at": started_at.isoformat() if started_at else None,
        })

    return {
        "scheduled_orders_active": tms_config.is_running,
        "scheduled_scanning": tms_config.is_running and monitor_phase == "active",
        "scheduled_phase": monitor_phase,
        "scheduled_status_message": tms_config.scheduled_status_message,
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
