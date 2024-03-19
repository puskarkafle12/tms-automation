from sqlalchemy import JSON, Column, Integer, String, DateTime, func
from database import Base

class OrderStatusLog(Base):
    __tablename__ = 'order_status_logs'

    log_id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(String)
    security_details = Column(JSON)
    script_name=Column(String)
    order_id = Column(Integer)
    qty = Column(Integer)
    status = Column(String)
    timestamp = Column(DateTime, default=func.now())
    price = Column(Integer)

    def __repr__(self):
        return f"<Order(order_id='{self.order_id}', client_id='{self.client_id}', security_details={self.security_details}, price={self.price}, status='{self.status}', last_updated='{self.last_updated}, qty {self.qty}')>"
        
    def __init__(self, client_id, security_details,script_name, order_id, qty, status,price):
        self.client_id = client_id
        self.security_details = security_details
        self.script_name=script_name
        self.order_id = order_id
        self.qty = qty
        self.status = status
        self.price = price