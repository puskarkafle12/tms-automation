from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import config.tms_config as tms_config
from config.app_environment import is_testing
from database import SessionLocal
from models.logged_in_user import LoggedInUsers
from models.scheduled_order import ScheduledOrder
from utils.log_sender import delete_order_log_scan_count
from utils.api_time import seconds_until_market_open
from utils.market_status import get_market_hours_status, get_nepal_now
from utils.monitor_order import monitor_order_task_func

logger = logging.getLogger(__name__)

SUPERVISOR_INTERVAL_SECONDS = 5
MARKET_OPEN_WAKE_WINDOW_SECONDS = 120


def has_logged_in_tms_users() -> bool:
    db = SessionLocal()
    try:
        return (
            db.query(LoggedInUsers)
            .filter(LoggedInUsers.status == "logged_in")
            .count()
            > 0
        )
    finally:
        db.close()


def should_auto_run_scheduler() -> bool:
    if not has_logged_in_tms_users():
        return False
    if is_testing():
        return True
    hours = get_market_hours_status(get_nepal_now())
    return bool(hours["market_hours_open"])


def should_keep_scheduler_running() -> bool:
    if not has_logged_in_tms_users():
        return False
    if is_testing():
        return True
    hours = get_market_hours_status(get_nepal_now())
    return bool(hours["market_hours_open"])


def get_scheduler_display_status() -> dict:
    """UI-facing scheduler state. Auto mode shows waiting, not stopped, outside market hours."""
    if tms_config.is_running:
        phase = tms_config.scheduled_phase or "armed"
        return {
            "scheduled_orders_active": True,
            "scheduled_scanning": phase == "active",
            "scheduled_phase": phase,
            "scheduled_status_message": (
                tms_config.scheduled_status_message or "Monitoring scheduled orders"
            ),
            "scheduled_auto_mode": True,
        }

    hours = get_market_hours_status(get_nepal_now())
    market_open = bool(hours["market_hours_open"])
    logged_in = has_logged_in_tms_users()

    if not market_open and not is_testing():
        return {
            "scheduled_orders_active": False,
            "scheduled_scanning": False,
            "scheduled_phase": "waiting_hours",
            "scheduled_status_message": "Auto — waiting for market to open",
            "scheduled_auto_mode": True,
        }
    if not market_open and is_testing():
        if not logged_in:
            return {
                "scheduled_orders_active": False,
                "scheduled_scanning": False,
                "scheduled_phase": "waiting_session",
                "scheduled_status_message": "Test mode — log in to a TMS account",
                "scheduled_auto_mode": True,
            }
        return {
            "scheduled_orders_active": False,
            "scheduled_scanning": False,
            "scheduled_phase": "armed",
            "scheduled_status_message": "Test mode — starting monitor (market hours bypassed)",
            "scheduled_auto_mode": True,
        }
    if not logged_in:
        return {
            "scheduled_orders_active": False,
            "scheduled_scanning": False,
            "scheduled_phase": "waiting_session",
            "scheduled_status_message": "Auto — log in to a TMS account",
            "scheduled_auto_mode": True,
        }
    return {
        "scheduled_orders_active": False,
        "scheduled_scanning": False,
        "scheduled_phase": "armed",
        "scheduled_status_message": "Auto — starting monitor…",
        "scheduled_auto_mode": True,
    }


async def start_scheduled_order_monitor(*, reset_logs: bool = False) -> bool:
    if tms_config.is_running:
        return False

    if reset_logs:
        db = SessionLocal()
        try:
            pending_orders = db.query(ScheduledOrder).filter_by(status="pending").all()
            for order in pending_orders:
                delete_order_log_scan_count(db, order.client_id, order.script_name)
            db.commit()
        finally:
            db.close()

    tms_config.is_running = True
    tms_config.scheduled_started_at = datetime.now(timezone.utc)
    if is_testing():
        tms_config.scheduled_phase = "armed"
        tms_config.scheduled_status_message = "Test mode — monitor running (market hours bypassed)"
    else:
        hours = get_market_hours_status(get_nepal_now())
        if hours["market_hours_open"]:
            tms_config.scheduled_phase = "active"
            tms_config.scheduled_status_message = "Monitoring scheduled orders"
        else:
            tms_config.scheduled_phase = "waiting_hours"
            tms_config.scheduled_status_message = "Auto — waiting for market"
    tms_config.check_orders_task = asyncio.create_task(monitor_order_task_func())
    return True


async def stop_scheduled_order_monitor() -> bool:
    if not tms_config.is_running:
        return False

    tms_config.is_running = False
    tms_config.scheduled_started_at = None
    tms_config.scheduled_phase = "stopped"
    tms_config.scheduled_status_message = ""

    task: Optional[asyncio.Task] = tms_config.check_orders_task
    tms_config.check_orders_task = None
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    return True


async def scheduled_monitor_supervisor_loop() -> None:
    while True:
        try:
            logged_in = has_logged_in_tms_users()

            if should_auto_run_scheduler() and not tms_config.is_running:
                await start_scheduled_order_monitor(reset_logs=False)
            elif tms_config.is_running and not should_keep_scheduler_running():
                await stop_scheduled_order_monitor()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Scheduled monitor supervisor tick failed")

        if is_testing():
            await asyncio.sleep(SUPERVISOR_INTERVAL_SECONDS)
            continue

        hours = get_market_hours_status(get_nepal_now())
        if hours["market_hours_open"]:
            await asyncio.sleep(SUPERVISOR_INTERVAL_SECONDS)
            continue

        wait_seconds = seconds_until_market_open()
        if wait_seconds <= 1:
            await asyncio.sleep(1)
        elif wait_seconds <= MARKET_OPEN_WAKE_WINDOW_SECONDS:
            await asyncio.sleep(min(wait_seconds, 1))
        else:
            await asyncio.sleep(min(wait_seconds, SUPERVISOR_INTERVAL_SECONDS))
