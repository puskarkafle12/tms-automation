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
    resume_scan_count: Optional[int] = 0
    resume_previous_ltp: Optional[float] = 0.0
    resume_stable_rate: Optional[float] = None


class TmsAccountCreate(BaseModel):
    client_id: str
    broker_no: str
    password: str
    auto_login: bool = True


class TmsAccountUpdate(BaseModel):
    broker_no: Optional[str] = None
    password: Optional[str] = None
    auto_login: Optional[bool] = None