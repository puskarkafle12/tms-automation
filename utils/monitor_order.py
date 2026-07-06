# tasks.py

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Type

from database import SessionLocal
from models.logged_in_user import LoggedInUsers
from models.order_status_log import OrderStatusLog
from utils.order_status_log_serializer import status_log_from_scheduled_order
from utils.strategies.aliases import canonical_strategy_name
from utils.strategies.execution_price import sell_price_exceeds_slippage
from models.scheduled_order import ScheduledOrder
from utils.base_functions import truncate_to_one_decimal_place
from utils.lot_size import get_board_lot_size, is_regular_lot_qty, normalize_sell_qty, round_down_to_board_lot
from sqlalchemy import or_, update

from utils.strategy_builder.constants import RULE_BASED_STRATEGIES
from utils.log_sender import consume_monitor_scan_count_resets, store_or_update_logs
from utils.market_gate import resolve_market_gate
from utils.live_quote_socket import live_quote_manager
from utils.tms import TmsUser
from utils.strategies.normalize import normalize_tms_quote
from utils.strategies.order_context import build_scanner_memory, update_scan_history
from utils.strategies.registry import decision_to_execute_dict, evaluate_strategy
from utils.strategies.types import ScriptDetails
from utils.tms_user_loader import load_tms_users_instances
from utils.monitor_scan_settings import (
    advance_nepse_alpha_scan_due_at,
    advance_tms_scan_due_at,
    ensure_scan_phase_offset_in_config,
    initial_tms_scan_due_at,
    is_tms_scan_due,
    order_requires_nepse_alpha,
)
import config.tms_config as config


MAX_PRICE_FETCH_CONCURRENCY = 1
MONITOR_SOCKET_RETRY_ATTEMPTS = 3
MONITOR_SOCKET_RETRY_DELAY_SECONDS = 20
MONITOR_SOCKET_FALLBACK_COOLDOWN_SECONDS = 60.0
MONITOR_SOCKET_FAILURE_THRESHOLD = 3
TERMINAL_STATUSES = {
    "order_placed",
    "Executed",
    "Cancelled",
    "Failed",
    "Expired",
    "Blocked by slippage",
    "BlockedByLotRule",
}

_monitor_socket_failure_state: Dict[tuple[str, str], Dict[str, float | int]] = {}
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
    "WatchingRecovery",
    "EXPIRY_PENDING_MARKET_OPEN",
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
    quote_source: str = "http"
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
            .filter(
                or_(
                    ScheduledOrder.status.in_(ACTIVE_STATUSES),
                    (
                        ScheduledOrder.strategy_type.in_(RULE_BASED_STRATEGIES)
                        & ~ScheduledOrder.status.in_(TERMINAL_STATUSES)
                    ),
                )
            )
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
    return status_log_from_scheduled_order(order)


def _monitor_socket_key(order: PendingOrderSnapshot) -> tuple[str, str]:
    return (order.client_id, order.script_name.strip().upper())


def _monitor_socket_polling_only(key: tuple[str, str]) -> bool:
    state = _monitor_socket_failure_state.get(key)
    if not state:
        return False
    fallback_until = float(state.get("fallback_until") or 0.0)
    return fallback_until > 0 and time.monotonic() < fallback_until


def _record_monitor_socket_success(key: tuple[str, str]) -> None:
    _monitor_socket_failure_state.pop(key, None)


def _record_monitor_socket_failure(key: tuple[str, str], *, terminal: bool = False) -> None:
    now = time.monotonic()
    state = _monitor_socket_failure_state.get(key, {"failures": 0, "fallback_until": 0.0})
    failures = MONITOR_SOCKET_FAILURE_THRESHOLD if terminal else int(state.get("failures") or 0) + 1
    if failures >= MONITOR_SOCKET_FAILURE_THRESHOLD:
        state = {
            "failures": 0,
            "fallback_until": now + MONITOR_SOCKET_FALLBACK_COOLDOWN_SECONDS,
        }
    else:
        state = {
            "failures": failures,
            "fallback_until": 0.0,
        }
    _monitor_socket_failure_state[key] = state


async def _handle_recovery_watch(
    db_order: ScheduledOrder,
    tms_user: TmsUser,
    current_price: float,
) -> bool:
    """Cancel a freshly placed stop-loss sell if price recovers above the stop."""
    stop_price = float(db_order.stop_loss_price or 0)
    if stop_price <= 0 or current_price <= stop_price * 1.005:
        return False

    exchange_ids = {
        item.strip()
        for item in str(db_order.runner_lock_id or "").split(",")
        if item.strip()
    }
    if not exchange_ids:
        exchange_ids = await tms_user.get_open_order_ids_for_symbol(db_order.script_name)

    if not exchange_ids:
        return False

    await tms_user.cancel_open_orders_for_symbol(db_order.script_name, exchange_ids)
    db_order.status = "Cancelled"
    db_order.cancelled_reason = (
        f"Sell cancelled after recovery: LTP {current_price:.2f} moved back above stop {stop_price:.2f}"
    )
    return True


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
    if status not in ACTIVE_STATUSES:
        status = "Monitoring"
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


def _resolve_script_details_for_order(
    db_order: ScheduledOrder,
    *,
    nepse_fetch_due: bool,
) -> tuple[ScriptDetails, bool]:
    """Return script details and whether a Nepse Alpha network fetch was attempted."""
    if not order_requires_nepse_alpha(db_order):
        return ScriptDetails(available=False), False

    from utils.strategies.normalize import get_script_details, get_script_details_fetch_meta

    if nepse_fetch_due:
        return get_script_details_fetch_meta(db_order.script_name, force_refresh=False)
    return get_script_details(db_order.script_name, force_refresh=False), False


def _evaluate_strategy(
    db_order: ScheduledOrder,
    current_price: float,
    quote: Optional[dict],
    *,
    scan_count: int = 0,
    db=None,
    details: Optional[ScriptDetails] = None,
    nepse_network_attempted: bool = False,
) -> tuple[Optional[dict], Optional[str]]:
    update_scan_history(db_order, current_price, (quote or {}).get("volume"))
    snapshot = normalize_tms_quote(db_order.script_name, quote)
    snapshot.ltp = float(current_price)
    memory = build_scanner_memory(db_order, current_price, snapshot.volume)
    if details is None:
        details, nepse_network_attempted = _resolve_script_details_for_order(
            db_order,
            nepse_fetch_due=True,
        )

    config_payload = dict(getattr(db_order, "strategy_config", None) or {})
    if db is not None:
        from utils.strategy_builder.reference_store import hydrate_strategy_config_references

        config_payload = hydrate_strategy_config_references(db, db_order.order_id, config_payload)
    config_payload["tms_scan_count"] = int(scan_count or 0)
    db_order.tms_scan_count = int(scan_count or 0)
    if nepse_network_attempted:
        next_nepse_scan_count = int(config_payload.get("nepse_alpha_scan_count") or 0) + 1
        config_payload["nepse_alpha_scan_count"] = next_nepse_scan_count
        db_order.nepse_alpha_scan_count = next_nepse_scan_count
    db_order.strategy_config = config_payload

    decision = evaluate_strategy(db_order, snapshot, memory, details)

    if decision.action == "EXPIRE":
        db_order.status = decision.tracking_status or "Expired"
        db_order.last_checked_ltp = current_price
        db_order.last_checked_at = datetime.utcnow()
        if decision.cancelled_reason:
            db_order.cancelled_reason = decision.cancelled_reason
        config_payload = dict(getattr(db_order, "strategy_config", None) or {})
        reason = config_payload.get("expiration_execution_reason")
        if reason:
            db_order.execution_reason = str(reason)
        return {"action": "expire"}, f"{decision.reason_code}: {decision.reason}"

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
    if decision.action in {"WATCH", "NO_TRADE", "SKIP", "TRACK"}:
        return None, log_message
    return None, None


@dataclass
class TmsSubmissionResult:
    submitted: bool
    blocked_reason: Optional[str] = None
    target_price: Optional[float] = None
    execution_qty: Optional[int] = None
    order_response: Optional[dict] = None
    lot_rule_blocked: bool = False
    retryable: bool = False


def _try_claim_order_for_execution(db, order_id: int) -> bool:
    result = db.execute(
        update(ScheduledOrder)
        .where(
            ScheduledOrder.order_id == order_id,
            ScheduledOrder.status.in_(list(ACTIVE_STATUSES)),
        )
        .values(status="Executing", updated_at=datetime.utcnow())
    )
    return bool(result.rowcount)


def _release_execution_claim(db, order_id: int, *, status: str = "Monitoring") -> None:
    db.execute(
        update(ScheduledOrder)
        .where(
            ScheduledOrder.order_id == order_id,
            ScheduledOrder.status == "Executing",
        )
        .values(status=status, updated_at=datetime.utcnow())
    )


async def submit_scheduled_order_to_tms(
    db_order: ScheduledOrder,
    decision: dict,
    *,
    high_price: Optional[float],
    fallback_qty: int,
    security_details: dict,
    order_type: str,
    tms_user: TmsUser,
    execution_gate: dict,
) -> TmsSubmissionResult:
    if not decision or decision.get("action") != "execute":
        return TmsSubmissionResult(submitted=False, blocked_reason="not_execute")

    if not execution_gate.get("can_execute"):
        return TmsSubmissionResult(submitted=False, blocked_reason=execution_gate.get("message"))

    target_price = truncate_to_one_decimal_place(float(decision["price"]))
    if order_type.lower() == "buy" and high_price is not None:
        day_high = truncate_to_one_decimal_place(float(high_price))
        if target_price > day_high:
            return TmsSubmissionResult(
                submitted=False,
                blocked_reason=(
                    f"Buy price ({target_price}) exceeds today's high "
                    f"({day_high}) for {db_order.script_name}"
                ),
            )

    from utils.strategy_builder.execution_quantity import (
        apply_quantity_resolution_audit,
        resolve_execution_quantity,
    )

    order_action = decision.get("order_action")
    if order_action:
        resolution = await resolve_execution_quantity(
            scheduled_order=db_order,
            matched_order_action=order_action,
            tms_user=tms_user,
            symbol=db_order.script_name,
            side=order_type,
            security_details=security_details,
        )
        db_order.strategy_config = apply_quantity_resolution_audit(
            getattr(db_order, "strategy_config", None),
            resolution,
        )
        if resolution.error or resolution.final_quantity <= 0:
            return TmsSubmissionResult(
                submitted=False,
                blocked_reason=resolution.error or "Execution quantity could not be resolved.",
                retryable=resolution.retryable,
            )
        execution_qty = int(resolution.final_quantity)
    else:
        execution_qty = int(decision.get("qty") or db_order.remaining_quantity or fallback_qty)

    lot_rule_error = await _validate_execution_lot_rule(
        db_order,
        tms_user,
        execution_qty,
        security_details,
    )
    if lot_rule_error:
        db_order.status = "BlockedByLotRule"
        return TmsSubmissionResult(
            submitted=False,
            blocked_reason=lot_rule_error,
            lot_rule_blocked=True,
        )

    order_response = await tms_user.order(
        target_price,
        execution_qty,
        security=security_details,
        order_type=order_type,
    )
    return TmsSubmissionResult(
        submitted=True,
        target_price=target_price,
        execution_qty=execution_qty,
        order_response=order_response,
    )


async def monitor_order_task_func():
    from config.portal_settings import get_portal_settings

    tms_users_instances: Dict[str, Type[TmsUser]] = {}
    count_dict: Dict[tuple, int] = {}
    security_cache = {}
    next_tms_scan_at: Dict[int, float] = {}
    next_nepse_alpha_scan_at: Dict[int, float] = {}
    last_nepse_alpha_details: Dict[int, ScriptDetails] = {}
    price_fetch_sem: Optional[asyncio.Semaphore] = None
    price_fetch_sem_limit = 0

    try:
        while config.is_running:
            for reset_key in consume_monitor_scan_count_resets():
                count_dict.pop(reset_key, None)

            pending_orders = []
            tick_seconds = int(getattr(config, "monitor_tick_seconds", None) or 1)
            try:
                portal_settings = get_portal_settings()
                tms_interval = int(portal_settings.get("monitor_interval_seconds") or config.monitor_interval or 5)
                nepse_interval = int(
                    portal_settings.get("nepse_alpha_interval_seconds") or config.nepse_alpha_interval_seconds or 1800
                )
                tick_seconds = int(portal_settings.get("monitor_tick_seconds") or config.monitor_tick_seconds or 1)
                stagger_enabled = bool(
                    portal_settings.get("enable_scan_staggering", config.enable_scan_staggering)
                )
                fetch_concurrency = int(
                    portal_settings.get("max_price_fetch_concurrency")
                    or config.max_price_fetch_concurrency
                    or MAX_PRICE_FETCH_CONCURRENCY
                )
                if price_fetch_sem is None or price_fetch_sem_limit != fetch_concurrency:
                    price_fetch_sem = asyncio.Semaphore(fetch_concurrency)
                    price_fetch_sem_limit = fetch_concurrency

                pending_orders, client_ids, logged_out_client_ids = await asyncio.to_thread(
                    _load_monitor_cycle_data
                )

                active_order_ids = {order.order_id for order in pending_orders}
                for order_id in list(next_tms_scan_at):
                    if order_id not in active_order_ids:
                        next_tms_scan_at.pop(order_id, None)
                        next_nepse_alpha_scan_at.pop(order_id, None)
                        last_nepse_alpha_details.pop(order_id, None)

                now = time.time()
                for order in pending_orders:
                    if order.order_id not in next_tms_scan_at:
                        next_tms_scan_at[order.order_id] = initial_tms_scan_due_at(
                            now,
                            order.order_id,
                            tms_interval,
                            stagger_enabled=stagger_enabled,
                        )

                due_orders = [
                    order
                    for order in pending_orders
                    if is_tms_scan_due(next_tms_scan_at.get(order.order_id), now)
                ]

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
                        await asyncio.sleep(tick_seconds)
                    except asyncio.CancelledError:
                        break
                    continue

                async def fetch_order_snapshot(order: PendingOrderSnapshot) -> OrderQuoteSnapshot:
                    key = (order.client_id, order.script_name)
                    monitor_socket_key = _monitor_socket_key(order)
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

                        live_snapshot = None
                        quote = None
                        quote_source = "http"
                        socket_state = None

                        if not _monitor_socket_polling_only(monitor_socket_key):
                            await live_quote_manager.ensure_stream(
                                tms_user,
                                order.script_name,
                                str(security_details["id"]),
                            )
                            for attempt in range(MONITOR_SOCKET_RETRY_ATTEMPTS):
                                live_snapshot = await live_quote_manager.wait_for_next_distinct_quote(
                                    order.script_name,
                                    after_signature=str((live_snapshot or {}).get("quote_signature") or ""),
                                    timeout=0.5,
                                )
                                socket_state = live_snapshot or live_quote_manager.get_snapshot(order.script_name)
                                if socket_state and socket_state.get("quote"):
                                    quote = socket_state["quote"]
                                    quote_source = "socket"
                                    _record_monitor_socket_success(monitor_socket_key)
                                    break
                                if socket_state and (
                                    socket_state.get("auth_failed")
                                    or socket_state.get("status") in {"auth_failed", "failed", "closed"}
                                ):
                                    await live_quote_manager.close_symbol(order.script_name)
                                    _record_monitor_socket_failure(monitor_socket_key, terminal=True)
                                    break
                                if attempt < MONITOR_SOCKET_RETRY_ATTEMPTS - 1:
                                    await asyncio.sleep(MONITOR_SOCKET_RETRY_DELAY_SECONDS)
                            else:
                                _record_monitor_socket_failure(monitor_socket_key)

                        if quote is None:
                            async with price_fetch_sem:
                                quote = await tms_user.get_stock_details_async(
                                    security_details["id"],
                                    max_retries=3,
                                    retry_backoff=True,
                                    force_refresh=True,
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
                            high_price=quote.get("high") or quote.get("dayHigh"),
                            quote_source=quote_source,
                        )
                    except Exception as exc:
                        return OrderQuoteSnapshot(
                            order=order,
                            scan_count=scan_count,
                            security_details=None,
                            current_price=None,
                            error_message=f"An error occurred: {exc}",
                        )

                snapshots = []
                if due_orders:
                    snapshots = await asyncio.gather(
                        *(fetch_order_snapshot(order) for order in due_orders)
                    )

                db = SessionLocal()
                try:
                    for snapshot in snapshots:
                        order = snapshot.order
                        key = (order.client_id, order.script_name)
                        scan_finished_at = time.time()
                        next_tms_scan_at[order.order_id] = advance_tms_scan_due_at(
                            scan_finished_at,
                            tms_interval,
                            stagger_enabled=stagger_enabled,
                        )

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

                        if db_order.status == "WatchingRecovery":
                            recovered = await _handle_recovery_watch(db_order, tms_users_instances[order.client_id], current_price)
                            if recovered:
                                await store_or_update_logs(
                                    db,
                                    order.client_id,
                                    order.script_name,
                                    count_dict[key],
                                    current_price,
                                    False,
                                    db_order.cancelled_reason or "Recovery cancel",
                                    commit=False,
                                )
                                db.add(_status_log_from_order(db_order))
                                db.delete(db_order)
                            continue

                        updated_config, _ = ensure_scan_phase_offset_in_config(
                            db_order.strategy_config,
                            db_order.order_id,
                            tms_interval,
                            stagger_enabled=stagger_enabled,
                        )
                        live_snapshot = live_quote_manager.get_snapshot(order.script_name)
                        if live_snapshot:
                            updated_config = {
                                **(updated_config or {}),
                                "last_tms_quote_source": snapshot.quote_source,
                                "last_socket_status": live_snapshot.get("status"),
                                "last_socket_received_at": live_snapshot.get("last_received_at"),
                                "last_socket_message_count": live_snapshot.get("message_count"),
                            }
                        if updated_config != (db_order.strategy_config or {}):
                            db_order.strategy_config = updated_config

                        requires_nepse_alpha = order_requires_nepse_alpha(db_order)
                        nepse_due = requires_nepse_alpha and (
                            db_order.order_id not in next_nepse_alpha_scan_at
                            or is_tms_scan_due(
                                next_nepse_alpha_scan_at.get(db_order.order_id),
                                scan_finished_at,
                            )
                        )
                        nepse_network_attempted = False
                        nepse_source = "cache"
                        if nepse_due:
                            details, nepse_network_attempted = _resolve_script_details_for_order(
                                db_order,
                                nepse_fetch_due=True,
                            )
                            last_nepse_alpha_details[db_order.order_id] = details
                            nepse_source = "live"
                            next_nepse_alpha_scan_at[db_order.order_id] = advance_nepse_alpha_scan_due_at(
                                scan_finished_at,
                                nepse_interval,
                                stagger_enabled=stagger_enabled,
                            )
                        elif requires_nepse_alpha:
                            details = last_nepse_alpha_details.get(db_order.order_id) or ScriptDetails(
                                available=False,
                                fetch_error="Waiting for next Nepse Alpha refresh slot",
                            )
                        else:
                            details = ScriptDetails(available=False)

                        decision, strategy_log = _evaluate_strategy(
                            db_order,
                            current_price,
                            snapshot.quote,
                            scan_count=count_dict[key],
                            db=db,
                            details=details,
                            nepse_network_attempted=nepse_network_attempted,
                        )
                        config_payload = dict(getattr(db_order, "strategy_config", None) or {})
                        config_payload["nepse_alpha_last_source"] = nepse_source
                        if nepse_source == "live" and nepse_network_attempted:
                            config_payload["nepse_alpha_last_fetched_at"] = time.time()
                            db_order.nepse_alpha_last_fetched_at = datetime.utcnow()
                        db_order.nepse_alpha_last_source = nepse_source
                        db_order.strategy_config = config_payload
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
                        if decision and decision.get("action") == "expire":
                            db.add(_status_log_from_order(db_order))
                            db.delete(db_order)
                            continue
                        if decision and decision.get("action") == "execute":
                            if not _try_claim_order_for_execution(db, db_order.order_id):
                                continue
                            db.refresh(db_order)
                            tms_user = tms_users_instances[order.client_id]
                            submission = await submit_scheduled_order_to_tms(
                                db_order,
                                decision,
                                high_price=snapshot.high_price,
                                fallback_qty=order.qty,
                                security_details=snapshot.security_details,
                                order_type=order.order_type,
                                tms_user=tms_user,
                                execution_gate=execution_gate,
                            )
                            if not submission.submitted:
                                if submission.blocked_reason and submission.blocked_reason != "not_execute":
                                    await store_or_update_logs(
                                        db,
                                        order.client_id,
                                        order.script_name,
                                        count_dict[key],
                                        current_price,
                                        False,
                                        submission.blocked_reason,
                                        commit=False,
                                    )
                                if submission.lot_rule_blocked:
                                    db_order.failed_reason = submission.blocked_reason
                                    db.add(_status_log_from_order(db_order))
                                    db.delete(db_order)
                                elif submission.retryable:
                                    db_order.failed_reason = submission.blocked_reason
                                    _release_execution_claim(db, db_order.order_id, status="Monitoring")
                                continue

                            db_order.runner_lock_id = f"{order.order_id}:{snapshot.scan_count}"
                            db.flush()
                            target_price = submission.target_price
                            execution_qty = submission.execution_qty
                            order_response = submission.order_response or {}

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
                                canonical = canonical_strategy_name(
                                    db_order.strategy_type or "",
                                    db_order.order_type or "sell",
                                )
                                reference_price = float(db_order.stop_loss_price or db_order.price or 0)
                                if (
                                    db_order.order_type.lower() == "sell"
                                    and reference_price > 0
                                    and sell_price_exceeds_slippage(
                                        requested_price=reference_price,
                                        execution_price=target_price,
                                        max_slippage_percent=float(db_order.max_allowed_slippage_percent or 1.0),
                                    )
                                ):
                                    open_ids = await tms_user.get_open_order_ids_for_symbol(db_order.script_name)
                                    if open_ids:
                                        await tms_user.cancel_open_orders_for_symbol(db_order.script_name, open_ids)
                                    db_order.status = "Blocked by slippage"
                                    db_order.failed_reason = (
                                        f"Sell blocked: limit {target_price} exceeded allowed slippage from {reference_price}"
                                    )
                                elif canonical == "Capital Protection Sell" and db_order.remaining_quantity <= 0:
                                    open_ids = await tms_user.get_open_order_ids_for_symbol(db_order.script_name)
                                    if open_ids:
                                        db_order.status = "WatchingRecovery"
                                        db_order.runner_lock_id = ",".join(sorted(open_ids))
                                    else:
                                        db_order.status = "Executed"
                                else:
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

                            if db_order.status in {"Executed", "Failed", "Cancelled", "Blocked by slippage"}:
                                db.add(_status_log_from_order(db_order))
                                db.delete(db_order)
                            elif db_order.status == "WatchingRecovery":
                                pass
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
                await asyncio.sleep(tick_seconds)
            except asyncio.CancelledError:
                break
    finally:
        config.is_running = False
        config.scheduled_started_at = None
        config.scheduled_phase = "stopped"
        config.scheduled_status_message = ""
