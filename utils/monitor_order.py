# tasks.py

import asyncio
from dataclasses import dataclass
from typing import Dict, Optional, Type

from database import SessionLocal
from models.logged_in_user import LoggedInUsers
from models.order_status_log import OrderStatusLog
from models.scheduled_order import ScheduledOrder
from utils.base_functions import truncate_to_one_decimal_place
from utils.log_sender import store_or_update_logs
from utils.market_status import (
    MARKET_HOURS_LABEL,
    is_market_hours_open,
    parse_session_check_response,
)
from utils.tms import TmsUser
from utils.tms_user_loader import load_tms_users_instances
import config.tms_config as config


MAX_PRICE_FETCH_CONCURRENCY = 5


@dataclass
class PendingOrderSnapshot:
    order_id: int
    client_id: str
    security_details: dict
    script_name: str
    price: float
    qty: int
    order_type: str


@dataclass
class OrderQuoteSnapshot:
    order: PendingOrderSnapshot
    scan_count: int
    security_details: Optional[dict]
    current_price: Optional[float]
    high_price: Optional[float] = None
    error_message: Optional[str] = None


def _load_monitor_cycle_data():
    db = SessionLocal()
    try:
        pending_orders = db.query(ScheduledOrder).filter_by(status="pending").all()
        snapshots = [
            PendingOrderSnapshot(
                order_id=order.order_id,
                client_id=order.client_id,
                security_details=order.security_details or {},
                script_name=order.script_name,
                price=order.price,
                qty=order.qty,
                order_type=order.order_type,
            )
            for order in pending_orders
        ]
        client_ids = {order.client_id for order in pending_orders}
        logged_out_client_ids = [
            user.client_id
            for user in db.query(LoggedInUsers).filter(LoggedInUsers.status == "logged_out").all()
        ]
        return snapshots, client_ids, logged_out_client_ids
    finally:
        db.close()


def _status_log_from_order(order: ScheduledOrder) -> OrderStatusLog:
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


async def _check_tms_session(tms_users_instances: Dict[str, TmsUser]) -> tuple[bool, str]:
    if not tms_users_instances:
        return False, "No logged-in TMS clients"

    for tms_user in tms_users_instances.values():
        try:
            payload = await tms_user.check_exchange_session()
            parsed = parse_session_check_response(payload)
            return parsed["session_active"], parsed["session_message"]
        except Exception:
            continue

    return False, "Unable to check TMS session"


async def _resolve_execution_gate(tms_users_instances: Dict[str, TmsUser]) -> dict:
    if not is_market_hours_open():
        return {
            "can_execute": False,
            "reason": f"Market closed — waiting for trading hours ({MARKET_HOURS_LABEL})",
            "session_active": False,
        }

    session_active, session_message = await _check_tms_session(tms_users_instances)
    if not session_active:
        return {
            "can_execute": False,
            "reason": f"Waiting for TMS session — {session_message}",
            "session_active": False,
        }

    return {
        "can_execute": True,
        "reason": "",
        "session_active": True,
    }


async def monitor_order_task_func():
    tms_users_instances: Dict[str, Type[TmsUser]] = {}
    count_dict = {}
    security_cache = {}
    price_fetch_sem = asyncio.Semaphore(MAX_PRICE_FETCH_CONCURRENCY)

    try:
        while config.is_running:
            pending_orders = []
            try:
                pending_orders, client_ids, logged_out_client_ids = await asyncio.to_thread(
                    _load_monitor_cycle_data
                )

                for client_id in logged_out_client_ids:
                    tms_users_instances.pop(client_id, None)

                missing_client_ids = [
                    client_id for client_id in client_ids
                    if client_id not in tms_users_instances
                ]
                if missing_client_ids:
                    try:
                        tms_users_instances = await load_tms_users_instances(client_ids, tms_users_instances)
                    except Exception:
                        pass

                execution_gate = await _resolve_execution_gate(tms_users_instances)

                async def fetch_order_snapshot(order: PendingOrderSnapshot) -> OrderQuoteSnapshot:
                    key = (order.client_id, order.script_name)
                    count_dict[key] = count_dict.get(key, 0) + 1
                    scan_count = count_dict[key]

                    tms_user = tms_users_instances.get(order.client_id)
                    if not tms_user:
                        return OrderQuoteSnapshot(
                            order=order,
                            scan_count=scan_count,
                            security_details=None,
                            current_price=None,
                            error_message=f"Client ID {order.client_id} is not logged in.",
                        )

                    try:
                        security_key = (order.client_id, order.script_name.upper())
                        security_details = security_cache.get(security_key)
                        if not security_details:
                            security_details = await tms_user.get_security_id(order.script_name)
                            if security_details:
                                security_cache[security_key] = security_details

                        if not security_details:
                            return OrderQuoteSnapshot(
                                order=order,
                                scan_count=scan_count,
                                security_details=None,
                                current_price=None,
                                error_message=f"Security not found for {order.script_name}",
                            )

                        async with price_fetch_sem:
                            quote = await tms_user.get_stock_details_async(
                                security_details["id"],
                                max_retries=1,
                            )
                        if quote is None:
                            return OrderQuoteSnapshot(
                                order=order,
                                scan_count=scan_count,
                                security_details=security_details,
                                current_price=None,
                                error_message="Price fetch failed",
                            )

                        return OrderQuoteSnapshot(
                            order=order,
                            scan_count=scan_count,
                            security_details=security_details,
                            current_price=quote.get("ltp"),
                            high_price=quote.get("high"),
                        )
                    except Exception as exc:
                        return OrderQuoteSnapshot(
                            order=order,
                            scan_count=scan_count,
                            security_details=None,
                            current_price=None,
                            error_message=f"An error occurred: {exc}",
                        )

                snapshots = await asyncio.gather(
                    *(fetch_order_snapshot(order) for order in pending_orders)
                )

                db = SessionLocal()
                try:
                    for snapshot in snapshots:
                        order = snapshot.order
                        key = (order.client_id, order.script_name)

                        if snapshot.error_message:
                            await store_or_update_logs(
                                db,
                                order.client_id,
                                order.script_name,
                                snapshot.scan_count,
                                snapshot.current_price or 0,
                                False,
                                snapshot.error_message,
                                commit=False,
                            )
                            continue

                        if snapshot.current_price is None or not snapshot.security_details:
                            continue

                        log_entry = await store_or_update_logs(
                            db,
                            order.client_id,
                            order.script_name,
                            snapshot.scan_count,
                            snapshot.current_price,
                            False,
                            commit=False,
                        )
                        if log_entry.scanning_count > count_dict[key]:
                            count_dict[key] = log_entry.scanning_count

                        target_price = truncate_to_one_decimal_place(order.price)
                        current_price = float(snapshot.current_price)
                        if (
                            truncate_to_one_decimal_place(current_price * 0.98)
                            <= target_price
                            <= truncate_to_one_decimal_place(current_price * 1.02)
                        ):
                            if not execution_gate["can_execute"]:
                                await store_or_update_logs(
                                    db,
                                    order.client_id,
                                    order.script_name,
                                    count_dict[key],
                                    current_price,
                                    False,
                                    execution_gate["reason"],
                                    commit=False,
                                )
                                continue

                            if order.order_type.lower() == "buy" and snapshot.high_price is not None:
                                day_high = truncate_to_one_decimal_place(float(snapshot.high_price))
                                if target_price > day_high:
                                    await store_or_update_logs(
                                        db,
                                        order.client_id,
                                        order.script_name,
                                        count_dict[key],
                                        current_price,
                                        False,
                                        (
                                            f"Buy price ({target_price}) exceeds today's high "
                                            f"({day_high}) for {order.script_name}"
                                        ),
                                        commit=False,
                                    )
                                    continue

                            tms_user = tms_users_instances[order.client_id]
                            order_response = await tms_user.order(
                                target_price,
                                order.qty,
                                security=snapshot.security_details,
                                order_type=order.order_type,
                            )

                            db_order = db.query(ScheduledOrder).filter_by(order_id=order.order_id).first()
                            if not db_order:
                                continue

                            if order_response.get("status") == 200:
                                db_order.status = "order_placed"
                                await store_or_update_logs(
                                    db,
                                    order.client_id,
                                    order.script_name,
                                    count_dict[key],
                                    current_price,
                                    True,
                                    f"Order placed for {order.script_name}",
                                    commit=False,
                                )
                            else:
                                db_order.status = "failed::" + str(order_response.get("message"))
                                await store_or_update_logs(
                                    db,
                                    order.client_id,
                                    order.script_name,
                                    count_dict[key],
                                    current_price,
                                    False,
                                    f"Failed to place order for {order.script_name}: {order_response.get('message')}",
                                    commit=False,
                                )

                            db.add(_status_log_from_order(db_order))
                            db.delete(db_order)
                    db.commit()
                finally:
                    db.close()

            except Exception as exc:
                db = SessionLocal()
                try:
                    for order in pending_orders:
                        await store_or_update_logs(
                            db,
                            order.client_id,
                            order.script_name,
                            count_dict.get((order.client_id, order.script_name), 0),
                            0,
                            False,
                            f"An error occurred: {exc}",
                            commit=False,
                        )
                    db.commit()
                finally:
                    db.close()

            if not config.is_running:
                break

            try:
                await asyncio.sleep(config.monitor_interval)
            except asyncio.CancelledError:
                break
    finally:
        config.is_running = False
