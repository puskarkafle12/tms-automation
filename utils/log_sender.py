# log_sender.py

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from models.order_log import OrderLog


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

    if commit:
        db.commit()
    return log_entry
