# log_sender.py

import asyncio
from sqlalchemy.orm import Session
from models.order_log import OrderLog
from datetime import datetime, timezone
from database import SessionLocal


def store_or_update_logs_sync(
    client_id: str,
    script_name: str,
    scanning_count: int,
    current_price: float,
    order_placed: bool,
    log_message: str | None = None,
):
    db = SessionLocal()
    try:
        scanning_count = int(scanning_count)
        if current_price is not None:
            current_price = int(round(float(current_price)))
        log_entry = db.query(OrderLog).filter_by(client_id=client_id, script_name=script_name).first()

        if log_entry:
            if log_entry.scanning_count < scanning_count:
                log_entry.scanning_count = scanning_count
            log_entry.current_price = current_price
            log_entry.order_placed = order_placed
            log_entry.timestamp = datetime.now(timezone.utc)
            if log_message:
                if log_entry.logs:
                    log_entry.logs += "\n" + log_message
                else:
                    log_entry.logs = log_message
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
        db.commit()
        db.refresh(log_entry)
        return log_entry
    finally:
        db.close()


async def store_or_update_logs(
    db: Session,
    client_id: str,
    script_name: str,
    scanning_count: int,
    current_price: float,
    order_placed: bool,
    log_message: str | None = None,
):
    del db
    return await asyncio.to_thread(
        store_or_update_logs_sync,
        client_id,
        script_name,
        scanning_count,
        current_price,
        order_placed,
        log_message,
    )
