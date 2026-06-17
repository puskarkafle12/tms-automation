# tasks.py

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Type

from database import SessionLocal
from models.logged_in_user import LoggedInUsers
from models.order_status_log import OrderStatusLog
from models.scheduled_order import ScheduledOrder
from utils.base_functions import truncate_to_one_decimal_place
from utils.lot_size import get_board_lot_size, is_regular_lot_qty, normalize_sell_qty, round_down_to_board_lot
from utils.log_sender import store_or_update_logs
from utils.market_gate import resolve_market_gate
from utils.tms import TmsUser
from utils.strategies.normalize import get_script_details, normalize_tms_quote
from utils.strategies.order_context import build_scanner_memory, update_scan_history
from utils.strategies.registry import decision_to_execute_dict, evaluate_strategy
from utils.tms_user_loader import load_tms_users_instances
import config.tms_config as config


MAX_PRICE_FETCH_CONCURRENCY = 5
TERMINAL_STATUSES = {
    "order_placed",
    "Executed",
    "Cancelled",
    "Failed",
    "Expired",
    "Blocked by slippage",
    "BlockedByLotRule",
}
ACTIVE_STATUSES = {
    "pending",
    "Waiting",
    "Monitoring",
    "Stop-loss monitoring",
    "Profit target waiting",
    "Profit target reached",
    "Waiting minimum time",
    "Waiting activation",
    "Tracking highest price",
    "Drop detected",
    "Stop-loss triggered",
    "Partially executed",
}


async def _latest_holding_qty(tms_user: TmsUser, script_name: str) -> int:
    normalized_symbol = script_name.strip().upper()
    holdings = await tms_user.get_user_stock_details()
    for holding in holdings or []:
        scrip = str(holding.get("scrip") or "").strip().upper()
        name = str(holding.get("symbolName") or "").strip().upper()
        if scrip == normalized_symbol or name == normalized_symbol:
            return int(float(holding.get("currentBalance") or 0))
    return 0


async def _validate_execution_lot_rule(
    db_order: ScheduledOrder,
    tms_user: TmsUser,
    requested_qty: int,
    security_details: Optional[dict],
) -> Optional[str]:
    merged_security = {
        **(db_order.security_details or {}),
        **(security_details or {}),
    }
    odd_lot_allowed = bool(merged_security.get("odd_lot_allowed") or merged_security.get("oddLotAllowed"))
    if odd_lot_allowed:
        return None

    lot_size = get_board_lot_size(merged_security)
    if (db_order.order_type or "").lower() == "buy":
        if not is_regular_lot_qty(requested_qty, lot_size):
            return f"Execution blocked because quantity {requested_qty} is not a board-lot multiple of {lot_size} kitta."
        if requested_qty < lot_size:
            return f"Execution blocked because buy quantity is below minimum board lot of {lot_size} kitta."
        return None

    holding_qty = await _latest_holding_qty(tms_user, db_order.script_name)
    if holding_qty <= 0:
        return f"Execution blocked because {db_order.script_name} is not available in DP holdings."
    if requested_qty > holding_qty:
        return f"Execution blocked because selling {requested_qty} exceeds latest holding {holding_qty}."

    normalized = normalize_sell_qty(requested_qty, holding_qty, lot_size)
    if not normalized.get("is_sell_all") and normalized.get("qty") != requested_qty:
        remaining = holding_qty - requested_qty
        if 0 < remaining < lot_size:
            return (
                f"Execution blocked because selling {requested_qty} from {holding_qty} "
                f"would leave {remaining} kitta odd-lot remainder."
            )
        return normalized.get("error") or normalized.get("warning") or "Execution blocked by board-lot rule."
    return None


@dataclass
class PendingOrderSnapshot:
    order_id: int
    client_id: str
    security_details: dict
    script_name: str
    price: float
    qty: int
    order_type: str
    strategy_type: str


@dataclass
class OrderQuoteSnapshot:
    order: PendingOrderSnapshot
    scan_count: int
    security_details: Optional[dict]
    current_price: Optional[float]
    quote: Optional[dict] = None
    high_price: Optional[float] = None
    error_message: Optional[str] = None


def _load_logged_in_client_ids():
    db = SessionLocal()
    try:
        return [
            user.client_id
            for user in db.query(LoggedInUsers).filter(LoggedInUsers.status == "logged_in").all()
        ]
    finally:
        db.close()


def _load_monitor_cycle_data():
    db = SessionLocal()
    try:
        pending_orders = (
            db.query(ScheduledOrder)
            .filter(ScheduledOrder.status.in_(ACTIVE_STATUSES))
            .all()
        )
        snapshots = [
            PendingOrderSnapshot(
                order_id=order.order_id,
                client_id=order.client_id,
                security_details=order.security_details or {},
                script_name=order.script_name,
                price=order.price,
                qty=order.qty,
                order_type=order.order_type,
                strategy_type=order.strategy_type or "Fixed Price",
            )
            for order in pending_orders
        ]
        client_ids = {order.client_id for order in pending_orders}
        logged_out_client_ids = [
            user.client_id
            for user in db.query(LoggedInUsers).filter(LoggedInUsers.status == "logged_out").all()
        ]
        return snapshots, client_ids, logged_out_client_ids
    finally:
        db.close()


def _status_log_from_order(order: ScheduledOrder) -> OrderStatusLog:
    return OrderStatusLog(
        order_id=order.order_id,
        client_id=order.client_id,
        security_details=order.security_details,
        script_name=order.script_name,
        qty=order.qty,
        status=order.status,
        price=order.price,
        order_type=order.order_type,
    )


def _top_level_price(quote: Optional[dict], side: str) -> tuple[Optional[float], str]:
    if not quote:
        return None, "missing quote"
    levels = quote.get("topBuy") if side.lower() == "sell" else quote.get("topSell")
    source = "Top Buy" if side.lower() == "sell" else "Top Sell"
    for level in levels or []:
        price = level.get("price")
        quantity = level.get("quantity")
        if price and float(price) > 0 and (quantity is None or float(quantity) > 0):
            return float(price), source
    ltp = quote.get("ltp")
    if ltp:
        return float(ltp), "LTP fallback"
    return None, "missing market depth"


def _mark_tracking(db_order: ScheduledOrder, status: str, current_price: float) -> None:
    now = datetime.utcnow()
    db_order.status = status
    db_order.last_checked_ltp = current_price
    db_order.last_checked_at = now
    db_order.updated_at = now


def _strategy_price(order: ScheduledOrder, quote: Optional[dict], fallback: float) -> tuple[float, str]:
    execution_price, source = _top_level_price(quote, order.order_type or "sell")
    if execution_price is None:
        return fallback, "LTP fallback"
    return execution_price, source


def _naive_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _evaluate_strategy(
    db_order: ScheduledOrder,
    current_price: float,
    quote: Optional[dict],
) -> tuple[Optional[dict], Optional[str]]:
    update_scan_history(db_order, current_price, (quote or {}).get("volume"))
    snapshot = normalize_tms_quote(db_order.script_name, quote)
    snapshot.ltp = float(current_price)
    memory = build_scanner_memory(db_order, current_price, snapshot.volume)
    details = get_script_details(db_order.script_name)

    decision = evaluate_strategy(db_order, snapshot, memory, details)

    if decision.action == "EXPIRE":
        _mark_tracking(db_order, decision.tracking_status or "Expired", current_price)
        if decision.cancelled_reason:
            db_order.cancelled_reason = decision.cancelled_reason
        return None, f"{decision.reason_code}: {decision.reason}"

    if decision.action == "EXECUTE":
        execute_payload = decision_to_execute_dict(decision)
        if execute_payload:
            return execute_payload, None

    if decision.tracking_status:
        _mark_tracking(db_order, decision.tracking_status, current_price)
    elif decision.action in {"WATCH", "NO_TRADE", "SKIP", "TRACK"}:
        _mark_tracking(db_order, "Monitoring", current_price)

    if decision.failed_reason:
        db_order.failed_reason = decision.failed_reason

    log_message = f"{decision.reason_code}: {decision.reason}"
    if decision.action in {"WATCH", "NO_TRADE", "SKIP"}:
        return None, log_message
    return None, None


async def monitor_order_task_func():
    tms_users_instances: Dict[str, Type[TmsUser]] = {}
    count_dict = {}
    security_cache = {}
    price_fetch_sem = asyncio.Semaphore(MAX_PRICE_FETCH_CONCURRENCY)

    try:
        while config.is_running:
            pending_orders = []
            try:
                pending_orders, client_ids, logged_out_client_ids = await asyncio.to_thread(
                    _load_monitor_cycle_data
                )

                for client_id in logged_out_client_ids:
                    tms_users_instances.pop(client_id, None)

                missing_client_ids = [
                    client_id for client_id in client_ids
                    if client_id not in tms_users_instances
                ]
                if missing_client_ids:
                    try:
                        tms_users_instances = await load_tms_users_instances(client_ids, tms_users_instances)
                    except Exception:
                        pass

                gate_users = tms_users_instances
                if not gate_users:
                    logged_in_ids = await asyncio.to_thread(_load_logged_in_client_ids)
                    if logged_in_ids:
                        try:
                            gate_users = await load_tms_users_instances(set(logged_in_ids), {})
                        except Exception:
                            gate_users = {}

                execution_gate = await resolve_market_gate(gate_users)
                config.scheduled_phase = execution_gate["phase"]
                config.scheduled_status_message = execution_gate["message"]

                if not execution_gate["can_scan"]:
                    db = SessionLocal()
                    try:
                        for order in pending_orders:
                            key = (order.client_id, order.script_name)
                            await store_or_update_logs(
                                db,
                                order.client_id,
                                order.script_name,
                                count_dict.get(key, 0),
                                None,
                                False,
                                execution_gate["message"],
                                commit=False,
                            )
                        db.commit()
                    finally:
                        db.close()

                    try:
                        await asyncio.sleep(config.monitor_interval)
                    except asyncio.CancelledError:
                        break
                    continue

                async def fetch_order_snapshot(order: PendingOrderSnapshot) -> OrderQuoteSnapshot:
                    key = (order.client_id, order.script_name)
                    count_dict[key] = count_dict.get(key, 0) + 1
                    scan_count = count_dict[key]

                    tms_user = tms_users_instances.get(order.client_id)
                    if not tms_user:
                        return OrderQuoteSnapshot(
                            order=order,
                            scan_count=scan_count,
                            security_details=None,
                            current_price=None,
                            error_message=f"Client ID {order.client_id} is not logged in.",
                        )

                    try:
                        security_key = (order.client_id, order.script_name.upper())
                        security_details = security_cache.get(security_key)
                        if not security_details:
                            security_details = await tms_user.get_security_id(order.script_name)
                            if security_details:
                                security_cache[security_key] = security_details

                        if not security_details:
                            return OrderQuoteSnapshot(
                                order=order,
                                scan_count=scan_count,
                                security_details=None,
                                current_price=None,
                                error_message=f"Security not found for {order.script_name}",
                            )

                        async with price_fetch_sem:
                            quote = await tms_user.get_stock_details_async(
                                security_details["id"],
                                max_retries=1,
                            )
                        if quote is None:
                            return OrderQuoteSnapshot(
                                order=order,
                                scan_count=scan_count,
                                security_details=security_details,
                                current_price=None,
                                error_message="Price fetch failed",
                            )

                        return OrderQuoteSnapshot(
                            order=order,
                            scan_count=scan_count,
                            security_details=security_details,
                            current_price=quote.get("ltp"),
                            quote=quote,
                            high_price=quote.get("high"),
                        )
                    except Exception as exc:
                        return OrderQuoteSnapshot(
                            order=order,
                            scan_count=scan_count,
                            security_details=None,
                            current_price=None,
                            error_message=f"An error occurred: {exc}",
                        )

                snapshots = await asyncio.gather(
                    *(fetch_order_snapshot(order) for order in pending_orders)
                )

                db = SessionLocal()
                try:
                    for snapshot in snapshots:
                        order = snapshot.order
                        key = (order.client_id, order.script_name)

                        if snapshot.error_message:
                            await store_or_update_logs(
                                db,
                                order.client_id,
                                order.script_name,
                                snapshot.scan_count,
                                snapshot.current_price or 0,
                                False,
                                snapshot.error_message,
                                commit=False,
                            )
                            continue

                        if snapshot.current_price is None or not snapshot.security_details:
                            continue

                        log_entry = await store_or_update_logs(
                            db,
                            order.client_id,
                            order.script_name,
                            snapshot.scan_count,
                            snapshot.current_price,
                            False,
                            commit=False,
                        )
                        if log_entry.scanning_count > count_dict[key]:
                            count_dict[key] = log_entry.scanning_count

                        db_order = db.query(ScheduledOrder).filter_by(order_id=order.order_id).first()
                        if not db_order or db_order.status in TERMINAL_STATUSES:
                            continue

                        current_price = float(snapshot.current_price)
                        decision, strategy_log = _evaluate_strategy(db_order, current_price, snapshot.quote)
                        if strategy_log:
                            await store_or_update_logs(
                                db,
                                order.client_id,
                                order.script_name,
                                count_dict[key],
                                current_price,
                                False,
                                strategy_log,
                                commit=False,
                            )
                        if decision and decision.get("action") == "execute":
                            if not execution_gate["can_execute"]:
                                await store_or_update_logs(
                                    db,
                                    order.client_id,
                                    order.script_name,
                                    count_dict[key],
                                    current_price,
                                    False,
                                    execution_gate["message"],
                                    commit=False,
                                )
                                continue

                            target_price = truncate_to_one_decimal_place(float(decision["price"]))
                            if db_order.order_type.lower() == "buy" and snapshot.high_price is not None:
                                day_high = truncate_to_one_decimal_place(float(snapshot.high_price))
                                if target_price > day_high:
                                    await store_or_update_logs(
                                        db,
                                        order.client_id,
                                        order.script_name,
                                        count_dict[key],
                                        current_price,
                                        False,
                                        (
                                            f"Buy price ({target_price}) exceeds today's high "
                                            f"({day_high}) for {order.script_name}"
                                        ),
                                        commit=False,
                                    )
                                    continue

                            db_order.status = "Executing"
                            db_order.runner_lock_id = f"{order.order_id}:{snapshot.scan_count}"
                            db.flush()
                            tms_user = tms_users_instances[order.client_id]
                            execution_qty = int(decision.get("qty") or db_order.remaining_quantity or order.qty)
                            lot_rule_error = await _validate_execution_lot_rule(
                                db_order,
                                tms_user,
                                execution_qty,
                                snapshot.security_details,
                            )
                            if lot_rule_error:
                                db_order.status = "BlockedByLotRule"
                                db_order.failed_reason = lot_rule_error
                                await store_or_update_logs(
                                    db,
                                    order.client_id,
                                    order.script_name,
                                    count_dict[key],
                                    current_price,
                                    False,
                                    lot_rule_error,
                                    commit=False,
                                )
                                db.add(_status_log_from_order(db_order))
                                db.delete(db_order)
                                continue

                            order_response = await tms_user.order(
                                target_price,
                                execution_qty,
                                security=snapshot.security_details,
                                order_type=order.order_type,
                            )

                            if order_response.get("status") == 200:
                                await tms_user.refresh_client_collateral()
                                executed_qty = execution_qty
                                db_order.execution_price = target_price
                                db_order.execution_price_source = decision.get("source") or "Target price"
                                db_order.execution_reason = decision.get("reason")
                                db_order.executed_at = datetime.utcnow()
                                db_order.remaining_quantity = max(0, int(db_order.remaining_quantity or order.qty) - executed_qty)
                                if decision.get("leg_id") is not None:
                                    executed_legs = list(db_order.executed_legs or [])
                                    executed_legs.append(decision["leg_id"])
                                    db_order.executed_legs = executed_legs
                                db_order.status = "Executed" if db_order.remaining_quantity <= 0 else "Partially executed"
                                await store_or_update_logs(
                                    db,
                                    order.client_id,
                                    order.script_name,
                                    count_dict[key],
                                    current_price,
                                    True,
                                    f"{db_order.strategy_type or 'Fixed Price'} order placed for {order.script_name}: {db_order.execution_reason or 'trigger reached'}",
                                    commit=False,
                                )
                            else:
                                db_order.status = "Failed"
                                db_order.failed_reason = str(order_response.get("message"))
                                await store_or_update_logs(
                                    db,
                                    order.client_id,
                                    order.script_name,
                                    count_dict[key],
                                    current_price,
                                    False,
                                    f"Failed to place order for {order.script_name}: {order_response.get('message')}",
                                    commit=False,
                                )

                            if db_order.status in {"Executed", "Failed"}:
                                db.add(_status_log_from_order(db_order))
                                db.delete(db_order)
                    db.commit()
                finally:
                    db.close()

            except Exception as exc:
                db = SessionLocal()
                try:
                    for order in pending_orders:
                        await store_or_update_logs(
                            db,
                            order.client_id,
                            order.script_name,
                            count_dict.get((order.client_id, order.script_name), 0),
                            0,
                            False,
                            f"An error occurred: {exc}",
                            commit=False,
                        )
                    db.commit()
                finally:
                    db.close()

            if not config.is_running:
                break

            try:
                await asyncio.sleep(config.monitor_interval)
            except asyncio.CancelledError:
                break
    finally:
        config.is_running = False
        config.scheduled_started_at = None
        config.scheduled_phase = "stopped"
        config.scheduled_status_message = ""
