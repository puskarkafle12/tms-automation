"""Local account authentication, feature permissions, and ownership helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from database import get_db
from models.frontend_user import FrontendUser

JWT_SECRET = os.getenv("APP_SECRET_KEY") or os.getenv("SECRET_KEY") or "change-this-local-secret"
JWT_ALGORITHM = "HS256"
# Long-lived browser sessions: stay signed in across reloads and daily use.
# Override with AUTH_TOKEN_HOURS when a shorter window is required.
JWT_LIFETIME_HOURS = max(1, int(os.getenv("AUTH_TOKEN_HOURS", "720")))
PASSWORD_ITERATIONS = 310_000

FEATURES = (
    "order_logs", "schedule_orders", "portfolio", "market_analysis", "stock_grabber",
    "strategy_details", "backtest", "recommendations", "stock_table", "edis",
    "settings", "tms_login", "admin_users",
)
DEFAULT_USER_PERMISSIONS = tuple(item for item in FEATURES if item not in {"stock_grabber", "admin_users"})


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        PASSWORD_ITERATIONS,
        base64.urlsafe_b64encode(salt).decode("ascii").rstrip("="),
        base64.urlsafe_b64encode(digest).decode("ascii").rstrip("="),
    )


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded:
        return False
    if not encoded.startswith("pbkdf2_sha256$"):
        return hmac.compare_digest(str(encoded), password)
    try:
        _, iterations, salt, expected = encoded.split("$", 3)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), _decode(salt), int(iterations))
        return hmac.compare_digest(actual, _decode(expected))
    except (TypeError, ValueError):
        return False


def resolved_permissions(user: FrontendUser) -> list[str]:
    if user.role == "superuser":
        return [item for item in FEATURES if item != "admin_users" or user.managed_by_user_id is None]
    configured = {str(item) for item in (user.permissions or []) if str(item) in FEATURES}
    if user.role == "admin":
        configured.add("admin_users")
    return [item for item in FEATURES if item in configured]


def create_access_token(user: FrontendUser) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({
        "sub": str(user.id), "username": user.username, "role": user.role,
        "ver": int(user.token_version or 1), "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=JWT_LIFETIME_HOURS)).timestamp()), "jti": secrets.token_hex(12),
    }, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Sign in is required.")
    return token


def authenticate_token(token: str, db: Session) -> FrontendUser:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = int(payload["sub"])
    except HTTPException:
        raise
    except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="The session is invalid or expired.") from exc
    user = db.query(FrontendUser).filter(FrontendUser.id == user_id).first()
    if not user or not user.is_active or int(payload.get("ver", 0)) != int(user.token_version or 1):
        raise HTTPException(status_code=401, detail="The session is no longer active.")
    return user


def authenticate_request(request: Request, db: Session) -> FrontendUser:
    return authenticate_token(_bearer_token(request), db)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> FrontendUser:
    return authenticate_request(request, db)


def require_permission(permission: str) -> Callable:
    def dependency(user: FrontendUser = Depends(get_current_user)) -> FrontendUser:
        if permission not in resolved_permissions(user):
            raise HTTPException(status_code=403, detail=f"Access to {permission.replace('_', ' ')} is not allowed.")
        return user
    return dependency


def require_admin(user: FrontendUser = Depends(get_current_user)) -> FrontendUser:
    if user.role != "admin" and not (user.role == "superuser" and user.managed_by_user_id is None):
        raise HTTPException(status_code=403, detail="Administrator access is required.")
    return user


def can_manage(actor: FrontendUser, target: FrontendUser) -> bool:
    if actor.role == "superuser" and actor.managed_by_user_id is None:
        return actor.id != target.id
    return actor.role == "admin" and target.role in {"user", "superuser"} and target.managed_by_user_id == actor.id


def owned_client_ids(db: Session, user: FrontendUser) -> list[str]:
    from models.user import User
    return [str(item) for item in db.query(User.client_id).filter(User.owner_user_id == user.id).scalars().all()]


def require_owned_client(db: Session, user: FrontendUser, client_id: str):
    from models.user import User
    account = db.query(User).filter(User.client_id == client_id, User.owner_user_id == user.id).first()
    if not account:
        raise HTTPException(status_code=404, detail="TMS account was not found.")
    return account


def normalized_permissions(values: Iterable[str] | None, role: str = "user") -> list[str]:
    selected = {str(value) for value in (values or []) if str(value) in FEATURES}
    if role == "superuser":
        selected = set(FEATURES)
    elif role == "admin":
        selected.add("admin_users")
    return [item for item in FEATURES if item in selected]
