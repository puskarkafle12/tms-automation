# tasks.py

import asyncio
from datetime import datetime, time
from typing import Dict, Type
from sqlalchemy.orm import Session
from websockets.exceptions import ConnectionClosedError
from database import get_db

from utils.base_functions import is_within_time_range, truncate_to_one_decimal_place
from utils.log_sender import send_logs
from utils.tms import TmsUser
from utils.tms_user_loader import load_tms_users_instances
from models.scheduled_order import ScheduledOrder
from models.logged_in_user import LoggedInUsers
import config.tms_config as config  # Import the config module

async def monitor_order_task_func(db: Session):
    await send_logs("hello")
    tms_users_instances: Dict[str, Type[TmsUser]] = {}
    config.is_running = True  # Access the global variable using config module

    while config.is_running:
        config.count += 1  # Access and modify the global variable using config module
        current_time = datetime.now().time()

        if is_within_time_range(config.start_time, config.end_time, current_time):
            try:
                pending_orders = db.query(ScheduledOrder).filter_by(status="pending").all()
                client_ids = set(order.client_id for order in pending_orders)
                logged_out_clients = db.query(LoggedInUsers).filter(LoggedInUsers.status == "logged_out").all()
                logged_out_client_ids = [user.client_id for user in logged_out_clients]

                for client_id in logged_out_client_ids:
                    tms_users_instances.pop(client_id, None)

                for client_id in client_ids:
                    if client_id not in tms_users_instances:
                        try:
                            tms_users_instances = load_tms_users_instances(client_ids, tms_users_instances)
                        except Exception:
                            pass

                for order in pending_orders:
                    if order.client_id in tms_users_instances:
                        await send_logs(str(client_ids))
                        security_details = tms_users_instances[order.client_id].get_security_id(order.script_name)
                        current_price = tms_users_instances[order.client_id].get_stock_details(security_details['id']).get('ltp')
                        await send_logs(f"scanning count {config.count} ...")
                        await send_logs(f"{order.script_name} {str(current_price)}")

                        if truncate_to_one_decimal_place(current_price * 0.98) <= truncate_to_one_decimal_place(order.price) <= truncate_to_one_decimal_place(current_price * 1.02):
                            await send_logs(f"price matched trying to order ...")
                            logs = f"Order executed for {order.client_id}, script_name: {order.script_name}"
                            await send_logs(logs)
                            order.price = truncate_to_one_decimal_place(order.price)
                            order_response = tms_users_instances[order.client_id].order(order.price, order.qty, security=security_details, order_type=order.order_type)

                            if order_response.get('status') == 200:
                                order.status = "order_placed"
                                db.delete(order)
                            else:
                                order.status = "failed::" + str(order_response.get('message'))
                                db.delete(order)
                            db.commit()
            except ConnectionClosedError:
                logs = "WebSocket connection closed unexpectedly"
            except Exception as e:
                logs = f"An error occurred: {e}"
                await send_logs(logs)

            await asyncio.sleep(5)
        else:
            logs = "Session not active, Check orders loop stopped."
            config.is_running = False
            await send_logs(logs)
