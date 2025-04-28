# schemas.py

from pydantic import BaseModel
from typing import Dict, Optional
class OrderCreateRequest(BaseModel):
    client_id: str
    security_details: Dict={}
    script_name:str
    price: float
    qty: int
    order_type: str
    status: str = "pending"

class LoginRequest(BaseModel):
    username: str
    password: str
    stock_symbol: str
    broker_no: str
    request_per_sec: int


class UserLogin(BaseModel):
    username: str
    password: str
class StockGrabberRequest(BaseModel):
    client_id: str
    stock_symbol: str
    order_quantity: int
    max_order_limit: Optional[int] = 0
    request_per_sec: Optional[float] = 2.0