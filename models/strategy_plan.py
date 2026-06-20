from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text, JSON, func, Index, UniqueConstraint
from database import Base


class StrategyPlan(Base):
    __tablename__ = "strategy_plans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, nullable=False)
    client_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    side = Column(String, nullable=False)
    strategy_type = Column(String, nullable=False)
    rule_source = Column(String, nullable=False, default="custom_query")
    query_text = Column(Text)
    query_version = Column(Integer, default=1)
    compiled_plan = Column(JSON)
    status = Column(String, default="draft")
    execution_mode = Column(String, default="paper")
    portfolio_limits = Column(JSON)
    form_symbol = Column(String)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    activated_at = Column(DateTime)


class StrategyRule(Base):
    __tablename__ = "strategy_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    plan_id = Column(Integer, nullable=False, index=True)
    rule_name = Column(String, nullable=False)
    priority = Column(Integer, default=0)
    rule_ast = Column(JSON)
    order_config = Column(JSON)
    confirmation_config = Column(JSON)
    execution_config = Column(JSON)
    risk_config = Column(JSON)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class StrategyTarget(Base):
    __tablename__ = "strategy_targets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    rule_id = Column(Integer, nullable=False, index=True)
    plan_id = Column(Integer, nullable=False, index=True)
    symbol = Column(String, nullable=False)
    status = Column(String, default="MONITORING")
    warning_codes = Column(JSON)
    last_evaluation_status = Column(String)
    last_match_at = Column(DateTime)
    execution_count = Column(Integer, default=0)
    cooldown_until = Column(DateTime)
    target_state = Column(JSON)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class RuleEvaluation(Base):
    __tablename__ = "rule_evaluations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    plan_id = Column(Integer, nullable=False, index=True)
    rule_id = Column(Integer)
    target_id = Column(Integer)
    symbol = Column(String, nullable=False)
    snapshot_id = Column(String)
    rule_version = Column(Integer, default=1)
    matched = Column(Boolean, default=False)
    status = Column(String)
    condition_results = Column(JSON)
    warning_codes = Column(JSON)
    evaluated_at = Column(DateTime, server_default=func.now())


class ExecutionBatch(Base):
    __tablename__ = "execution_batches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    plan_id = Column(Integer, nullable=False, index=True)
    evaluation_cycle_id = Column(String)
    side = Column(String)
    status = Column(String, default="PLANNED")
    total_candidates = Column(Integer, default=0)
    total_intents = Column(Integer, default=0)
    submitted_count = Column(Integer, default=0)
    skipped_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())
    completed_at = Column(DateTime)


class OrderIntent(Base):
    __tablename__ = "order_intents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    batch_id = Column(Integer, index=True)
    plan_id = Column(Integer, nullable=False, index=True)
    rule_id = Column(Integer)
    symbol = Column(String, nullable=False)
    side = Column(String, nullable=False)
    requested_quantity = Column(Integer)
    effective_quantity = Column(Integer)
    requested_amount = Column(Float)
    order_price = Column(Float)
    max_slippage_pct = Column(Float)
    idempotency_key = Column(String, nullable=False)
    status = Column(String, default="PENDING")
    broker_order_id = Column(String)
    request_payload = Column(JSON)
    response_payload = Column(JSON)
    created_at = Column(DateTime, server_default=func.now())
    submitted_at = Column(DateTime)
    confirmed_at = Column(DateTime)

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_order_intents_idempotency_key"),
    )


class StrategyWarning(Base):
    __tablename__ = "strategy_warnings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    plan_id = Column(Integer, nullable=False, index=True)
    rule_id = Column(Integer)
    symbol = Column(String)
    warning_code = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    is_acknowledged = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
