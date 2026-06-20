from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import relationship

from database import Base


class ScheduledFieldReference(Base):
    __tablename__ = "scheduled_field_references"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scheduled_order_id = Column(Integer, ForeignKey("scheduled_orders.order_id", ondelete="CASCADE"), nullable=False)
    rule_name = Column(String, nullable=False)
    symbol = Column(String, nullable=False)
    field_key = Column(String, nullable=False)
    field_type = Column(String, nullable=False)
    numeric_value = Column(Float)
    text_value = Column(String)
    boolean_value = Column(Boolean)
    captured_at = Column(DateTime, server_default=func.now())
    source = Column(String)
    refreshed_at = Column(DateTime)
    refresh_count = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    audits = relationship("ScheduledFieldReferenceAudit", back_populates="reference", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint(
            "scheduled_order_id",
            "rule_name",
            "symbol",
            "field_key",
            name="uq_scheduled_field_reference",
        ),
    )


class ScheduledFieldReferenceAudit(Base):
    __tablename__ = "scheduled_field_reference_audits"

    id = Column(Integer, primary_key=True, autoincrement=True)
    reference_id = Column(Integer, ForeignKey("scheduled_field_references.id", ondelete="CASCADE"), nullable=False)
    previous_numeric = Column(Float)
    previous_text = Column(String)
    previous_boolean = Column(Boolean)
    new_numeric = Column(Float)
    new_text = Column(String)
    new_boolean = Column(Boolean)
    refreshed_at = Column(DateTime, server_default=func.now())
    refreshed_by = Column(String)

    reference = relationship("ScheduledFieldReference", back_populates="audits")
