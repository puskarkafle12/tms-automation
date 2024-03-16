import asyncio
import sys
from typing import Dict
from fastapi import FastAPI, HTTPException, BackgroundTasks
from database import get_db
from models.order import Order
from schemas.schemas import OrderCreateRequest
from utils.base_functions import load_users
from utils.tms import Tms
import uvicorn
# Define the FastAPI application instance

app = FastAPI(debug=True)
db=get_db()

# Load user credentials
user_file_path = '/Users/pkafle/tms-automation/users.txt'
if not user_file_path:
    print("User credential file not found, exiting... ")
    sys.exit()
user = load_users(user_file_path)[0]

# Create an instance of Tms
tms = Tms(
    user['username'], user['password'], user['stock_symbol'],
    user['request_per_sec'], user['broker_no']
)

# Define your routes
@app.get("/")
async def read_root():
    return {"message": "Hello, FastAPI"}

@app.post("/add_order/")
async def add_order(order_data: OrderCreateRequest):
    db = get_db()
    order = Order(order_data.client_id, order_data.security_details, order_data.price, order_data.qty, order_data.status)
    db.add(order)
    db.commit()
    return {"message": "Order added successfully"}

@app.get("/check_orders/")
async def check_orders():
    while True:
        db = get_db()
        orders = db.query(Order).filter_by(status="pending").all()
        for order in orders:
            current_price = tms.get_stock_details(order.security_details['id']).get('ltp')
            if current_price <= order.price:
                order_response = tms.order(current_price, order.qty, order.security_details)
                order.status = "completed"
                db.commit()
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
