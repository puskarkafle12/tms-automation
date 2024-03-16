from sqlalchemy import Column, Integer, String, JSON, DateTime, func, event
from database import Base, get_db
from models.order_status_log import OrderStatusLog

class Order(Base):
    __tablename__ = 'orders'

    order_id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(String)
    security_details = Column(JSON)
    price = Column(Integer)
    qty = Column(Integer)
    status = Column(String)
    last_updated = Column(DateTime, default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<Order(order_id='{self.order_id}', client_id='{self.client_id}', security_details={self.security_details}, price={self.price}, status='{self.status}', last_updated='{self.last_updated}, qty={self.qty})>"
    def __init__(self, client_id, security_details, price, qty, status):
        self.client_id = client_id
        self.security_details = security_details
        self.price = price
        self.qty = qty
        self.status = status
@event.listens_for(Order, 'before_delete')
def before_delete_order(mapper, connection, target):
    db = get_db()
    log_entry = OrderStatusLog(order_id=target.order_id, client_id=target.client_id, security_details=target.security_details, qty=target.qty, status=target.status)
    db.add(log_entry)
    db.commit()
