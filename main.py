import logging
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import sys
from typing import Dict, List, Type
from fastapi import FastAPI, HTTPException, Depends, Query, WebSocketDisconnect
from fastapi.responses import JSONResponse
import websockets
from database import get_db
from sqlalchemy import cast, DateTime
from exceptions.login_exceptions import LoginFailedException
from models.frontend_user import FrontendUser
from models.logged_in_user import LoggedInUsers
from models.order_log import OrderLog
from models.scheduled_order import ScheduledOrder
from models.order_status_log import OrderStatusLog
from models.user import User
from schemas.schemas import LoginRequest, OrderCreateRequest, UserLogin
from utils.base_functions import is_within_time_range, truncate_to_one_decimal_place
from utils.monitor_order import monitor_order_task_func
from utils.tms import TmsUser
import uvicorn
import jwt
from fastapi import FastAPI, Request, HTTPException
from sqlalchemy.orm import Session
from datetime import date, time, timedelta, datetime

from utils.tms_user_loader import load_tms_users_instances
import config.tms_config as tms_config
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
    return {"message": "Hello, FastAPI"}


@app.post("/login/")
async def login(login_request: LoginRequest, db: Session = Depends(get_db)):
    enc_password = TmsUser.encode_base64(login_request.password)
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
        raise HTTPException(status_code=500, detail=str(e))

    if login_status.get("status") == "success":
        return {"message": login_status}, 200
    else:
        raise HTTPException(status_code=401, detail="Login failed")


@app.delete("/cancel_order/")
async def cancel_order(client_id: str, exchange_order_id: str, db: Session = Depends(get_db)):
    try:
        # Retrieve user from the database based on client_id
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
        await tms_user_instance.try_cached_login()  # Await the async call

        # Cancel the order
        # Await the async call
        response = await tms_user_instance.cancel_order(exchange_order_id)

        # Return the response
        return response

    except LoginFailedException as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
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
        logged_in_users = db.query(LoggedInUsers).filter(
            LoggedInUsers.status == "logged_in").all()
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

    # Perform a separate query to retrieve ScheduledOrder data
    scheduled_orders = db.query(ScheduledOrder).filter(
        ScheduledOrder.client_id == client_id).all()

    # Combine the results
    combined_results = {
        "order_logs": [log.__dict__ for log in order_logs],
        "scheduled_orders": [order.__dict__ for order in scheduled_orders]
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

    tms_user = TmsUser(broker_no=user.broker_no,
                       username=user.client_id, password=user.password)
    await tms_user.try_cached_login()  # Await the async call
    try:
        order_history = await tms_user.get_order_history()  # Await the async call
        return order_history
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/dp_holdings")
async def get_dp_holdings(client_id: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.client_id == client_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    tms_user = TmsUser(broker_no=user.broker_no,
                       username=user.client_id, password=user.password)
    await tms_user.try_cached_login()  # Await the async call
    try:
        dp_holdings = await tms_user.get_user_stock_details()  # Await the async call
        return dp_holdings
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/get_order_book")
async def get_order_book(client_id: str, db: Session = Depends(get_db)):
    try:
        user = db.query(User).filter(User.client_id == client_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        tms_user_instance = TmsUser(
            broker_no=user.broker_no,
            username=user.client_id,
            password=user.password,
        )

        await tms_user_instance.try_cached_login()  # Await the async call

        order_book = await tms_user_instance.get_order_book()  # Await the async call
        return order_book

    except LoginFailedException as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/get_script_details")
async def get_script_details(client_id: str, db: Session = Depends(get_db)):
    try:
        user = db.query(User).filter(User.client_id == client_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        tms_user_instance = TmsUser(
            broker_no=user.broker_no,
            username=user.client_id,
            password=user.password,
        )

        await tms_user_instance.try_cached_login()  # Await the async call

        stock_data = await tms_user_instance.fetch_securities_details()  # Await the async call
        return stock_data

    except LoginFailedException as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/check_orders/")
async def check_orders_endpoint(db: Session = Depends(get_db)):
    if tms_config.is_running:
        return JSONResponse(status_code=400, content={"message": "Check orders loop is already running."})

    global check_orders_task
    check_orders_task = asyncio.create_task(
        monitor_order_task_func(db))  # Keep as is, no changes needed
    return {"message": "Check orders loop started."}


@app.get("/stop_check_orders/")
async def stop_check_orders_endpoint():
    global check_orders_task

    if not tms_config.is_running:
        return JSONResponse(status_code=400, content={"message": "Check orders loop is not running."})

    tms_config.is_running = False
    check_orders_task.cancel()
    return {"message": "Check orders loop stopped."}

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
    host = "0.0.0.0"
    port = 8000
    uvicorn.run(app, host=host, port=port, reload=True)
    print(f"Server is running at {host}:{port} ")
