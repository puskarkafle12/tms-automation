# models/order_log.py

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float, Text, Index
from datetime import datetime, timezone
from database import Base

class OrderLog(Base):
    __tablename__ = 'order_logs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(String, nullable=False)
    script_name = Column(String, nullable=False)
    scanning_count = Column(Integer, default=0)
    current_price = Column(Float, nullable=True)
    order_placed = Column(Boolean, default=False)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    logs = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_order_logs_client_script", "client_id", "script_name"),
    )
