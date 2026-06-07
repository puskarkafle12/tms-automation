# tasks.py

import asyncio
from datetime import datetime
from typing import Dict, Type
from sqlalchemy.orm import Session
from database import get_db

from utils.base_functions import is_within_time_range, truncate_to_one_decimal_place
from utils.log_sender import store_or_update_logs  # Import store_or_update_logs function
from utils.tms import TmsUser
from utils.tms_user_loader import load_tms_users_instances
from models.scheduled_order import ScheduledOrder
from models.logged_in_user import LoggedInUsers
import config.tms_config as config  # Import the config module

async def monitor_order_task_func(db: Session):
    tms_users_instances: Dict[str, Type[TmsUser]] = {}
    config.is_running = True
    # Create a dictionary to keep counts for each (client_id, script_name) pair
    count_dict = {}

    while config.is_running:
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
                            tms_users_instances = await load_tms_users_instances(client_ids, tms_users_instances)
                        except Exception:
                            pass

                for order in pending_orders:
                    # Initialize the count for the (client_id, script_name) if not present
                    key = (order.client_id, order.script_name)
                    if key not in count_dict:
                        count_dict[key] = 0
                    count_dict[key] += 1  # Increment the count for this specific client_id and script_name

                    if order.client_id in tms_users_instances:
                        security_details = await tms_users_instances[order.client_id].get_security_id(order.script_name)
                        current_price = await tms_users_instances[order.client_id].get_stock_details_async(security_details['id'])
                        current_price = current_price.get('ltp')
                        log_entry=await store_or_update_logs(db, order.client_id, order.script_name, count_dict[key], current_price, False)
                        if log_entry.scanning_count>count_dict[key]:
                            count_dict[key]=log_entry.scanning_count
                        if truncate_to_one_decimal_place(current_price * 0.98) <= truncate_to_one_decimal_place(order.price) <= truncate_to_one_decimal_place(current_price * 1.02):
                            order.price = truncate_to_one_decimal_place(order.price)
                            order_response = await tms_users_instances[order.client_id].order(order.price, order.qty, security=security_details, order_type=order.order_type)

                            if order_response.get('status') == 200:
                                order.status = "order_placed"
                                await store_or_update_logs(db, order.client_id, order.script_name, count_dict[key], current_price, True, f"Order placed for {order.script_name}")
                                db.delete(order)
                            else:
                                await store_or_update_logs(db, order.client_id, order.script_name, count_dict[key], current_price, False, f"Failed to place order for {order.script_name}: {order_response.get('message')}")
                                order.status = "failed::" + str(order_response.get('message'))
                                db.delete(order)
                            db.commit()
                    else:
                        logs = f"Client ID {order.client_id} is not logged in."
                        await store_or_update_logs(db, order.client_id, order.script_name, count_dict[key], 0, False, logs)

            except Exception as e:
                # Log the error with client_id and script_name if available
                for order in pending_orders:
                    await store_or_update_logs(db, order.client_id, order.script_name,count_dict.get((order.client_id, order.script_name),''), 0, False, f"An error occurred: {e}")

            await asyncio.sleep(config.monitor_interval)
        else:
            logs = "Session not active, Check orders loop stopped."
            config.is_running = False
            # Log the session end message for each client_id and script_name
            for order in pending_orders:
                await store_or_update_logs(db, order.client_id, order.script_name, count_dict[(order.client_id, order.script_name)], 0, False, logs)
