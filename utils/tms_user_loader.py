import time
from typing import Dict

from database import get_db_session
from models.logged_in_user import LoggedInUsers
from models.user import User
from utils.tms_client_resolver import get_tms_user_for_client


AUTO_LOGIN_RETRY_BASE_SECONDS = 60.0
AUTO_LOGIN_RETRY_MAX_SECONDS = 15 * 60.0
_auto_login_failures: Dict[str, tuple[int, float]] = {}


def auto_login_retry_allowed(client_id: str) -> bool:
    state = _auto_login_failures.get(str(client_id))
    return state is None or time.monotonic() >= state[1]


def record_auto_login_success(client_id: str) -> None:
    _auto_login_failures.pop(str(client_id), None)


def record_auto_login_failure(client_id: str) -> None:
    key = str(client_id)
    attempts = _auto_login_failures.get(key, (0, 0.0))[0] + 1
    delay = min(AUTO_LOGIN_RETRY_MAX_SECONDS, AUTO_LOGIN_RETRY_BASE_SECONDS * (2 ** (attempts - 1)))
    _auto_login_failures[key] = (attempts, time.monotonic() + delay)


async def load_tms_users_instances(client_ids, tms_instances: Dict):
    db = get_db_session()
    try:
        normalized_ids = {str(client_id) for client_id in client_ids}
        sessions = (
            db.query(LoggedInUsers)
            .filter(LoggedInUsers.client_id.in_(normalized_ids))
            .all()
        )
        users = db.query(User).filter(User.client_id.in_(normalized_ids)).all()
        sessions_by_id = {row.client_id: row for row in sessions}
        users_by_id = {row.client_id: row for row in users}

        for client_id in normalized_ids:
            if client_id in tms_instances:
                continue
            session = sessions_by_id.get(client_id)
            user = users_by_id.get(client_id)
            # Every requested client here owns an active scheduled order. The order
            # itself authorizes session recovery even if an older account toggle is off.
            may_auto_login = user is not None
            is_logged_in = bool(session and session.status == "logged_in")
            if not is_logged_in and not may_auto_login:
                continue
            if not auto_login_retry_allowed(client_id):
                continue
            try:
                tms_instances[client_id] = await get_tms_user_for_client(
                    client_id,
                    db,
                    allow_full_login=True,
                )
                record_auto_login_success(client_id)
            except Exception:
                tms_instances.pop(client_id, None)
                record_auto_login_failure(client_id)
    finally:
        db.close()
    return tms_instances
