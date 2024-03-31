from sqlalchemy import Column, Float, Integer, String, JSON, DateTime, func, event
from database import Base, get_db
from models.order_status_log import OrderStatusLog
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

@event.listens_for(ScheduledOrder, 'after_delete')
def after_delete_order(mapper, connection, target):
    with get_db() as db:
        log_entry = OrderStatusLog(order_id=target.order_id, client_id=target.client_id, security_details=target.security_details, script_name=target.script_name, qty=target.qty, status=target.status,price=target.price,order_type=target.order_type)
        db.add(log_entry)
        db.commit()