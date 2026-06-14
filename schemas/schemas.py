# schemas.py

from pydantic import BaseModel
from datetime import datetime
from typing import Any, Dict, Optional
class OrderCreateRequest(BaseModel):
    client_id: str
    security_details: Dict={}
    script_name:str
    price: float
    qty: int
    order_type: str
    status: str = "pending"
    strategy_type: Optional[str] = "Fixed Price"
    side: Optional[str] = None
    symbol: Optional[str] = None
    company_name: Optional[str] = None
    remaining_quantity: Optional[int] = None
    limit_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    stop_limit_price: Optional[float] = None
    book_profit_price: Optional[float] = None
    profit_target_price: Optional[float] = None
    trailing_drop_percent: Optional[float] = None
    stable_band_percent: Optional[float] = None
    minimum_wait_minutes: Optional[int] = None
    consecutive_drop_checks: Optional[int] = None
    activation_price: Optional[float] = None
    protected_price: Optional[float] = None
    average_buy_price: Optional[float] = None
    partial_legs: Optional[Any] = None
    executed_legs: Optional[Any] = None
    expiry_time: Optional[datetime] = None
    expiry_action: Optional[str] = None
    max_allowed_slippage_percent: Optional[float] = None
    emergency_execution: Optional[bool] = False
    user_allocation: Optional[Any] = None

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
