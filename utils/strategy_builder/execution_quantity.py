from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from utils.lot_size import get_board_lot_size, normalize_sell_qty
from utils.strategy_builder.execution_sizing import resolve_order_quantity

HOLDING_DEPENDENT_MODES = frozenset({"percent_of_holding", "all_available", "sell_up_to"})


def is_holding_dependent_mode(mode: Optional[str]) -> bool:
    return str(mode or "").lower() in HOLDING_DEPENDENT_MODES


@dataclass
class QuantityResolution:
    mode: str
    configured_value: Optional[float]
    available_holding: Optional[int]
    final_quantity: int
    source: str
    error: Optional[str] = None
    retryable: bool = False


def extract_order_action_from_plan(
    compiled_plan: Optional[Dict[str, Any]],
    symbol: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    if not isinstance(compiled_plan, dict):
        return None
    normalized_symbol = (symbol or "").strip().upper()
    for rule in compiled_plan.get("rules") or []:
        rule_symbols = [
            str(item).strip().upper()
            for item in (rule.get("symbols") or [])
            if str(item).strip()
        ]
        if normalized_symbol and rule_symbols and normalized_symbol not in rule_symbols:
            continue
        order = rule.get("order") or {}
        mode = str(order.get("mode") or "").lower()
        if not mode:
            continue
        return {
            "mode": mode,
            "value": order.get("value"),
            "rule_name": rule.get("name"),
        }
    return None


def plan_uses_holding_dependent_quantity(compiled_plan: Optional[Dict[str, Any]]) -> bool:
    action = extract_order_action_from_plan(compiled_plan)
    return bool(action and is_holding_dependent_mode(action.get("mode")))


async def fetch_symbol_holding_qty(tms_user, symbol: str) -> int:
    from utils.strategy_builder.holdings_preflight import build_holdings_map

    holdings = await build_holdings_map(tms_user)
    normalized = symbol.strip().upper()
    return int(holdings.get(normalized, 0) or 0)


def _audit_payload(resolution: QuantityResolution) -> Dict[str, Any]:
    return {
        "quantity_mode": resolution.mode,
        "configured_quantity_value": resolution.configured_value,
        "execution_available_holding": resolution.available_holding,
        "resolved_execution_quantity": resolution.final_quantity,
        "quantity_resolved_at": datetime.now(timezone.utc).isoformat(),
        "quantity_source": resolution.source,
    }


def apply_quantity_resolution_audit(strategy_config: Optional[Dict[str, Any]], resolution: QuantityResolution) -> Dict[str, Any]:
    payload = dict(strategy_config or {})
    payload["execution_quantity_audit"] = _audit_payload(resolution)
    return payload


async def resolve_execution_quantity(
    *,
    scheduled_order,
    matched_order_action: Dict[str, Any],
    tms_user,
    symbol: str,
    side: str,
    security_details: Optional[dict] = None,
) -> QuantityResolution:
    mode = str(matched_order_action.get("mode") or "quantity").lower()
    configured_value = matched_order_action.get("value")
    client_id = str(getattr(scheduled_order, "client_id", "") or "")
    normalized_symbol = symbol.strip().upper()

    if side.lower() == "buy" and is_holding_dependent_mode(mode):
        return QuantityResolution(
            mode=mode,
            configured_value=configured_value,
            available_holding=None,
            final_quantity=0,
            source="validation",
            error="Holding-based quantity modes are not valid for BUY orders.",
        )

    merged_security = {
        **(getattr(scheduled_order, "security_details", None) or {}),
        **(security_details or {}),
    }
    odd_lot_allowed = bool(merged_security.get("odd_lot_allowed") or merged_security.get("oddLotAllowed"))
    lot_size = get_board_lot_size(merged_security)

    if not is_holding_dependent_mode(mode):
        if mode == "quantity" and configured_value == -1:
            final_qty = int(getattr(scheduled_order, "qty", 0) or 0)
        else:
            final_qty = resolve_order_quantity(
                order_mode=mode,
                order_value=configured_value,
                ltp=None,
                holding_qty=0,
                board_lot=lot_size,
                form_qty=int(getattr(scheduled_order, "qty", 0) or 0),
            )
        if final_qty <= 0:
            final_qty = int(getattr(scheduled_order, "remaining_quantity", 0) or getattr(scheduled_order, "qty", 0) or 0)
        if side.lower() == "sell" and final_qty > 0:
            try:
                available = await fetch_symbol_holding_qty(tms_user, normalized_symbol)
            except Exception:
                return QuantityResolution(
                    mode=mode,
                    configured_value=configured_value,
                    available_holding=None,
                    final_quantity=0,
                    source="live_dp_holding",
                    error=(
                        f"Unable to resolve execution quantity: current DP holding could not be retrieved "
                        f"for {normalized_symbol} under client {client_id}."
                    ),
                    retryable=True,
                )
            if available <= 0:
                return QuantityResolution(
                    mode=mode,
                    configured_value=configured_value,
                    available_holding=0,
                    final_quantity=0,
                    source="live_dp_holding",
                    error=f"No sellable DP holding for {normalized_symbol}.",
                )
            if final_qty > available:
                return QuantityResolution(
                    mode=mode,
                    configured_value=configured_value,
                    available_holding=available,
                    final_quantity=0,
                    source="live_dp_holding",
                    error=(
                        f"Sell quantity {final_qty} exceeds latest holding {available} for {normalized_symbol}."
                    ),
                )
            if not odd_lot_allowed:
                normalized = normalize_sell_qty(final_qty, available, lot_size)
                if normalized.get("qty", 0) <= 0 and not normalized.get("is_sell_all"):
                    return QuantityResolution(
                        mode=mode,
                        configured_value=configured_value,
                        available_holding=available,
                        final_quantity=0,
                        source="live_dp_holding",
                        error=normalized.get("error") or "Execution blocked by board-lot rule.",
                    )
                final_qty = int(normalized.get("qty") or final_qty)
        return QuantityResolution(
            mode=mode,
            configured_value=configured_value,
            available_holding=None,
            final_quantity=max(0, final_qty),
            source="configured_quantity",
        )

    try:
        available = await fetch_symbol_holding_qty(tms_user, normalized_symbol)
    except Exception:
        return QuantityResolution(
            mode=mode,
            configured_value=configured_value,
            available_holding=None,
            final_quantity=0,
            source="live_dp_holding",
            error=(
                f"Unable to resolve execution quantity: current DP holding could not be retrieved "
                f"for {normalized_symbol} under client {client_id}."
            ),
            retryable=True,
        )

    if available <= 0:
        return QuantityResolution(
            mode=mode,
            configured_value=configured_value,
            available_holding=0,
            final_quantity=0,
            source="live_dp_holding",
            error=f"No sellable DP holding for {normalized_symbol}.",
        )

    if mode == "percent_of_holding":
        pct = float(configured_value or 0)
        if pct <= 0:
            return QuantityResolution(
                mode=mode,
                configured_value=configured_value,
                available_holding=available,
                final_quantity=0,
                source="live_dp_holding",
                error="Percent of holding must be greater than zero.",
            )
        if pct > 100:
            return QuantityResolution(
                mode=mode,
                configured_value=configured_value,
                available_holding=available,
                final_quantity=0,
                source="live_dp_holding",
                error="Percent of holding cannot exceed 100.",
            )

    raw_qty = resolve_order_quantity(
        order_mode=mode,
        order_value=configured_value,
        ltp=None,
        holding_qty=available,
        board_lot=lot_size,
        form_qty=int(getattr(scheduled_order, "qty", 0) or 0),
    )
    raw_qty = min(int(raw_qty), available)

    final_qty = raw_qty
    if side.lower() == "sell" and not odd_lot_allowed:
        normalized = normalize_sell_qty(raw_qty, available, lot_size)
        if normalized.get("is_sell_all"):
            final_qty = int(normalized.get("qty") or available)
        elif int(normalized.get("qty") or 0) <= 0:
            return QuantityResolution(
                mode=mode,
                configured_value=configured_value,
                available_holding=available,
                final_quantity=0,
                source="live_dp_holding",
                error=normalized.get("error") or "Execution blocked by board-lot rule.",
            )
        else:
            final_qty = int(normalized["qty"])

    final_qty = min(final_qty, available)
    if final_qty <= 0:
        return QuantityResolution(
            mode=mode,
            configured_value=configured_value,
            available_holding=available,
            final_quantity=0,
            source="live_dp_holding",
            error=f"Resolved sell quantity is zero for {normalized_symbol}.",
        )

    return QuantityResolution(
        mode=mode,
        configured_value=configured_value,
        available_holding=available,
        final_quantity=final_qty,
        source="live_dp_holding",
    )
