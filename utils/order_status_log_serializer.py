from __future__ import annotations

from models.order_status_log import OrderStatusLog
from models.scheduled_order import ScheduledOrder
from utils.api_time import format_api_timestamp


def status_log_from_scheduled_order(order: ScheduledOrder, status: str | None = None) -> OrderStatusLog:
    execution_price = float(order.execution_price) if order.execution_price is not None else None
    requested_price = float(order.price) if order.price is not None else None
    display_price = execution_price if execution_price is not None else requested_price
    return OrderStatusLog(
        order_id=order.order_id,
        client_id=order.client_id,
        security_details=order.security_details,
        script_name=order.script_name,
        qty=order.qty,
        status=status or order.status,
        price=display_price,
        order_type=order.order_type,
        strategy_type=order.strategy_type or "Fixed Price",
        requested_price=requested_price,
        execution_price=execution_price,
        execution_price_source=order.execution_price_source,
        execution_reason=order.execution_reason,
        stop_loss_price=float(order.stop_loss_price) if order.stop_loss_price is not None else None,
        average_buy_price=float(order.average_buy_price) if order.average_buy_price is not None else None,
        max_allowed_slippage_percent=float(order.max_allowed_slippage_percent)
        if order.max_allowed_slippage_percent is not None
        else None,
    )


def serialize_order_status_log(log: OrderStatusLog) -> dict:
    return {
        "log_id": log.log_id,
        "client_id": log.client_id,
        "security_details": log.security_details,
        "script_name": log.script_name,
        "order_id": log.order_id,
        "qty": log.qty,
        "status": log.status,
        "price": log.price,
        "order_type": log.order_type,
        "timestamp": format_api_timestamp(log.timestamp),
        "strategy_type": log.strategy_type,
        "requested_price": log.requested_price,
        "execution_price": log.execution_price,
        "execution_price_source": log.execution_price_source,
        "execution_reason": log.execution_reason,
        "stop_loss_price": log.stop_loss_price,
        "average_buy_price": log.average_buy_price,
        "max_allowed_slippage_percent": log.max_allowed_slippage_percent,
    }
