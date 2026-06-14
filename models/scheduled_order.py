from sqlalchemy import Boolean, Column, Float, Integer, String, JSON, DateTime, func, Index
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
    strategy_type = Column(String, default="Fixed Price")
    side = Column(String)
    symbol = Column(String)
    company_name = Column(String)
    remaining_quantity = Column(Integer)
    limit_price = Column(Float)
    stop_loss_price = Column(Float)
    stop_limit_price = Column(Float)
    book_profit_price = Column(Float)
    profit_target_price = Column(Float)
    trailing_drop_percent = Column(Float)
    stable_band_percent = Column(Float)
    minimum_wait_minutes = Column(Integer)
    consecutive_drop_checks = Column(Integer)
    activation_price = Column(Float)
    target_reached = Column(Boolean, default=False)
    target_reached_at = Column(DateTime)
    highest_tracked_price = Column(Float)
    highest_tracked_at = Column(DateTime)
    protected_price = Column(Float)
    average_buy_price = Column(Float)
    partial_legs = Column(JSON)
    executed_legs = Column(JSON)
    execution_price = Column(Float)
    execution_price_source = Column(String)
    execution_reason = Column(String)
    executed_at = Column(DateTime)
    cancelled_reason = Column(String)
    failed_reason = Column(String)
    expiry_time = Column(DateTime)
    expiry_action = Column(String)
    max_allowed_slippage_percent = Column(Float)
    emergency_execution = Column(Boolean, default=False)
    user_allocation = Column(JSON)
    last_checked_ltp = Column(Float)
    last_checked_at = Column(DateTime)
    below_stop_loss_check_count = Column(Integer, default=0)
    consecutive_drop_count = Column(Integer, default=0)
    runner_lock_id = Column(String)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
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
        self.strategy_type = order_data.strategy_type or "Fixed Price"
        self.side = order_data.side or order_data.order_type
        self.symbol = order_data.symbol or order_data.script_name
        self.company_name = order_data.company_name
        self.remaining_quantity = order_data.remaining_quantity or order_data.qty
        self.limit_price = order_data.limit_price
        self.stop_loss_price = order_data.stop_loss_price
        self.stop_limit_price = order_data.stop_limit_price
        self.book_profit_price = order_data.book_profit_price
        self.profit_target_price = order_data.profit_target_price
        self.trailing_drop_percent = order_data.trailing_drop_percent
        self.stable_band_percent = order_data.stable_band_percent
        self.minimum_wait_minutes = order_data.minimum_wait_minutes
        self.consecutive_drop_checks = order_data.consecutive_drop_checks
        self.activation_price = order_data.activation_price
        self.protected_price = order_data.protected_price
        self.average_buy_price = order_data.average_buy_price
        self.partial_legs = order_data.partial_legs
        self.executed_legs = order_data.executed_legs
        self.expiry_time = order_data.expiry_time
        self.expiry_action = order_data.expiry_action
        self.max_allowed_slippage_percent = order_data.max_allowed_slippage_percent
        self.emergency_execution = order_data.emergency_execution
        self.user_allocation = order_data.user_allocation
