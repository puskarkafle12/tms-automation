# schemas.py

from pydantic import BaseModel
from typing import Dict

class OrderCreateRequest(BaseModel):
    client_id: str
    security_details: Dict
    price: int
    qty: int
    status: str = "pending"
