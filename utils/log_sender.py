# log_sender.py

from sqlalchemy.orm import Session
from models.order_log import OrderLog
from datetime import datetime, timezone

# Function to store or update logs in the database
async def store_or_update_logs(db: Session, client_id: str, script_name: str, scanning_count: int, current_price: float, order_placed: bool, log_message: str = None):
    log_entry = db.query(OrderLog).filter_by(client_id=client_id, script_name=script_name).first()

    if log_entry:
        if log_entry.scanning_count<scanning_count:
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
            logs=log_message
        )
        db.add(log_entry)
    db.commit()
    return log_entry
