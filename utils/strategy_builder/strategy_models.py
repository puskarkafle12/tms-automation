from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field


class LiteralNode(BaseModel):
    type: Literal["literal"] = "literal"
    value: Union[str, int, float, bool, None]


class FieldNode(BaseModel):
    type: Literal["field"] = "field"
    name: str


class ArithmeticNode(BaseModel):
    type: Literal["arithmetic"] = "arithmetic"
    operator: Literal["+", "-", "*", "/"]
    left: "RuleExpression"
    right: "RuleExpression"


class ComparisonNode(BaseModel):
    type: Literal["comparison"] = "comparison"
    left: "RuleExpression"
    operator: str
    right: "RuleExpression"


class GroupNode(BaseModel):
    type: Literal["group"] = "group"
    logic: Literal["AND", "OR"]
    children: List["RuleExpression"]


class NotNode(BaseModel):
    type: Literal["not"] = "not"
    child: "RuleExpression"


class FunctionNode(BaseModel):
    type: Literal["function"] = "function"
    name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


class ListNode(BaseModel):
    type: Literal["list"] = "list"
    values: List["RuleExpression"]


class AvailabilityCheckNode(BaseModel):
    type: Literal["availability_check"] = "availability_check"
    field: Optional[str] = None
    expression: Optional[Dict[str, Any]] = None
    check: str


RuleExpression = Union[
    LiteralNode,
    FieldNode,
    ArithmeticNode,
    ComparisonNode,
    GroupNode,
    NotNode,
    FunctionNode,
    ListNode,
    AvailabilityCheckNode,
]

ArithmeticNode.model_rebuild()
ComparisonNode.model_rebuild()
GroupNode.model_rebuild()
NotNode.model_rebuild()
ListNode.model_rebuild()


class OrderSizing(BaseModel):
    mode: str
    value: Optional[float] = None
    price_source: Optional[str] = "ltp"
    explicit: bool = True


class ConfirmationConfig(BaseModel):
    mode: str = "immediate"
    scans: Optional[int] = None
    required: Optional[int] = None
    window: Optional[int] = None
    wait_seconds: Optional[int] = None


class ExecutionConfig(BaseModel):
    trigger: str = "on_cross"
    frequency: str = "once_per_symbol"
    max_times: Optional[int] = None
    cooldown_minutes: Optional[int] = None
    max_slippage_pct: Optional[float] = None
    max_data_age_seconds: Optional[int] = None
    missing_market_depth: str = "wait"
    missing_holding: str = "warn_and_skip"


class RuleBlock(BaseModel):
    rule_id: str
    name: str
    symbols: List[str]
    target_type: str = "single"
    when: Optional[RuleExpression] = None
    eligibility: Optional[RuleExpression] = None
    signal: Optional[RuleExpression] = None
    require: Optional[RuleExpression] = None
    score_items: List[Dict[str, Any]] = Field(default_factory=list)
    required_score: Optional[float] = None
    order: OrderSizing
    confirmation: ConfirmationConfig = Field(default_factory=ConfirmationConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    priority: int = 0
    conflict_policy: str = "HIGHEST_PRIORITY_ONLY"
    stop_loss_price: Optional[float] = None
    use_strategy: Optional[str] = None
    strategy_params: Dict[str, Any] = Field(default_factory=dict)


class PositionExitAction(BaseModel):
    action: str
    order_mode: Optional[str] = None
    order_value: Optional[float] = None
    when: Optional[RuleExpression] = None
    lock_profit_pct: Optional[float] = None


class PortfolioLimits(BaseModel):
    max_matching_stocks: Optional[int] = None
    max_total_buy_amount: Optional[float] = None
    max_amount_per_stock: Optional[float] = None
    max_position_pct: Optional[float] = None
    max_open_orders: Optional[int] = None
    max_single_stock_exposure_pct: Optional[float] = None
    max_total_position_exposure_pct: Optional[float] = None
    max_daily_buy_amount: Optional[float] = None
    max_daily_loss_pct: Optional[float] = None
    max_daily_orders: Optional[int] = None
    max_open_strategies: Optional[int] = None
    pause_new_buys_when_daily_loss_pct: Optional[float] = None


class RankConfig(BaseModel):
    fields: List[Dict[str, str]] = Field(default_factory=list)
    limit: Optional[int] = None


class StrategyPlanAST(BaseModel):
    version: int = 1
    side: Literal["BUY", "SELL"]
    defaults: ExecutionConfig = Field(default_factory=ExecutionConfig)
    portfolio_limits: Optional[PortfolioLimits] = None
    position_protection: Optional["PositionProtectionConfig"] = None
    position_exit: List[PositionExitAction] = Field(default_factory=list)
    rank: Optional[RankConfig] = None
    rules: List[RuleBlock] = Field(default_factory=list)
    current_state: Optional[str] = None


class PositionProtectionConfig(BaseModel):
    fixed_stop_loss_price: Optional[float] = None
    trailing_stop_pct: Optional[float] = None


class ValidationIssue(BaseModel):
    code: str
    message: str
    symbol: Optional[str] = None
    line: Optional[int] = None
    column: Optional[int] = None


class TargetPreview(BaseModel):
    symbol: str
    rule_name: str
    eligible: bool = True
    status: str = "MONITORING"
    matched: bool = False
    proposed_order: Optional[str] = None
    holding_qty: Optional[int] = None


class ValidationResult(BaseModel):
    valid: bool
    status: str = "ok"
    message: Optional[str] = None
    missing_items: List[str] = Field(default_factory=list)
    errors: List[ValidationIssue] = Field(default_factory=list)
    warnings: List[ValidationIssue] = Field(default_factory=list)
    suggestions: List[ValidationIssue] = Field(default_factory=list)
    compiled_plan: Optional[StrategyPlanAST] = None
    targets: List[TargetPreview] = Field(default_factory=list)


class ConditionResult(BaseModel):
    expression: str
    matched: bool
    actual_value: Optional[Any] = None
    expected_value: Optional[Any] = None
    values: Optional[List[Any]] = None
    message: Optional[str] = None


class EvaluationResult(BaseModel):
    symbol: str
    rule_name: str
    matched: bool
    status: str
    conditions: List[ConditionResult] = Field(default_factory=list)
    final_result: bool = False
    proposed_quantity: Optional[int] = None
    proposed_amount: Optional[float] = None
    score_breakdown: List[Dict[str, Any]] = Field(default_factory=list)
    final_score: Optional[float] = None
