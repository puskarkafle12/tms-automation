# schemas.py

from pydantic import BaseModel
from typing import Dict
class OrderCreateRequest(BaseModel):
    client_id: str
    security_details: Dict={}
    script_name:str
    price: int
    qty: int
    status: str = "pending"

class LoginRequest(BaseModel):
    username: str
    password: str
    stock_symbol: str
    broker_no: str
    request_per_sec: int