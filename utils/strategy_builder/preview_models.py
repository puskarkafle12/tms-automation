from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class PreviewWarning(BaseModel):
    code: str
    message: str
    severity: Literal["warning", "error", "info"] = "warning"


class ConditionPreview(BaseModel):
    strategy_text: str
    matched: Optional[bool] = None
    current_value: Optional[Any] = None
    target_value: Optional[Any] = None
    current_display: Optional[str] = None
    target_display: Optional[str] = None
    value_unit: Optional[str] = None
    estimated_price: Optional[float] = None
    estimated_price_available: bool = False
    is_exact_price: bool = False
    connector: Optional[str] = None


class TriggerPreview(BaseModel):
    kind: str = "condition"
    strategy_text: str
    estimated_price: Optional[float] = None
    estimated_price_display: Optional[str] = None
    estimated_price_available: bool = False
    is_exact_price: bool = False
    current_value: Optional[Any] = None
    target_value: Optional[Any] = None
    current_display: Optional[str] = None
    target_display: Optional[str] = None
    value_unit: Optional[str] = None
    operator: Optional[str] = None
    source_fields: Dict[str, Any] = Field(default_factory=dict)
    conditions: List[ConditionPreview] = Field(default_factory=list)
    logic: Optional[str] = None


class QuantityPreview(BaseModel):
    mode: str
    configured_value: Optional[float] = None
    current_holding: Optional[int] = None
    estimated_quantity: Optional[int] = None
    estimated_quantity_display: Optional[str] = None
    is_final: bool = False
    description: str
    note: Optional[str] = None
    warnings: List[PreviewWarning] = Field(default_factory=list)


class ConfirmationPreview(BaseModel):
    mode: str
    matched_scans: int = 0
    required_scans: int = 0
    display: str


class ExecutionPricePreview(BaseModel):
    mode: str
    description: str
    estimated_price: Optional[float] = None
    estimated_price_display: Optional[str] = None


class ExecutionPolicyPreview(BaseModel):
    trigger_mode: Optional[str] = None
    frequency: Optional[str] = None
    max_slippage_pct: Optional[float] = None
    display: Optional[str] = None


class RulePreview(BaseModel):
    symbol: str
    status: str
    status_label: str
    matched: bool
    live_ltp: Optional[float] = None
    live_ltp_display: Optional[str] = None
    reference_ltp: Optional[float] = None
    reference_ltp_display: Optional[str] = None
    trigger: TriggerPreview
    quantity: Optional[QuantityPreview] = None
    confirmation: Optional[ConfirmationPreview] = None
    execution_price: Optional[ExecutionPricePreview] = None
    execution_policy: Optional[ExecutionPolicyPreview] = None
    reason: Optional[str] = None
    warnings: List[PreviewWarning] = Field(default_factory=list)
    blocker: Optional[str] = None
    strategy: Optional[str] = None
    strategy_action: Optional[str] = None
    message: Optional[str] = None
    nepse_alpha_available: Optional[bool] = None

    def to_legacy_row(self) -> Dict[str, Any]:
        row: Dict[str, Any] = {
            "symbol": self.symbol,
            "rule": getattr(self, "rule_name", None),
            "matched": self.matched,
            "status": self.status,
            "status_label": self.status_label,
            "blocker": self.blocker,
            "reference_ltp": self.reference_ltp,
            "preview_ltp": self.live_ltp,
            "trigger_ltp": self.trigger.estimated_price if self.trigger.is_exact_price else None,
            "nepse_alpha_available": self.nepse_alpha_available,
            "message": self.message,
            "reason": self.reason,
            "trigger": self.trigger.model_dump(),
            "warnings": [item.model_dump() for item in self.warnings],
        }
        if self.quantity:
            row["quantity"] = self.quantity.model_dump()
        if self.confirmation:
            row["confirmation"] = self.confirmation.model_dump()
        if self.execution_price:
            row["execution_price"] = self.execution_price.model_dump()
        if self.execution_policy:
            row["execution_policy"] = self.execution_policy.model_dump()
        if self.strategy:
            row["strategy"] = self.strategy
        if self.strategy_action:
            row["strategy_action"] = self.strategy_action
        return row
