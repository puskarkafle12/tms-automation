# log_sender.py

from datetime import datetime, timezone
from typing import Iterable, Optional, Set, Tuple

from sqlalchemy.orm import Session

import config.tms_config as tms_config
from models.order_log import OrderLog
from models.scheduled_order import ScheduledOrder

Pair = Tuple[str, str]

TRANSIENT_MONITOR_LOG_PREFIXES = (
    "Price fetch failed",
)


def is_transient_monitor_log_line(line: str) -> bool:
    stripped = (line or "").strip()
    if not stripped:
        return False
    return any(
        stripped.startswith(prefix) or stripped == prefix
        for prefix in TRANSIENT_MONITOR_LOG_PREFIXES
    )


def _normalize_scan_pair(client_id: str, script_name: str) -> Pair:
    return (str(client_id or "").strip(), str(script_name or "").strip())


def request_monitor_scan_count_reset(client_id: str, script_name: str) -> None:
    pair = _normalize_scan_pair(client_id, script_name)
    if not pair[0] or not pair[1]:
        return
    tms_config.scan_count_reset_keys.add(pair)


def consume_monitor_scan_count_resets() -> Set[Pair]:
    resets = set(tms_config.scan_count_reset_keys)
    tms_config.scan_count_reset_keys.clear()
    return resets


def delete_order_log_scan_count(
    db: Session,
    client_id: str,
    script_name: str,
    *,
    commit: bool = False,
) -> bool:
    deleted = (
        db.query(OrderLog)
        .filter(
            OrderLog.client_id == client_id,
            OrderLog.script_name == script_name,
        )
        .delete(synchronize_session=False)
    )
    request_monitor_scan_count_reset(client_id, script_name)
    if commit:
        db.commit()
    return deleted > 0


def delete_order_log_scan_counts_for_client_ids(
    db: Session,
    client_ids: Iterable[str],
    *,
    commit: bool = False,
) -> int:
    normalized = [str(client_id).strip() for client_id in client_ids if str(client_id).strip()]
    if not normalized:
        return 0

    for log in db.query(OrderLog).filter(OrderLog.client_id.in_(normalized)).all():
        request_monitor_scan_count_reset(log.client_id, log.script_name)

    deleted = (
        db.query(OrderLog)
        .filter(OrderLog.client_id.in_(normalized))
        .delete(synchronize_session=False)
    )
    if commit:
        db.commit()
    return deleted


def reset_scan_count_after_scheduled_order_removed(
    db: Session,
    client_id: str,
    script_name: str,
) -> bool:
    remaining = (
        db.query(ScheduledOrder)
        .filter(
            ScheduledOrder.client_id == client_id,
            ScheduledOrder.script_name == script_name,
        )
        .count()
    )
    if remaining > 0:
        return False
    return delete_order_log_scan_count(db, client_id, script_name)


def strip_transient_monitor_log_lines(logs: Optional[str]) -> Optional[str]:
    if not logs:
        return logs
    kept = [
        line
        for line in str(logs).splitlines()
        if line.strip() and not is_transient_monitor_log_line(line)
    ]
    if not kept:
        return None
    return "\n".join(kept)


async def store_or_update_logs(
    db: Session,
    client_id: str,
    script_name: str,
    scanning_count: int,
    current_price: Optional[float],
    order_placed: bool,
    log_message: Optional[str] = None,
    *,
    commit: bool = True,
):
    scanning_count = int(scanning_count or 0)
    if current_price is not None:
        current_price = float(current_price)

    log_entry = db.query(OrderLog).filter_by(
        client_id=client_id,
        script_name=script_name,
    ).first()

    if log_entry:
        if (log_entry.scanning_count or 0) < scanning_count:
            log_entry.scanning_count = scanning_count
        log_entry.current_price = current_price
        log_entry.order_placed = order_placed
        log_entry.timestamp = datetime.now(timezone.utc)
        if log_message:
            log_entry.logs = f"{log_entry.logs}\n{log_message}" if log_entry.logs else log_message
    else:
        log_entry = OrderLog(
            client_id=client_id,
            script_name=script_name,
            scanning_count=scanning_count,
            current_price=current_price,
            order_placed=order_placed,
            timestamp=datetime.now(timezone.utc),
            logs=log_message,
        )
        db.add(log_entry)

    if current_price is not None and current_price > 0:
        log_entry.logs = strip_transient_monitor_log_lines(log_entry.logs)

    if commit:
        db.commit()
    return log_entry
