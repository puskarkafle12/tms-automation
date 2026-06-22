"""Resolve a logged-in TMS user with the correct broker host (not client_id)."""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from models.logged_in_user import LoggedInUsers
from models.user import User
from utils.tms import TmsUser
from utils.tms_broker import normalize_broker_no, tms_host_for_broker

__all__ = ["normalize_broker_no", "tms_host_for_broker", "get_tms_user_for_client"]


async def get_tms_user_for_client(
    client_id: str,
    db: Session,
    *,
    request_per_sec: float = 5,
    allow_full_login: bool = True,
) -> TmsUser:
    """Build TmsUser from DB session using broker_no — never use client_id as broker."""
    user = db.query(User).filter(User.client_id == client_id).first()
    if not user:
        raise ValueError(f"TMS account not found for client {client_id}.")

    session = (
        db.query(LoggedInUsers)
        .filter(LoggedInUsers.client_id == client_id, LoggedInUsers.status == "logged_in")
        .first()
    )
    broker_source = (session.broker_no if session and session.broker_no else None) or user.broker_no
    broker_no = normalize_broker_no(broker_source)

    tms_user = TmsUser(
        broker_no=broker_no,
        username=user.client_id,
        password=user.password,
        request_per_sec=request_per_sec,
    )
    await tms_user.try_cached_login(allow_full_login=allow_full_login)
    return tms_user
