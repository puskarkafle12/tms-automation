from sqlalchemy import JSON, Column, Integer, String, DateTime, func
from database import Base

class OrderStatusLog(Base):
    __tablename__ = 'order_status_logs'

    log_id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(String)
    security_details = Column(JSON)
    order_id = Column(Integer)
    qty = Column(Integer)
    status = Column(String)
    timestamp = Column(DateTime, default=func.now())

    def __repr__(self):
        return f"<Order(order_id='{self.order_id}', client_id='{self.client_id}', security_details={self.security_details}, price={self.price}, status='{self.status}', last_updated='{self.last_updated}, qty {self.qty}')>"
        
    def __init__(self, client_id, security_details, order_id, qty, status):
        self.client_id = client_id
        self.security_details = security_details
        self.order_id = order_id
        self.qty = qty
        self.status = status