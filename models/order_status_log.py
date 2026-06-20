from sqlalchemy import JSON, Column, Float, Integer, String, DateTime, func, Index
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
    deleted_at = Column(DateTime, nullable=True)
    price = Column(Float)
    order_type = Column(String)
    strategy_type = Column(String)
    requested_price = Column(Float)
    execution_price = Column(Float)
    execution_price_source = Column(String)
    execution_reason = Column(String)
    stop_loss_price = Column(Float)
    average_buy_price = Column(Float)
    max_allowed_slippage_percent = Column(Float)

    __table_args__ = (
        Index("ix_order_status_logs_timestamp_client_script", "timestamp", "client_id", "script_name"),
    )

    def __repr__(self):
        return f"<Order(order_id='{self.order_id}', client_id='{self.client_id}', security_details={self.security_details}, price={self.price}, status='{self.status}', last_updated='{self.last_updated}, qty {self.qty}')>"
        
    def __init__(
        self,
        client_id,
        security_details,
        script_name,
        order_id,
        qty,
        status,
        price,
        order_type,
        strategy_type=None,
        requested_price=None,
        execution_price=None,
        execution_price_source=None,
        execution_reason=None,
        stop_loss_price=None,
        average_buy_price=None,
        max_allowed_slippage_percent=None,
    ):
        self.client_id = client_id
        self.security_details = security_details
        self.script_name=script_name
        self.order_id = order_id
        self.qty = qty
        self.status = status
        self.price = price
        self.order_type = order_type
        self.strategy_type = strategy_type
        self.requested_price = requested_price
        self.execution_price = execution_price
        self.execution_price_source = execution_price_source
        self.execution_reason = execution_reason
        self.stop_loss_price = stop_loss_price
        self.average_buy_price = average_buy_price
        self.max_allowed_slippage_percent = max_allowed_slippage_percent
