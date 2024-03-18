import asyncio
import sys
from typing import Dict
from fastapi import FastAPI, HTTPException, BackgroundTasks,Depends, Query
from database import SessionLocal, get_db
from sqlalchemy import cast, Column, DateTime, func, Integer, String, JSON
from models.order import SheduldedOrder
from models.order_status_log import OrderStatusLog
from schemas.schemas import LoginRequest, OrderCreateRequest
from utils.base_functions import load_users
from utils.tms import TmsUser
import uvicorn
from sqlalchemy.orm import joinedload

from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from datetime import datetime, date, timedelta
from datetime import datetime, timedelta

from utils.tms_user_loader import load_tms_users_instances

app = FastAPI(debug=True)
# Load user credentials
user_file_path = '/Users/pkafle/tms-automation/users.txt'
if not user_file_path:
    print("User credential file not found, exiting... ")
    sys.exit()
user = load_users(user_file_path)[0]

# Create an instance of Tms
# tms = TmsUser(
#     username=user['username'], password=user['password'], stock_symbol=user['stock_symbol'],
#     request_per_sec=user['request_per_sec'],broker_no= user['broker_no']
# )

# Define your routes
@app.get("/")
async def read_root():
    return {"message": "Hello, FastAPI"}



@app.post("/login/")
async def login(login_request: LoginRequest):
        tms_instance = TmsUser(username=login_request.username, password=login_request.password, stock_symbol=login_request.stock_symbol, broker_no=login_request.broker_no, request_per_sec=login_request.request_per_sec)
        login_status = tms_instance.try_cached_login()
        if login_status.get("status")=="success":
            return {"message": login_status}
        else:
            raise HTTPException(status_code=500, detail=login_status)
@app.post("/add_order/")
async def add_order(order_data: OrderCreateRequest,db: Session = Depends(get_db)):
    order = SheduldedOrder(order_data)
    db.add(order)
    db.commit()
    return {"message": "Order added successfully"}
from sqlalchemy.orm import join

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
    if ordered_date:
        try:
            parsed_date = datetime.strptime(ordered_date, "%Y-%m-%d").date()
            query = query.filter(cast(OrderStatusLog.timestamp, DateTime) >= parsed_date)
            query = query.filter(cast(OrderStatusLog.timestamp, DateTime) < parsed_date + timedelta(days=1))
        except ValueError:
            return {"error": "Invalid date format. Please use YYYY-MM-DD."}
    else:
        today = date.today()
        query = query.filter(cast(OrderStatusLog.timestamp, DateTime) >= today)
        query = query.filter(cast(OrderStatusLog.timestamp, DateTime) < today + timedelta(days=1))

    order_logs = query.all()

    # Perform a separate query to retrieve SheduldedOrder data
    scheduled_orders = db.query(SheduldedOrder).filter(SheduldedOrder.client_id == client_id).all()

    # Combine the results
    combined_results = {
        "order_logs": [log.__dict__ for log in order_logs],
        "scheduled_orders": [order.__dict__ for order in scheduled_orders]
    }

    return combined_results
    
@app.get("/check_orders/")
async def check_orders(db: Session = Depends(get_db)):
    tms_users_instances={}
    while True:
        try:
            pending_orders = db.query(SheduldedOrder).filter_by(status="pending").all()
            client_ids=[order.client_id for order in pending_orders ]
            for client_id in client_ids:
                if client_id not in tms_users_instances.keys():
                    try:
                        tms_users_instances:Dict=load_tms_users_instances(client_ids,tms_users_instances)
                    except Exception as e:
                        pass
            for order in pending_orders:
                security_details = tms_users_instances[order.client_id].get_securities_ids(order.script_name)
                current_price = tms_users_instances[order.client_id].get_stock_details(security_details['id']).get('ltp')
                if current_price * 0.98 <= order.price <= current_price * 1.02 or current_price<=order.price:
                    order_response = tms_users_instances[order.client_id].order(current_price, order.qty, security_details)
                    if order_response.get('status')==200:
                        order.status="completed"
                    else :
                        order.status="failed::"+str(order_response.get('message'))
                    db.delete(order)
                    db.commit()
        except Exception as e:
            # Log the exception
            print(f"An error occurred: {e}")
        await asyncio.sleep(4)



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
    raise HTTPException(status_code=404, detail="Route not found")

# Run the FastAPI application
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8003 ,reload=True)
    print("Server is running at http://0.0.0.0:8000")
