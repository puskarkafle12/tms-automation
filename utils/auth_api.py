"""Authentication, signup CAPTCHA, and delegated user administration API."""

from __future__ import annotations

import hashlib
import base64
from io import BytesIO
import json
import os
import random
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db
from models.frontend_user import FrontendUser
from utils.auth import (
    DEFAULT_USER_PERMISSIONS, FEATURES, JWT_SECRET, can_manage, create_access_token,
    get_current_user, hash_password, normalized_permissions, require_admin,
    resolved_permissions, verify_password,
)

router = APIRouter(prefix="/api", tags=["authentication"])
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.-]{3,40}$")


class LoginBody(BaseModel):
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=1, max_length=200)


class SignupBody(LoginBody):
    password: str = Field(min_length=10, max_length=200)
    captcha_id: str = Field(min_length=20, max_length=100)
    captcha_answer: str = Field(min_length=1, max_length=20)

    @field_validator("username")
    @classmethod
    def valid_username(cls, value: str) -> str:
        clean = value.strip()
        if not USERNAME_RE.fullmatch(clean):
            raise ValueError("Use 3–40 letters, numbers, dots, dashes, or underscores.")
        return clean

    @field_validator("password")
    @classmethod
    def strong_password(cls, value: str) -> str:
        if not re.search(r"[a-z]", value) or not re.search(r"[A-Z]", value) or not re.search(r"\d", value):
            raise ValueError("Use at least 10 characters with uppercase, lowercase, and a number.")
        return value


class ChangePasswordBody(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


class AdminUserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=8, max_length=200)
    role: Literal["user", "admin", "superuser"] = "user"
    permissions: Optional[list[str]] = None
    managed_by_user_id: Optional[int] = None


class AdminUserUpdate(BaseModel):
    role: Optional[Literal["user", "admin", "superuser"]] = None
    permissions: Optional[list[str]] = None
    is_active: Optional[bool] = None
    managed_by_user_id: Optional[int] = None


class ResetPasswordBody(BaseModel):
    new_password: str = Field(min_length=8, max_length=200)


def _serialize(user: FrontendUser) -> dict[str, Any]:
    return {
        "id": user.id, "username": user.username, "role": user.role,
        "permissions": resolved_permissions(user), "configured_permissions": list(user.permissions or []),
        "managed_by_user_id": user.managed_by_user_id, "is_active": bool(user.is_active),
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "updated_at": user.updated_at.isoformat() if user.updated_at else None,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
    }


def _user_workspace_summary(db: Session, user_id: int) -> dict[str, int]:
    row = db.execute(text("""
        SELECT
          (SELECT COUNT(*) FROM users WHERE owner_user_id=:id) AS tms_accounts,
          (SELECT COUNT(*) FROM scheduled_orders WHERE owner_user_id=:id) AS scheduled_orders,
          (SELECT COUNT(*) FROM order_status_logs WHERE owner_user_id=:id AND deleted_at IS NULL) AS order_logs,
          (SELECT COUNT(*) FROM backtest_runs WHERE owner_id=:owner AND deleted_at IS NULL AND archived_at IS NULL) AS backtest_runs
    """), {"id": user_id, "owner": str(user_id)}).mappings().one()
    return {key: int(value or 0) for key, value in row.items()}


def _audit(db: Session, *, action: str, actor_id: int | None, target_id: int | None,
           request: Request, before: Any = None, after: Any = None) -> None:
    db.execute(text("""
        INSERT INTO frontend_user_audit_log
            (actor_user_id,target_user_id,action,before_data,after_data,ip_address,user_agent)
        VALUES (:actor,:target,:action,CAST(:before AS JSONB),CAST(:after AS JSONB),:ip,:agent)
    """), {
        "actor": actor_id, "target": target_id, "action": action,
        "before": json.dumps(before) if before is not None else None,
        "after": json.dumps(after) if after is not None else None,
        "ip": request.client.host if request.client else None,
        "agent": request.headers.get("user-agent", "")[:500],
    })


def _captcha_digest(challenge_id: str, answer: str, nonce: str) -> str:
    normalized = answer.strip().lower()
    return hashlib.sha256(f"{challenge_id}:{normalized}:{nonce}:{JWT_SECRET}".encode()).hexdigest()


def _consume_captcha(db: Session, challenge_id: str, answer: str) -> None:
    row = db.execute(text("""
        SELECT challenge_id,answer_digest,nonce,expires_at,attempts,max_attempts,consumed_at
        FROM signup_captcha_challenges WHERE challenge_id=:challenge_id FOR UPDATE
    """), {"challenge_id": challenge_id}).mappings().first()
    now = datetime.now(timezone.utc)
    if not row or row["consumed_at"] or row["expires_at"].replace(tzinfo=timezone.utc) <= now:
        raise HTTPException(status_code=400, detail="CAPTCHA expired. Request a new challenge.")
    attempts = int(row["attempts"] or 0) + 1
    db.execute(text("UPDATE signup_captcha_challenges SET attempts=:attempts WHERE challenge_id=:id"),
               {"attempts": attempts, "id": challenge_id})
    expected = _captcha_digest(challenge_id, answer, row["nonce"])
    if attempts > int(row["max_attempts"] or 3) or not secrets.compare_digest(expected, row["answer_digest"]):
        raise HTTPException(status_code=400, detail="CAPTCHA answer is incorrect.")
    db.execute(text("UPDATE signup_captcha_challenges SET consumed_at=NOW() WHERE challenge_id=:id"), {"id": challenge_id})


def _captcha_image(answer: str) -> str:
    """Render a noisy, per-character rotated challenge without exposing its text."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    rng = random.SystemRandom()
    image = Image.new("RGB", (250, 84), (241, 247, 250))
    draw = ImageDraw.Draw(image)
    for _ in range(9):
        color = (rng.randint(80, 180), rng.randint(100, 190), rng.randint(120, 205))
        draw.line((rng.randint(-20, 250), rng.randint(0, 84), rng.randint(0, 270), rng.randint(0, 84)), fill=color, width=rng.randint(1, 3))
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    try:
        font = ImageFont.truetype(font_path, 46)
    except OSError:
        font = ImageFont.load_default()
    for index, character in enumerate(answer):
        tile = Image.new("RGBA", (48, 66), (255, 255, 255, 0))
        tile_draw = ImageDraw.Draw(tile)
        tile_draw.text((7, 3), character, font=font, fill=(rng.randint(20, 65), rng.randint(45, 90), rng.randint(65, 115), 255))
        tile = tile.rotate(rng.randint(-22, 22), resample=Image.Resampling.BICUBIC, expand=False)
        image.paste(tile, (10 + index * 39, rng.randint(7, 15)), tile)
    draw = ImageDraw.Draw(image)
    for _ in range(240):
        draw.point((rng.randrange(250), rng.randrange(84)), fill=(rng.randrange(70, 220), rng.randrange(70, 220), rng.randrange(70, 220)))
    image = image.filter(ImageFilter.GaussianBlur(radius=0.35))
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


@router.get("/auth/captcha")
def create_captcha(request: Request, db: Session = Depends(get_db)):
    request_ip = request.client.host if request.client else "unknown"
    recent = int(db.execute(text("""
        SELECT COUNT(*) FROM signup_captcha_challenges
        WHERE request_ip=:request_ip AND created_at > NOW()-INTERVAL '15 minutes'
    """), {"request_ip": request_ip}).scalar() or 0)
    if recent >= 15:
        raise HTTPException(status_code=429, detail="Too many CAPTCHA requests. Please wait a few minutes and try again.")
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    answer = "".join(secrets.choice(alphabet) for _ in range(6))
    challenge_id, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(18)
    db.execute(text("""
        INSERT INTO signup_captcha_challenges
            (challenge_id,answer_digest,nonce,expires_at,max_attempts,request_ip)
        VALUES (:id,:digest,:nonce,NOW()+INTERVAL '5 minutes',3,:request_ip)
    """), {"id": challenge_id, "digest": _captcha_digest(challenge_id, answer, nonce), "nonce": nonce, "request_ip": request_ip})
    db.execute(text("DELETE FROM signup_captcha_challenges WHERE expires_at < NOW()-INTERVAL '1 day'"))
    db.commit()
    return {
        "captcha_id": challenge_id, "image_data_url": _captcha_image(answer),
        "prompt": "Enter the six characters shown", "expires_in_seconds": 300,
    }


@router.post("/auth/signup", status_code=201)
def signup(body: SignupBody, request: Request, db: Session = Depends(get_db)):
    username = body.username.strip()
    _consume_captcha(db, body.captcha_id, body.captcha_answer)
    if db.query(FrontendUser).filter(FrontendUser.username == username).first():
        raise HTTPException(status_code=409, detail="That username is already in use.")
    default_admin = db.query(FrontendUser).filter(
        FrontendUser.role == "admin", FrontendUser.is_active.is_(True)
    ).order_by(FrontendUser.id).first()
    user = FrontendUser(
        username=username, password=hash_password(body.password), role="user",
        permissions=list(DEFAULT_USER_PERMISSIONS),
        managed_by_user_id=default_admin.id if default_admin else None,
        is_active=True, token_version=1,
    )
    db.add(user); db.flush()
    _audit(db, action="signup", actor_id=user.id, target_id=user.id, request=request, after=_serialize(user))
    db.commit(); db.refresh(user)
    return {"message": "Account created successfully. Your private workspace is ready.", "access_token": create_access_token(user), "user": _serialize(user)}


@router.post("/auth/login")
def login(body: LoginBody, request: Request, db: Session = Depends(get_db)):
    user = db.query(FrontendUser).filter(FrontendUser.username == body.username.strip()).first()
    if not user or not user.is_active or not verify_password(body.password, user.password):
        if user:
            _audit(db, action="login_failed", actor_id=user.id, target_id=user.id, request=request)
            db.commit()
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    if not str(user.password).startswith("pbkdf2_sha256$"):
        user.password = hash_password(body.password)
    user.last_login_at = datetime.utcnow()
    _audit(db, action="login", actor_id=user.id, target_id=user.id, request=request)
    db.commit(); db.refresh(user)
    return {"message": "Login successful", "user_id": user.id, "access_token": create_access_token(user), "user": _serialize(user)}


@router.get("/auth/me")
def me(user: FrontendUser = Depends(get_current_user)):
    # Sliding session: each successful check issues a fresh token so active
    # users stay signed in without re-entering credentials.
    return {
        "user": _serialize(user),
        "features": list(FEATURES),
        "access_token": create_access_token(user),
    }


@router.post("/auth/logout")
def logout(request: Request, user: FrontendUser = Depends(get_current_user), db: Session = Depends(get_db)):
    user.token_version = int(user.token_version or 1) + 1
    _audit(db, action="logout_all", actor_id=user.id, target_id=user.id, request=request)
    db.commit()
    return {"message": "Signed out"}


@router.post("/auth/change-password")
def change_password(body: ChangePasswordBody, request: Request, user: FrontendUser = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.password):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    user.password = hash_password(body.new_password); user.token_version = int(user.token_version or 1) + 1
    _audit(db, action="password_changed", actor_id=user.id, target_id=user.id, request=request)
    db.commit()
    return {"message": "Password changed. Sign in again."}


@router.get("/admin/users")
def list_users(actor: FrontendUser = Depends(require_admin), db: Session = Depends(get_db)):
    query = db.query(FrontendUser)
    if actor.role != "superuser" or actor.managed_by_user_id is not None:
        query = query.filter(FrontendUser.managed_by_user_id == actor.id)
    items = []
    for managed_user in query.order_by(FrontendUser.username).all():
        item = _serialize(managed_user)
        item["workspace_summary"] = _user_workspace_summary(db, managed_user.id)
        items.append(item)
    return {"items": items, "features": list(FEATURES)}


@router.post("/admin/users", status_code=201)
def create_user(body: AdminUserCreate, request: Request, actor: FrontendUser = Depends(require_admin), db: Session = Depends(get_db)):
    username = body.username.strip()
    if not USERNAME_RE.fullmatch(username):
        raise HTTPException(status_code=400, detail="Username format is invalid.")
    if db.query(FrontendUser).filter(FrontendUser.username == username).first():
        raise HTTPException(status_code=409, detail="That username is already in use.")
    if body.role == "admin" and (actor.role != "superuser" or actor.managed_by_user_id is not None):
        raise HTTPException(status_code=403, detail="Only a superuser can create another administrator.")
    is_root = actor.role == "superuser" and actor.managed_by_user_id is None
    manager_id = body.managed_by_user_id if is_root else actor.id
    user = FrontendUser(
        username=username, password=hash_password(body.password), role=body.role,
        permissions=normalized_permissions(body.permissions or DEFAULT_USER_PERMISSIONS, body.role),
        managed_by_user_id=None if body.role == "superuser" and is_root else manager_id,
        is_active=True, token_version=1,
    )
    db.add(user); db.flush()
    _audit(db, action="user_created", actor_id=actor.id, target_id=user.id, request=request, after=_serialize(user))
    db.commit(); db.refresh(user)
    return {"user": _serialize(user)}


def _managed_target(db: Session, actor: FrontendUser, user_id: int) -> FrontendUser:
    target = db.query(FrontendUser).filter(FrontendUser.id == user_id).first()
    if not target or not can_manage(actor, target):
        raise HTTPException(status_code=404, detail="Managed user was not found.")
    return target


@router.patch("/admin/users/{user_id}")
def update_user(user_id: int, body: AdminUserUpdate, request: Request, actor: FrontendUser = Depends(require_admin), db: Session = Depends(get_db)):
    target = _managed_target(db, actor, user_id); before = _serialize(target)
    next_role = body.role or target.role
    is_root = actor.role == "superuser" and actor.managed_by_user_id is None
    if next_role == "admin" and not is_root:
        raise HTTPException(status_code=403, detail="Only a superuser can assign the administrator role.")
    if body.role is not None:
        target.role = body.role
    if body.permissions is not None:
        target.permissions = normalized_permissions(body.permissions, next_role)
    if body.is_active is not None:
        target.is_active = body.is_active
    if body.managed_by_user_id is not None and is_root:
        target.managed_by_user_id = body.managed_by_user_id
    if next_role == "superuser" and is_root:
        target.managed_by_user_id = None
    target.token_version = int(target.token_version or 1) + 1
    _audit(db, action="user_updated", actor_id=actor.id, target_id=target.id, request=request, before=before, after=_serialize(target))
    db.commit(); db.refresh(target)
    return {"user": _serialize(target)}


@router.post("/admin/users/{user_id}/reset-password")
def reset_password(user_id: int, body: ResetPasswordBody, request: Request, actor: FrontendUser = Depends(require_admin), db: Session = Depends(get_db)):
    target = _managed_target(db, actor, user_id)
    target.password = hash_password(body.new_password); target.token_version = int(target.token_version or 1) + 1
    _audit(db, action="password_reset", actor_id=actor.id, target_id=target.id, request=request)
    db.commit()
    return {"message": "Password reset. Existing sessions were revoked."}


@router.get("/admin/users/{user_id}/activity")
def user_activity(user_id: int, actor: FrontendUser = Depends(require_admin), db: Session = Depends(get_db)):
    target = _managed_target(db, actor, user_id)
    rows = db.execute(text("""
        SELECT id,actor_user_id,target_user_id,action,before_data,after_data,ip_address,created_at
        FROM frontend_user_audit_log
        WHERE actor_user_id=:id OR target_user_id=:id ORDER BY created_at DESC LIMIT 200
    """), {"id": target.id}).mappings().all()
    return {"items": [{**dict(row), "created_at": row["created_at"].isoformat()} for row in rows]}
