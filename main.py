import logging
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import sys
from typing import Dict, Type
from fastapi import FastAPI, HTTPException, Depends, Query, WebSocketDisconnect
from fastapi.responses import JSONResponse
import websockets
from database import get_db
from sqlalchemy import cast, DateTime
from exceptions.login_exceptions import LoginFailedException
from models.frontend_user import FrontendUser
from models.logged_in_user import LoggedInUsers
from models.scheduled_order import ScheduledOrder
from models.order_status_log import OrderStatusLog
from models.user import User
from schemas.schemas import LoginRequest, OrderCreateRequest, UserLogin
from utils.base_functions import is_within_time_range, load_users, truncate_to_one_decimal_place
from utils.tms import TmsUser
import uvicorn
import jwt
from fastapi import FastAPI, WebSocket

from sqlalchemy.orm import Session
from datetime import date, time, timedelta, datetime

from utils.tms_user_loader import load_tms_users_instances

app = FastAPI(debug=True)
SECRET_KEY = "your_secret_key_here"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)
# Load user credentials
# to disable the warnings in the logs
logging.disable(logging.WARNING)
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
async def login(login_request: LoginRequest, db: Session = Depends(get_db)):
    tms_instance = TmsUser(
        username=login_request.username, password=login_request.password, stock_symbol=login_request.stock_symbol,
        broker_no=login_request.broker_no, request_per_sec=login_request.request_per_sec
    )
    try:
        login_status = tms_instance.try_cached_login()
    except LoginFailedException as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    if login_status.get("status") == "success":

        return {"message": login_status}, 200
    else:
        raise HTTPException(status_code=401, detail="Login failed")

@app.delete("/cancel_order/")
async def cancel_order(client_id: str, exchange_order_id: str):
    try:
        # Retrieve user from the database based on client_id
        db = get_db()
        user = db.query(User).filter(User.client_id == client_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Instantiate TmsUser with user credentials
        tms_user_instance = TmsUser(
            broker_no=user.broker_no,
            username=user.client_id,
            password=user.password,
        )

        # Try to login
        tms_user_instance.try_cached_login()

        # Cancel the order
        response = tms_user_instance.cancel_order(exchange_order_id)

        # Return the response
        return response

    except LoginFailedException as e:
        # Handle login failure
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        # Handle other errors
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/add_order/")
async def add_order(order_data: OrderCreateRequest, db: Session = Depends(get_db)):
    order = ScheduledOrder(order_data)
    db.add(order)
    db.commit()
    return {"message": "Order added successfully"}

@app.get("/logged_in_clients/")
async def get_logged_in_clients(db: Session = Depends(get_db)):
    try:
        logged_in_users = db.query(LoggedInUsers).filter(LoggedInUsers.status == "logged_in").all()
        client_ids = [user.client_id for user in logged_in_users]
        return {"logged_in_client_ids": client_ids}
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
        deleted_count = db.query(ScheduledOrder).filter(
            ScheduledOrder.order_id == order_id).delete()
    elif client_id and script_name:
        deleted_count = db.query(ScheduledOrder).filter(
            ScheduledOrder.client_id == client_id,
            ScheduledOrder.script_name == script_name
        ).delete()
    else:
        raise HTTPException(
            status_code=400, detail="Invalid parameters. Specify order_id or client_id and script_name.")

    db.commit()

    if deleted_count == 0:
        raise HTTPException(status_code=404, detail="Order not found")

    return {"message": "Order deleted successfully"}


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

    # Perform a separate query to retrieve ScheduledOrder data
    scheduled_orders = db.query(ScheduledOrder).filter(
        ScheduledOrder.client_id == client_id).all()

    # Combine the results
    combined_results = {
        "order_logs": [log.__dict__ for log in order_logs],
        "scheduled_orders": [order.__dict__ for order in scheduled_orders]
    }

    return combined_results



# Keep track of connected WebSocket clients
active_websockets: Dict[WebSocket, str] = {}

# Function to send logs to all connected clients


async def send_logs(logs: str):
    # Create a copy of the dictionary to avoid RuntimeError
    for ws, _ in list(active_websockets.items()):
        try:
            await ws.send_text(logs)
        except websockets.exceptions.ConnectionClosedError:
            del active_websockets[ws]
        except websockets.ConnectionClosedOK:
            del active_websockets[ws]


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_websockets[websocket] = ""
    try:
        while True:
            await asyncio.sleep(5)  # Keep WebSocket connection alive
    except WebSocketDisconnect:
        del active_websockets[websocket]
    except websockets.ConnectionClosedOK:
        del active_websockets[websocket]


start_time = time(hour=11, minute=0)
end_time = time(hour=15, minute=0)
count = 0
is_running = False
check_orders_task = None

async def check_orders_task_func(db: Session):
    global is_running
    tms_users_instances: Dict[str, Type[TmsUser]] = {}
    global start_time
    global end_time
    global count

    is_running = True
    while is_running:
        count += 1
        current_time = datetime.now().time()
        if is_within_time_range(start_time, end_time, current_time):
            try:
                pending_orders = db.query(ScheduledOrder).filter_by(
                    status="pending").all()
                client_ids = set(order.client_id for order in pending_orders)
                logged_out_clients = db.query(LoggedInUsers).filter(
                    LoggedInUsers.status == "logged_out").all()
                logged_out_client_ids = [
                    user.client_id for user in logged_out_clients]
                for client_id in logged_out_client_ids:
                    tms_users_instances.pop(client_id, None)
                for client_id in client_ids:
                    if client_id not in tms_users_instances.keys():
                        try:
                            tms_users_instances: Dict = load_tms_users_instances(
                                client_ids, tms_users_instances)
                        except Exception as e:
                            pass
                for order in pending_orders:
                    if order.client_id in tms_users_instances.keys():
                        await send_logs(str(client_ids))
                        security_details = tms_users_instances[order.client_id].get_security_id(
                            order.script_name)
                        current_price = tms_users_instances[order.client_id].get_stock_details(
                            security_details['id']).get('ltp')
                        await send_logs(f"scanning count {count} ...")
                        await send_logs(f"{order.script_name} {str(current_price)}")
                        if truncate_to_one_decimal_place(current_price * 0.98) <= truncate_to_one_decimal_place(order.price) <= truncate_to_one_decimal_place(current_price * 1.02):
                            await send_logs(f"price matched trying to order ...")
                            logs = f"Order executed for {
                                order.client_id}, script_name: {order.script_name}"
                            await send_logs(logs)
                            order.price = truncate_to_one_decimal_place(
                                order.price)
                            order_response = tms_users_instances[order.client_id].order(
                                order.price, order.qty, security=security_details,order_type=order.order_type)
                            if order_response.get('status') == 200:
                                order.status = "order_placed"
                                db.delete(order)
                            else:
                                order.status = "failed::" + \
                                    str(order_response.get('message'))
                                db.delete(order)
                            db.commit()
            except websockets.exceptions.ConnectionClosedError:
                # Handle the ConnectionClosedError
                logs = "WebSocket connection closed unexpectedly"
                # await send_logs(logs)
            except Exception as e:
                logs = f"An error occurred: {e}"
                await send_logs(logs)
            await asyncio.sleep(5)
        else:
            logs = "Session not active, Check orders loop stopped."
            is_running=False
            await send_logs(logs)
@app.get("/order_history")
async def get_order_history(client_id: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.client_id == client_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    tms_user = TmsUser(broker_no=user.broker_no, username=user.client_id, password=user.password)
    tms_user.try_cached_login()
    try:
        order_history = tms_user.get_order_history()
        return order_history
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@app.get("/dp_holdings")
async def get_dp_holdings(client_id: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.client_id == client_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    tms_user = TmsUser(broker_no=user.broker_no, username=user.client_id, password=user.password)
    tms_user.try_cached_login()
    try:
        dp_holdings = tms_user.get_user_stock_details()
        return dp_holdings
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/get_order_book")
async def get_order_book(client_id: str):
    try:
        db = get_db()
        user = db.query(User).filter(User.client_id == client_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        tms_user_instance = TmsUser(
            broker_no=user.broker_no,
            username=user.client_id,
            password=user.password,
        )

        tms_user_instance.try_cached_login()

        order_book = tms_user_instance.get_order_book()
        return order_book

    except LoginFailedException as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/check_orders/")
async def check_orders_endpoint(db: Session = Depends(get_db)):
    global is_running
    global check_orders_task

    if is_running:
        return JSONResponse(status_code=400, content={"message": "Check orders loop is already running."})

    check_orders_task = asyncio.create_task(check_orders_task_func(db))
    return {"message": "Check orders loop started."}

@app.get("/stop_check_orders/")
async def stop_check_orders_endpoint():
    global is_running
    global check_orders_task

    if not is_running:
        return JSONResponse(status_code=400, content={"message": "Check orders loop is not running."})

    is_running = False
    check_orders_task.cancel()
    return {"message": "Check orders loop stopped."}

@app.post("/frontend-login")
def frontend_login(user_login: UserLogin, db: Session = Depends(get_db)):
    user = FrontendUser.authenticate(
        user_login.username, user_login.password, db)
    if not user:
        raise HTTPException(
            status_code=401, detail="Invalid username or password")

    # Generate JWT token
    timestamp = datetime.utcnow().timestamp()
    payload = {
        "username": user_login.username,
        "password": user_login.password,
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
    raise HTTPException(status_code=404, detail="Route not found")

# Run the FastAPI application
if __name__ == "__main__":
    host="0.0.0.0"
    port=8000
    uvicorn.run(app, host=host, port=port, reload=True)
    print(f"Server is running at {host}:{port} ")
