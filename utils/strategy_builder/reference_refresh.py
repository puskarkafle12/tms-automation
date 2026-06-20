from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from models.scheduled_field_reference import ScheduledFieldReference, ScheduledFieldReferenceAudit
from models.scheduled_order import ScheduledOrder
from utils.strategy_builder.reference_capture import ReferenceCaptureError, _field_type_for_key, _source_label, _typed_row_value
from utils.strategy_builder.reference_store import load_reference_store
from utils.strategy_builder.strategy_models import StrategyPlanAST


class ReferenceRefreshError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


async def refresh_field_references(
    db: Session,
    order_id: int,
    *,
    scope: str = "all",
    rule_name: Optional[str] = None,
    symbol: Optional[str] = None,
    fields: Optional[List[str]] = None,
    refreshed_by: Optional[str] = None,
) -> Dict[str, Any]:
    order = db.query(ScheduledOrder).filter(ScheduledOrder.order_id == order_id).first()
    if not order:
        raise ReferenceRefreshError("ORDER_NOT_FOUND", f"Scheduled order {order_id} was not found.")

    strategy_config = dict(order.strategy_config or {})
    compiled = strategy_config.get("compiled_plan")
    if not compiled:
        raise ReferenceRefreshError("MISSING_PLAN", "Order has no compiled plan.")
    plan = StrategyPlanAST.model_validate(compiled)

    existing = (
        db.query(ScheduledFieldReference)
        .filter(ScheduledFieldReference.scheduled_order_id == order_id)
        .all()
    )
    if not existing:
        raise ReferenceRefreshError("NO_REFERENCES", "Order has no stored field references.")

    selected = existing
    if scope != "all":
        requested_fields = {str(item).strip() for item in (fields or []) if str(item).strip()}
        selected = [
            row
            for row in existing
            if (not rule_name or row.rule_name == rule_name)
            and (not symbol or row.symbol.upper() == symbol.strip().upper())
            and (not requested_fields or row.field_key in requested_fields)
        ]
    if not selected:
        raise ReferenceRefreshError("NO_MATCHING_REFERENCES", "No matching reference rows to refresh.")

    from utils.tms_client_resolver import get_tms_user_for_client
    from utils.strategy_builder.reference_capture import _fetch_symbol_flat

    tms_user = await get_tms_user_for_client(order.client_id, db)
    flat_cache: Dict[str, dict] = {}
    refreshed_at = datetime.now(timezone.utc)

    for model in selected:
        target_symbol = model.symbol.upper()
        if target_symbol not in flat_cache:
            try:
                flat_cache[target_symbol] = await _fetch_symbol_flat(tms_user, target_symbol)
            except ReferenceCaptureError as exc:
                raise ReferenceRefreshError(exc.code, str(exc)) from exc
        flat = flat_cache[target_symbol]
        raw_value = flat.get(model.field_key)
        if raw_value in (None, ""):
            raise ReferenceRefreshError(
                "REFERENCE_VALUE_REQUIRED",
                f"Cannot refresh {model.field_key} for {target_symbol}.",
            )
        try:
            field_type, numeric_value, text_value, boolean_value = _typed_row_value(model.field_key, raw_value)
        except ReferenceCaptureError as exc:
            raise ReferenceRefreshError(exc.code, str(exc)) from exc
        source = _source_label(model.field_key)

        audit = ScheduledFieldReferenceAudit(
            reference_id=model.id,
            previous_numeric=model.numeric_value,
            previous_text=model.text_value,
            previous_boolean=model.boolean_value,
            new_numeric=numeric_value,
            new_text=text_value,
            new_boolean=boolean_value,
            refreshed_at=refreshed_at,
            refreshed_by=refreshed_by,
        )
        db.add(audit)

        model.field_type = field_type
        model.numeric_value = numeric_value
        model.text_value = text_value
        model.boolean_value = boolean_value
        model.source = source
        model.refreshed_at = refreshed_at
        model.refresh_count = int(model.refresh_count or 0) + 1

    db.flush()
    updated_config = dict(order.strategy_config or {})
    updated_config["field_reference_rows"] = [
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
        for row in db.query(ScheduledFieldReference)
        .filter(ScheduledFieldReference.scheduled_order_id == order_id)
        .all()
    ]
    order.strategy_config = updated_config

    return {
        "order_id": order_id,
        "refreshed_count": len(selected),
        "refreshed_at": refreshed_at.isoformat(),
        "references": load_reference_store(db, order_id).summary(),
        "plan_side": plan.side,
    }
