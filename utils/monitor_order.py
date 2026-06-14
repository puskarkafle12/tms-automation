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
from utils.log_sender import store_or_update_logs
from utils.market_gate import resolve_market_gate
from utils.tms import TmsUser
from utils.tms_user_loader import load_tms_users_instances
import config.tms_config as config


MAX_PRICE_FETCH_CONCURRENCY = 5
TERMINAL_STATUSES = {"order_placed", "Executed", "Cancelled", "Failed", "Expired", "Blocked by slippage"}
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


def _evaluate_strategy(db_order: ScheduledOrder, current_price: float, quote: Optional[dict]) -> Optional[dict]:
    strategy = db_order.strategy_type or "Fixed Price"
    now = datetime.utcnow()

    if strategy in {"Fixed Price", "Fixed Price Buy", "Fixed Price Sell"}:
        target_price = truncate_to_one_decimal_place(db_order.price)
        if (
            truncate_to_one_decimal_place(current_price * 0.98)
            <= target_price
            <= truncate_to_one_decimal_place(current_price * 1.02)
        ):
            return {"action": "execute", "price": target_price, "reason": "Fixed price reached"}
        _mark_tracking(db_order, "pending", current_price)
        return None

    if strategy in {"Buy Below Price", "Dip Buy"}:
        target_price = truncate_to_one_decimal_place(db_order.price)
        if current_price <= target_price:
            return {"action": "execute", "price": target_price, "reason": f"{strategy} trigger reached"}
        _mark_tracking(db_order, "Monitoring", current_price)
        return None

    if strategy == "Breakout Buy":
        target_price = truncate_to_one_decimal_place(db_order.price)
        if current_price >= target_price:
            return {"action": "execute", "price": target_price, "reason": "Breakout trigger reached"}
        _mark_tracking(db_order, "Monitoring", current_price)
        return None

    if strategy == "Time-Based Buy":
        expiry_time = _naive_utc(db_order.expiry_time)
        if expiry_time and now >= expiry_time:
            _mark_tracking(db_order, "Expired", current_price)
            db_order.cancelled_reason = "Buy strategy expired"
            return None
        _mark_tracking(db_order, "Monitoring", current_price)
        return None

    execution_price, execution_source = _strategy_price(db_order, quote, current_price)

    if strategy == "Fast Stop Loss":
        stop = float(db_order.stop_loss_price or 0)
        if stop <= 0:
            _mark_tracking(db_order, "Failed", current_price)
            db_order.failed_reason = "Missing stop-loss trigger price"
            return None
        if current_price <= stop:
            count = int(db_order.below_stop_loss_check_count or 0) + 1
            db_order.below_stop_loss_check_count = count
            fast_fall = current_price <= stop * 0.99
            sharp_drop = db_order.last_checked_ltp and current_price <= float(db_order.last_checked_ltp) * 0.99
            if fast_fall or sharp_drop or count >= 2:
                max_slippage = float(db_order.max_allowed_slippage_percent or 1.0)
                slippage = ((stop - execution_price) / stop) * 100 if stop else 0
                if slippage > max_slippage and not db_order.emergency_execution:
                    _mark_tracking(db_order, "Blocked by slippage", current_price)
                    db_order.failed_reason = f"Slippage {slippage:.2f}% exceeded max {max_slippage:.2f}%"
                    return None
                return {"action": "execute", "price": execution_price, "source": execution_source, "reason": "Stop-loss triggered"}
            _mark_tracking(db_order, "Stop-loss triggered", current_price)
            return None
        db_order.below_stop_loss_check_count = 0
        _mark_tracking(db_order, "Stop-loss monitoring", current_price)
        return None

    if strategy == "Stop Limit Sell":
        stop = float(db_order.stop_loss_price or 0)
        limit = float(db_order.stop_limit_price or db_order.limit_price or 0)
        if current_price <= stop and limit > 0:
            return {"action": "execute", "price": limit, "source": "Stop limit", "reason": "Stop-limit trigger reached"}
        _mark_tracking(db_order, "Monitoring", current_price)
        return None

    if strategy == "Trailing Stop Loss":
        activation = db_order.activation_price
        if activation and current_price < float(activation):
            _mark_tracking(db_order, "Waiting activation", current_price)
            return None
        high = max(float(db_order.highest_tracked_price or 0), current_price)
        if high != db_order.highest_tracked_price:
            db_order.highest_tracked_price = high
            db_order.highest_tracked_at = now
        drop = ((high - current_price) / high) * 100 if high else 0
        if drop >= float(db_order.trailing_drop_percent or 1.0):
            return {"action": "execute", "price": execution_price, "source": execution_source, "reason": "Trailing drop detected"}
        _mark_tracking(db_order, "Tracking highest price", current_price)
        return None

    if strategy in {"Smart Profit Booking", "Book Profit + Stop Loss"}:
        if strategy == "Book Profit + Stop Loss":
            stop = float(db_order.stop_loss_price or 0)
            if stop > 0 and current_price <= stop:
                return {"action": "execute", "price": execution_price, "source": execution_source, "reason": "OCO stop-loss side triggered"}
            target = float(db_order.book_profit_price or 0)
        else:
            target = float(db_order.profit_target_price or 0)
        if not db_order.target_reached:
            if target > 0 and current_price >= target:
                db_order.target_reached = True
                db_order.target_reached_at = now
                db_order.highest_tracked_price = current_price
                db_order.highest_tracked_at = now
                _mark_tracking(db_order, "Profit target reached", current_price)
            else:
                _mark_tracking(db_order, "Profit target waiting", current_price)
            return None
        high = max(float(db_order.highest_tracked_price or 0), current_price)
        if high != db_order.highest_tracked_price:
            db_order.highest_tracked_price = high
            db_order.highest_tracked_at = now
        reached_at = _naive_utc(db_order.target_reached_at) or now
        wait_minutes = max(int(db_order.minimum_wait_minutes or 5), 5)
        if now < reached_at + timedelta(minutes=wait_minutes):
            _mark_tracking(db_order, "Waiting minimum time", current_price)
            return None
        trailing = float(db_order.trailing_drop_percent or 0.75)
        if target > 0:
            profit_above_target = ((high - target) / target) * 100
            if profit_above_target >= 12:
                trailing = min(trailing, 0.30)
            elif profit_above_target >= 8:
                trailing = min(trailing, 0.40)
            elif profit_above_target >= 5:
                trailing = min(trailing, 0.50)
            elif profit_above_target >= 3:
                trailing = min(trailing, 0.60)
        drop = ((high - current_price) / high) * 100 if high else 0
        stable_band = float(db_order.stable_band_percent or 0.20)
        if drop >= trailing and drop > stable_band:
            return {"action": "execute", "price": execution_price, "source": execution_source, "reason": "Profit trailing drop detected"}
        _mark_tracking(db_order, "Tracking highest price", current_price)
        return None

    if strategy == "Break-Even Protection":
        avg = float(db_order.average_buy_price or 0)
        activation_price = float(db_order.activation_price or avg * 1.03)
        protected_price = float(db_order.protected_price or avg * 1.005)
        if not db_order.target_reached and current_price >= activation_price:
            db_order.target_reached = True
            db_order.protected_price = protected_price
            db_order.highest_tracked_price = current_price
            db_order.highest_tracked_at = now
        if db_order.target_reached and current_price <= protected_price:
            return {"action": "execute", "price": execution_price, "source": execution_source, "reason": "Break-even protection triggered"}
        if db_order.target_reached:
            db_order.highest_tracked_price = max(float(db_order.highest_tracked_price or 0), current_price)
            _mark_tracking(db_order, "Tracking highest price", current_price)
        else:
            _mark_tracking(db_order, "Waiting activation", current_price)
        return None

    if strategy == "Partial Profit Booking":
        legs = db_order.partial_legs if isinstance(db_order.partial_legs, list) else []
        executed = set(db_order.executed_legs or [])
        total_qty = int(db_order.qty or 0)
        for index, leg in enumerate(legs):
            leg_id = str(leg.get("id") or index)
            target = float(leg.get("targetPrice") or 0)
            percent = float(leg.get("sellPercent") or 0)
            if leg_id not in executed and target > 0 and percent > 0 and current_price >= target:
                leg_qty = max(1, int(total_qty * percent / 100))
                return {
                    "action": "execute",
                    "price": execution_price,
                    "qty": min(leg_qty, int(db_order.remaining_quantity or total_qty)),
                    "source": execution_source,
                    "reason": f"Partial profit leg {leg_id} reached",
                    "leg_id": leg_id,
                }
        high = max(float(db_order.highest_tracked_price or 0), current_price)
        if high != db_order.highest_tracked_price:
            db_order.highest_tracked_price = high
            db_order.highest_tracked_at = now
        remaining_qty = int(db_order.remaining_quantity or total_qty)
        drop = ((high - current_price) / high) * 100 if high else 0
        if remaining_qty > 0 and drop >= float(db_order.trailing_drop_percent or 0.75):
            return {
                "action": "execute",
                "price": execution_price,
                "qty": remaining_qty,
                "source": execution_source,
                "reason": "Remaining partial quantity trailing stop",
            }
        _mark_tracking(db_order, "Tracking highest price", current_price)
        return None

    if strategy == "Time-Based Exit":
        expiry_time = _naive_utc(db_order.expiry_time)
        if expiry_time and now >= expiry_time:
            action = db_order.expiry_action or "Cancel strategy"
            if action == "Sell using Top Buy":
                return {"action": "execute", "price": execution_price, "source": execution_source, "reason": "Time exit expired"}
            _mark_tracking(db_order, "Cancelled" if action == "Cancel strategy" else "Expired", current_price)
            db_order.cancelled_reason = "Strategy expired"
            return None
        _mark_tracking(db_order, "Monitoring", current_price)
        return None

    if strategy == "Emergency Exit":
        return {"action": "execute", "price": execution_price, "source": execution_source, "reason": "Emergency exit confirmed"}

    _mark_tracking(db_order, "Monitoring", current_price)
    return None


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
                        decision = _evaluate_strategy(db_order, current_price, snapshot.quote)
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
                            order_response = await tms_user.order(
                                target_price,
                                int(decision.get("qty") or db_order.remaining_quantity or order.qty),
                                security=snapshot.security_details,
                                order_type=order.order_type,
                            )

                            if order_response.get("status") == 200:
                                executed_qty = int(decision.get("qty") or db_order.remaining_quantity or order.qty)
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
