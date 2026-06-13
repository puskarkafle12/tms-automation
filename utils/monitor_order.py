# tasks.py

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Type

from database import SessionLocal

from utils.base_functions import is_within_time_range, truncate_to_one_decimal_place
from utils.log_sender import store_or_update_logs_sync
from utils.tms import TmsUser
from utils.tms_user_loader import load_tms_users_instances
from models.scheduled_order import ScheduledOrder
from models.logged_in_user import LoggedInUsers
import config.tms_config as config


@dataclass
class PendingOrderSnapshot:
    order_id: int
    client_id: str
    script_name: str
    price: float
    qty: int
    order_type: str


def _load_monitor_cycle_data():
    db = SessionLocal()
    try:
        pending_orders = db.query(ScheduledOrder).filter_by(status="pending").all()
        snapshots = [
            PendingOrderSnapshot(
                order_id=order.order_id,
                client_id=order.client_id,
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


def _finalize_order_sync(order_id: int, status: str, delete_order: bool):
    db = SessionLocal()
    try:
        order = db.query(ScheduledOrder).filter_by(order_id=order_id).first()
        if not order:
            return
        if delete_order:
            db.delete(order)
        else:
            order.status = status
        db.commit()
    finally:
        db.close()


async def monitor_order_task_func():
    tms_users_instances: Dict[str, Type[TmsUser]] = {}
    count_dict = {}

    try:
        while config.is_running:
            current_time = datetime.now().time()

            if not is_within_time_range(config.start_time, config.end_time, current_time):
                break

            pending_orders = []
            try:
                pending_orders, client_ids, logged_out_client_ids = await asyncio.to_thread(
                    _load_monitor_cycle_data
                )

                if not config.is_running:
                    break

                for client_id in logged_out_client_ids:
                    tms_users_instances.pop(client_id, None)

                missing_clients = [client_id for client_id in client_ids if client_id not in tms_users_instances]
                if missing_clients:
                    try:
                        tms_users_instances = await load_tms_users_instances(client_ids, tms_users_instances)
                    except Exception:
                        pass

                for order in pending_orders:
                    if not config.is_running:
                        break
                    key = (order.client_id, order.script_name)
                    if key not in count_dict:
                        count_dict[key] = 0
                    count_dict[key] += 1

                    if order.client_id not in tms_users_instances:
                        await asyncio.to_thread(
                            store_or_update_logs_sync,
                            order.client_id,
                            order.script_name,
                            count_dict[key],
                            0,
                            False,
                            f"Client ID {order.client_id} is not logged in.",
                        )
                        continue

                    tms_user = tms_users_instances[order.client_id]
                    security_details = await tms_user.get_security_id(order.script_name)
                    if not security_details:
                        continue

                    quote = await tms_user.get_stock_details_async(security_details['id'])
                    current_price = quote.get('ltp')
                    if current_price is None:
                        continue

                    log_entry = await asyncio.to_thread(
                        store_or_update_logs_sync,
                        order.client_id,
                        order.script_name,
                        count_dict[key],
                        current_price,
                        False,
                    )
                    if log_entry.scanning_count > count_dict[key]:
                        count_dict[key] = log_entry.scanning_count

                    target_price = truncate_to_one_decimal_place(order.price)
                    if (
                        truncate_to_one_decimal_place(current_price * 0.98)
                        <= target_price
                        <= truncate_to_one_decimal_place(current_price * 1.02)
                    ):
                        order_response = await tms_user.order(
                            target_price,
                            order.qty,
                            security=security_details,
                            order_type=order.order_type,
                        )

                        if order_response.get('status') == 200:
                            await asyncio.to_thread(
                                store_or_update_logs_sync,
                                order.client_id,
                                order.script_name,
                                count_dict[key],
                                current_price,
                                True,
                                f"Order placed for {order.script_name}",
                            )
                            await asyncio.to_thread(_finalize_order_sync, order.order_id, "order_placed", True)
                        else:
                            await asyncio.to_thread(
                                store_or_update_logs_sync,
                                order.client_id,
                                order.script_name,
                                count_dict[key],
                                current_price,
                                False,
                                f"Failed to place order for {order.script_name}: {order_response.get('message')}",
                            )
                            await asyncio.to_thread(
                                _finalize_order_sync,
                                order.order_id,
                                "failed::" + str(order_response.get('message')),
                                True,
                            )
            except Exception as exc:
                for order in pending_orders:
                    await asyncio.to_thread(
                        store_or_update_logs_sync,
                        order.client_id,
                        order.script_name,
                        count_dict.get((order.client_id, order.script_name), 0),
                        0,
                        False,
                        f"An error occurred: {exc}",
                    )

            if not config.is_running:
                break

            try:
                await asyncio.sleep(config.monitor_interval)
            except asyncio.CancelledError:
                break
    finally:
        config.is_running = False
