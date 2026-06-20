from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from utils.strategies.aliases import canonical_strategy_name
from utils.strategies.types import OrderContext, ScannerMemory, StrategyConfig


def _config_from_dict(raw: Optional[Dict[str, Any]]) -> StrategyConfig:
    payload = raw or {}
    known_keys = {
        "min_buy_score", "require_fresh_trade", "require_volume_increase", "allow_market_depth_filter",
        "wrapped_strategy_type", "expiry_action", "stop_loss_pct", "defaultStopLossPct",
        "break_even_trigger_pct", "breakEvenTriggerPct", "target1_pct", "target1Pct",
        "target1_sell_pct", "target1SellPct", "target2_pct", "target2Pct", "target2_sell_pct",
        "target2SellPct", "trailing_stop_pct", "trailingStopPct", "max_capital_per_stock_pct",
        "order_timeout_minutes", "allow_split_emergency_exit", "sold_target1", "sold_target2",
        "break_even_armed", "extra",
    }
    extra = dict(payload.get("extra") or {})
    for key, value in payload.items():
        if key not in known_keys:
            extra[key] = value
    return StrategyConfig(
        min_buy_score=float(payload.get("min_buy_score") or 65.0),
        require_fresh_trade=bool(payload.get("require_fresh_trade")),
        require_volume_increase=bool(payload.get("require_volume_increase")),
        allow_market_depth_filter=bool(payload.get("allow_market_depth_filter", True)),
        wrapped_strategy_type=payload.get("wrapped_strategy_type"),
        expiry_action=payload.get("expiry_action"),
        stop_loss_pct=float(payload.get("stop_loss_pct") or payload.get("defaultStopLossPct") or 3.0),
        break_even_trigger_pct=float(payload.get("break_even_trigger_pct") or payload.get("breakEvenTriggerPct") or 3.0),
        target1_pct=float(payload.get("target1_pct") or payload.get("target1Pct") or 4.0),
        target1_sell_pct=float(payload.get("target1_sell_pct") or payload.get("target1SellPct") or 30.0),
        target2_pct=float(payload.get("target2_pct") or payload.get("target2Pct") or 8.0),
        target2_sell_pct=float(payload.get("target2_sell_pct") or payload.get("target2SellPct") or 30.0),
        trailing_stop_pct=float(payload.get("trailing_stop_pct") or payload.get("trailingStopPct") or 3.0),
        max_capital_per_stock_pct=float(payload.get("max_capital_per_stock_pct") or 10.0),
        order_timeout_minutes=int(payload.get("order_timeout_minutes") or 3),
        allow_split_emergency_exit=bool(payload.get("allow_split_emergency_exit")),
        sold_target1=bool(payload.get("sold_target1")),
        sold_target2=bool(payload.get("sold_target2")),
        break_even_armed=bool(payload.get("break_even_armed")),
        extra=extra,
    )


def build_order_context(db_order) -> OrderContext:
    side = (db_order.side or db_order.order_type or "buy").lower()
    raw_strategy = db_order.strategy_type or "Fixed Price"
    canonical = canonical_strategy_name(raw_strategy, side)
    config = _config_from_dict(getattr(db_order, "strategy_config", None))
    if getattr(db_order, "reference_ltp", None) and getattr(db_order, "trigger_price", None):
        baseline = dict(config.extra.get("schedule_baseline") or {})
        baseline.setdefault("reference_ltp", float(db_order.reference_ltp))
        baseline.setdefault("trigger_price", float(db_order.trigger_price))
        if getattr(db_order, "drop_percent", None) is not None:
            baseline.setdefault("drop_percent", float(db_order.drop_percent))
        if getattr(db_order, "reference_ltp_captured_at", None):
            baseline.setdefault(
                "reference_ltp_captured_at",
                db_order.reference_ltp_captured_at.isoformat(),
            )
        config.extra["schedule_baseline"] = baseline
    order_id = getattr(db_order, "order_id", None)
    if config.extra.get("uses_field_references") and not config.extra.get("field_reference_rows") and order_id is not None:
        try:
            from database import get_db_session
            from utils.strategy_builder.reference_store import load_reference_store

            session = get_db_session()
            try:
                store = load_reference_store(session, order_id)
                config.extra["field_reference_rows"] = [
                    {
                        "rule_name": row.rule_name,
                        "symbol": row.symbol,
                        "field_key": row.field_key,
                        "field_type": row.field_type,
                        "numeric_value": row.numeric_value,
                        "text_value": row.text_value,
                        "boolean_value": row.boolean_value,
                        "source": row.source,
                    }
                    for row in store.to_rows()
                ]
            finally:
                session.close()
        except Exception:
            pass
    if order_id is not None:
        config.extra["order_id"] = order_id

    return OrderContext(
        strategy_type=raw_strategy,
        canonical_strategy=canonical,
        side=side,
        symbol=(db_order.symbol or db_order.script_name or "").upper(),
        qty=int(db_order.qty or 0),
        remaining_qty=int(db_order.remaining_quantity or db_order.qty or 0),
        target_price=float(db_order.price or 0),
        stop_loss_price=float(db_order.stop_loss_price) if db_order.stop_loss_price else None,
        stop_limit_price=float(db_order.stop_limit_price) if db_order.stop_limit_price else None,
        book_profit_price=float(db_order.book_profit_price) if db_order.book_profit_price else None,
        profit_target_price=float(db_order.profit_target_price) if db_order.profit_target_price else None,
        trailing_drop_percent=float(db_order.trailing_drop_percent or config.trailing_stop_pct or 3.0),
        stable_band_percent=float(db_order.stable_band_percent or 0.2),
        minimum_wait_minutes=int(db_order.minimum_wait_minutes or 5),
        activation_price=float(db_order.activation_price) if db_order.activation_price else None,
        protected_price=float(db_order.protected_price) if db_order.protected_price else None,
        average_buy_price=float(db_order.average_buy_price) if db_order.average_buy_price else None,
        partial_legs=list(db_order.partial_legs or []),
        executed_legs=list(db_order.executed_legs or []),
        target_reached=bool(db_order.target_reached),
        target_reached_at=db_order.target_reached_at,
        highest_tracked_price=float(db_order.highest_tracked_price) if db_order.highest_tracked_price else None,
        expiry_time=db_order.expiry_time,
        expiry_action=db_order.expiry_action,
        max_allowed_slippage_percent=float(db_order.max_allowed_slippage_percent or 1.0),
        emergency_execution=bool(db_order.emergency_execution),
        below_stop_loss_check_count=int(db_order.below_stop_loss_check_count or 0),
        last_checked_ltp=float(db_order.last_checked_ltp) if db_order.last_checked_ltp else None,
        config=config,
        legacy_alias=raw_strategy if raw_strategy != canonical else None,
    )


def build_scanner_memory(db_order, snapshot_ltp: float, snapshot_volume: Optional[float]) -> ScannerMemory:
    prices = list(getattr(db_order, "scan_price_history", None) or [])
    volumes = list(getattr(db_order, "scan_volume_history", None) or [])
    previous_ltp = prices[-1] if prices else db_order.last_checked_ltp
    previous_volume = volumes[-1] if volumes else None
    entry = context_entry_price(db_order)
    return ScannerMemory(
        last_prices=prices,
        last_volumes=volumes,
        previous_ltp=float(previous_ltp) if previous_ltp is not None else None,
        previous_volume=float(previous_volume) if previous_volume is not None else None,
        highest_after_buy=float(db_order.highest_tracked_price) if db_order.highest_tracked_price else None,
        entry_price=entry,
        holding_qty=int(db_order.remaining_quantity or db_order.qty or 0),
    )


def context_entry_price(db_order) -> Optional[float]:
    if db_order.average_buy_price:
        return float(db_order.average_buy_price)
    if db_order.order_type and db_order.order_type.lower() == "buy":
        return float(db_order.price or 0) or None
    return None


def update_scan_history(db_order, ltp: float, volume: Optional[float]) -> Dict[str, List[float]]:
    prices = list(getattr(db_order, "scan_price_history", None) or [])
    volumes = list(getattr(db_order, "scan_volume_history", None) or [])
    prices.append(float(ltp))
    if volume is not None:
        volumes.append(float(volume))
    prices = prices[-10:]
    volumes = volumes[-10:]
    db_order.scan_price_history = prices
    db_order.scan_volume_history = volumes
    return {"scan_price_history": prices, "scan_volume_history": volumes}
