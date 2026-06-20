from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from schemas.schemas import OrderCreateRequest
from utils.strategy_builder.strategy_models import StrategyPlanAST

logger = logging.getLogger(__name__)

PREVIEW_CAPTURE_RETRY_ATTEMPTS = 3
PREVIEW_CAPTURE_RETRY_DELAY_SECONDS = 0.6
BATCH_PREVIEW_CONCURRENCY = 2


def _find_rule_for_symbol(plan: StrategyPlanAST, symbol: str):
    normalized = symbol.strip().upper()
    for rule in plan.rules:
        if normalized in {item.strip().upper() for item in rule.symbols}:
            return rule
    return plan.rules[0] if plan.rules else None


def snapshot_from_preview_row(row: Dict[str, Any]) -> Dict[str, Any]:
    trigger = row.get("trigger") or {}
    quantity = row.get("quantity") or {}
    confirmation = row.get("confirmation") or {}
    execution_price = row.get("execution_price") or {}
    estimated_price = trigger.get("estimated_price")
    estimated_quantity = quantity.get("estimated_quantity")
    trigger_kind = str(trigger.get("kind") or "")
    try:
        estimated_quantity_int = int(estimated_quantity) if estimated_quantity is not None else None
    except (TypeError, ValueError):
        estimated_quantity_int = None
    price_display = trigger.get("estimated_price_display")
    if trigger_kind == "non_price_condition":
        price_display = str(trigger.get("strategy_text") or "Signal-based")
    return {
        "estimated_trigger_price": estimated_price,
        "estimated_trigger_price_display": price_display,
        "trigger_kind": trigger_kind or None,
        "is_exact_trigger_price": bool(trigger.get("is_exact_price")),
        "trigger_strategy_text": trigger.get("strategy_text"),
        "current_required_display": _current_required_display(trigger),
        "quantity_description": quantity.get("description"),
        "estimated_quantity": estimated_quantity_int,
        "estimated_quantity_display": quantity.get("estimated_quantity_display"),
        "confirmation_display": confirmation.get("display"),
        "live_ltp_display": row.get("preview_ltp"),
        "reference_ltp_display": row.get("reference_ltp"),
        "execution_price_description": execution_price.get("description"),
        "reason": row.get("reason"),
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }


def snapshots_from_preview_rows(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    snapshots: Dict[str, Dict[str, Any]] = {}
    for row in rows or []:
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol or row.get("status") == "MISSING_DATA":
            continue
        snapshots[symbol] = snapshot_from_preview_row(row)
    return snapshots


def _current_required_display(trigger: Dict[str, Any]) -> Optional[str]:
    current = trigger.get("current_display")
    target = trigger.get("target_display")
    if current and target:
        return f"{current} / {target}"
    return None


def _snapshot_missing_trigger(snapshot: Dict[str, Any]) -> bool:
    if str(snapshot.get("trigger_kind") or "") == "non_price_condition":
        return False
    estimated = snapshot.get("estimated_trigger_price")
    if estimated is not None:
        try:
            if float(estimated) > 0:
                return False
        except (TypeError, ValueError):
            pass
    display = str(snapshot.get("estimated_trigger_price_display") or "").strip()
    return display in {"", "—", "Unavailable"}


def snapshots_complete_for_symbols(
    snapshots: Dict[str, Dict[str, Any]],
    symbols: List[str],
) -> bool:
    for symbol in symbols:
        normalized = str(symbol).strip().upper()
        snapshot = snapshots.get(normalized)
        if not isinstance(snapshot, dict) or _snapshot_missing_trigger(snapshot):
            return False
    return True


async def _resolve_schedule_preview_holdings(
    order_data: OrderCreateRequest,
    db: Session,
    plan: StrategyPlanAST,
    *,
    holdings_by_symbol: Optional[Dict[str, int]] = None,
    holding_retrieval_failed: bool = False,
) -> tuple[Dict[str, int], bool]:
    resolved = {
        str(symbol).strip().upper(): int(value or 0)
        for symbol, value in (holdings_by_symbol or {}).items()
    }
    failed = holding_retrieval_failed
    if str(plan.side or order_data.order_type or "").upper() == "SELL" and order_data.client_id and db is not None and not resolved:
        try:
            from utils.strategy_builder.holdings_preflight import build_holdings_map
            from utils.tms_client_resolver import get_tms_user_for_client

            tms_user = await get_tms_user_for_client(order_data.client_id, db)
            resolved = await build_holdings_map(tms_user)
        except Exception:
            failed = True
    return resolved, failed


def _apply_snapshot_to_order(order, snapshot: Dict[str, Any]) -> None:
    config = dict(order.strategy_config or {})
    config["schedule_preview_snapshot"] = snapshot
    order.strategy_config = config

    estimated = snapshot.get("estimated_trigger_price")
    if estimated is not None and getattr(order, "trigger_price", None) in (None, 0):
        order.trigger_price = float(estimated)

    estimated_qty = snapshot.get("estimated_quantity")
    try:
        qty_value = int(estimated_qty) if estimated_qty is not None else 0
    except (TypeError, ValueError):
        qty_value = 0
    if qty_value > 0:
        order.qty = qty_value
        if getattr(order, "remaining_quantity", None) in (None, 0):
            order.remaining_quantity = qty_value


def _precomputed_snapshot_for_symbol(
    order_data: OrderCreateRequest,
    symbol: str,
    *,
    batch_snapshots: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    normalized = symbol.strip().upper()
    if batch_snapshots and normalized in batch_snapshots:
        snapshot = batch_snapshots[normalized]
        if not _snapshot_missing_trigger(snapshot):
            return snapshot
    config = dict(order_data.strategy_config or {})
    stored = (config.get("schedule_preview_snapshots_by_symbol") or {}).get(normalized)
    if isinstance(stored, dict) and not _snapshot_missing_trigger(stored):
        return stored
    return None


async def capture_schedule_preview_snapshot(
    order_data: OrderCreateRequest,
    db: Session,
    *,
    holdings_by_symbol: Optional[Dict[str, int]] = None,
    holding_retrieval_failed: bool = False,
    max_attempts: int = PREVIEW_CAPTURE_RETRY_ATTEMPTS,
) -> Optional[Dict[str, Any]]:
    from utils.strategies.aliases import canonical_strategy_name
    from utils.strategy_builder.preview_service import _preview_symbol

    side = str(order_data.order_type or order_data.side or "buy").lower()
    canonical = canonical_strategy_name(order_data.strategy_type or "Fixed Price", side)
    if canonical not in {"Custom Query Buy", "Custom Query Sell"}:
        return None

    config = dict(order_data.strategy_config or {})
    compiled = config.get("compiled_plan")
    if not compiled:
        return None

    try:
        plan = StrategyPlanAST.model_validate(compiled)
    except Exception:
        return None

    symbol = str(order_data.script_name or "").strip().upper()
    if not symbol:
        return None

    rule = _find_rule_for_symbol(plan, symbol)
    if rule is None:
        return None

    resolved_holdings, holdings_failed = await _resolve_schedule_preview_holdings(
        order_data,
        db,
        plan,
        holdings_by_symbol=holdings_by_symbol,
        holding_retrieval_failed=holding_retrieval_failed,
    )

    last_snapshot: Optional[Dict[str, Any]] = None
    for attempt in range(max(1, max_attempts)):
        force_refresh = attempt > 0
        row = await _preview_symbol(
            rule,
            symbol,
            plan=plan,
            plan_side=str(plan.side or side).upper(),
            client_id=order_data.client_id,
            db=db,
            holdings_by_symbol=resolved_holdings,
            holding_retrieval_failed=holdings_failed,
            force_refresh=force_refresh,
        )
        if not row or row.get("status") == "MISSING_DATA":
            if attempt < max_attempts - 1:
                await asyncio.sleep(PREVIEW_CAPTURE_RETRY_DELAY_SECONDS * (attempt + 1))
                continue
            return last_snapshot
        snapshot = snapshot_from_preview_row(row)
        last_snapshot = snapshot
        if not _snapshot_missing_trigger(snapshot) or attempt >= max_attempts - 1:
            return snapshot
        await asyncio.sleep(PREVIEW_CAPTURE_RETRY_DELAY_SECONDS * (attempt + 1))
    return last_snapshot


async def capture_batch_preview_snapshots(
    order_data: OrderCreateRequest,
    db: Session,
    symbols: List[str],
    *,
    holdings_by_symbol: Optional[Dict[str, int]] = None,
    holding_retrieval_failed: bool = False,
) -> Dict[str, Dict[str, Any]]:
    config = dict(order_data.strategy_config or {})
    compiled = config.get("compiled_plan")
    if not compiled:
        return {}
    try:
        plan = StrategyPlanAST.model_validate(compiled)
    except Exception:
        return {}

    precomputed = dict(config.get("schedule_preview_snapshots_by_symbol") or {})
    snapshots = {
        symbol: snapshot
        for symbol, snapshot in precomputed.items()
        if isinstance(snapshot, dict) and not _snapshot_missing_trigger(snapshot)
    }
    missing_symbols = [
        str(symbol).strip().upper()
        for symbol in symbols
        if str(symbol).strip().upper() not in snapshots
    ]
    if not missing_symbols:
        return snapshots

    semaphore = asyncio.Semaphore(BATCH_PREVIEW_CONCURRENCY)

    async def _capture_one(symbol: str) -> tuple[str, Optional[Dict[str, Any]]]:
        async with semaphore:
            request = order_data.model_copy(update={"script_name": symbol})
            captured = await capture_schedule_preview_snapshot(
                request,
                db,
                holdings_by_symbol=holdings_by_symbol,
                holding_retrieval_failed=holding_retrieval_failed,
            )
            return symbol, captured

    results = await asyncio.gather(*[_capture_one(symbol) for symbol in missing_symbols])
    for symbol, captured in results:
        if captured:
            snapshots[symbol] = captured
        elif symbol in precomputed and isinstance(precomputed[symbol], dict):
            snapshots[symbol] = precomputed[symbol]
    return snapshots


async def apply_schedule_preview_snapshot(
    order,
    order_data: OrderCreateRequest,
    db: Session,
    *,
    holdings_by_symbol: Optional[Dict[str, int]] = None,
    holding_retrieval_failed: bool = False,
    batch_snapshots: Optional[Dict[str, Dict[str, Any]]] = None,
) -> None:
    symbol = str(order_data.script_name or "").strip().upper()
    precomputed = _precomputed_snapshot_for_symbol(
        order_data,
        symbol,
        batch_snapshots=batch_snapshots,
    )
    if precomputed:
        _apply_snapshot_to_order(order, precomputed)
        return

    snapshot = await capture_schedule_preview_snapshot(
        order_data,
        db,
        holdings_by_symbol=holdings_by_symbol,
        holding_retrieval_failed=holding_retrieval_failed,
    )
    if not snapshot:
        return

    _apply_snapshot_to_order(order, snapshot)
