from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from utils.strategy_builder.reference_capture import ReferenceCaptureError, capture_references_for_plan
from utils.strategy_builder.reference_dependencies import plan_uses_reference
from utils.strategy_builder.reference_store import ReferenceRow, persist_reference_rows
from utils.strategy_builder.strategy_models import StrategyPlanAST


def serialize_reference_rows(rows: List[ReferenceRow]) -> List[Dict[str, Any]]:
    return [
        {
            "rule_name": row.rule_name,
            "symbol": row.symbol,
            "field_key": row.field_key,
            "field_type": row.field_type,
            "numeric_value": row.numeric_value,
            "text_value": row.text_value,
            "boolean_value": row.boolean_value,
            "source": row.source,
            "captured_at": row.captured_at.isoformat() if row.captured_at else None,
        }
        for row in rows
    ]


async def capture_and_attach_field_references(
    *,
    db: Session,
    tms_user,
    order_id: int,
    symbol: str,
    plan: StrategyPlanAST,
    strategy_config: dict,
) -> dict:
    if not plan_uses_reference(plan):
        return strategy_config
    rows = await capture_references_for_plan(tms_user, symbol=symbol, plan=plan)
    persist_reference_rows(db, order_id, rows)
    updated = dict(strategy_config or {})
    updated["uses_field_references"] = True
    updated["field_reference_rows"] = serialize_reference_rows(rows)
    return updated


async def preview_field_references(*, tms_user, symbol: str, plan: StrategyPlanAST) -> Dict[str, Any]:
    from utils.strategy_builder.reference_capture import capture_references_preview

    if not plan_uses_reference(plan):
        return {}
    return await capture_references_preview(tms_user, symbol=symbol, plan=plan)
