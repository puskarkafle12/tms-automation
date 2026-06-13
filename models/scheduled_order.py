from sqlalchemy import Column, Float, Integer, String, JSON, DateTime, func, Index
from database import Base
from schemas.schemas import OrderCreateRequest

class ScheduledOrder(Base):
    __tablename__ = 'scheduled_orders'

    order_id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(String)
    security_details = Column(JSON)
    script_name = Column(String)
    price = Column(Float)
    qty = Column(Integer)
    status = Column(String)
    order_type = Column(String)
    last_updated = Column(DateTime, default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_scheduled_orders_status_client_script", "status", "client_id", "script_name"),
    )

    def __repr__(self):
        return f"<Order(order_id='{self.order_id}', client_id='{self.client_id}', security_details={self.security_details}, price={self.price}, status='{self.status}', last_updated='{self.last_updated}', qty={self.qty})>"

    def __init__(self, order_data: OrderCreateRequest):
        self.client_id = order_data.client_id
        self.security_details = order_data.security_details
        self.script_name = order_data.script_name
        self.price = order_data.price
        self.qty = order_data.qty
        self.order_type = order_data.order_type
        self.status = order_data.status
