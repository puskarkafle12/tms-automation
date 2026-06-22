from typing import Dict

from database import get_db_session
from models.logged_in_user import LoggedInUsers
from utils.tms_client_resolver import get_tms_user_for_client


async def load_tms_users_instances(client_ids, tms_instances: Dict):
    db = get_db_session()
    try:
        sessions = (
            db.query(LoggedInUsers)
            .filter(LoggedInUsers.client_id.in_(client_ids), LoggedInUsers.status == "logged_in")
            .all()
        )
        session_ids = {row.client_id for row in sessions}
        for client_id in client_ids:
            if client_id in tms_instances or client_id not in session_ids:
                continue
            try:
                tms_instances[client_id] = await get_tms_user_for_client(
                    client_id,
                    db,
                    allow_full_login=True,
                )
            except Exception:
                tms_instances.pop(client_id, None)
    finally:
        db.close()
    return tms_instances
