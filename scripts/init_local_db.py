"""Create all tables and seed the default frontend login user."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database import Base, engine, SessionLocal, ensure_performance_indexes
from models.frontend_user import FrontendUser
from models import frontend_user, logged_in_user, order_log, order_status_log, scheduled_order, tms_password_backup, user  # noqa: F401
from utils.auth import DEFAULT_USER_PERMISSIONS, hash_password, verify_password


def main() -> None:
    seed_user = os.getenv("FRONTEND_SEED_USER", "admin")
    seed_password = os.getenv("FRONTEND_SEED_PASSWORD", "nepse2026")
    admin_user = os.getenv("FRONTEND_ADMIN_USER", "manager")
    admin_password = os.getenv("FRONTEND_ADMIN_PASSWORD", "manager2026")
    normal_user = os.getenv("FRONTEND_NORMAL_USER", "user")
    normal_password = os.getenv("FRONTEND_NORMAL_PASSWORD", "user2026")

    Base.metadata.create_all(bind=engine)
    ensure_performance_indexes()
    db = SessionLocal()
    try:
        existing = db.query(FrontendUser).filter(FrontendUser.username == seed_user).first()
        if not existing:
            existing = FrontendUser(username=seed_user, password=hash_password(seed_password), role="superuser", permissions=[])
            db.add(existing)
            print(f"Seeded frontend user: {seed_user}")
            print("Use FRONTEND_SEED_USER and FRONTEND_SEED_PASSWORD in .env to customize.")
        else:
            if not str(existing.password).startswith("pbkdf2_sha256$"):
                # Preserve an existing legacy password while upgrading its storage.
                existing.password = hash_password(str(existing.password))
            if not verify_password(seed_password, str(existing.password)):
                # Keep the seed login in sync with FRONTEND_SEED_PASSWORD so a
                # fresh pull + restart always accepts the configured credentials.
                # Do not bump token_version here — that would force every open
                # browser session to sign in again after a routine restart.
                existing.password = hash_password(seed_password)
                print(f"Reset password for seed user: {seed_user}")
            existing.role = "superuser"
            existing.is_active = True
            print(f"Frontend user already exists: {seed_user}")
        db.flush()
        delegated_admin = db.query(FrontendUser).filter(FrontendUser.username == admin_user).first()
        if not delegated_admin and admin_user != seed_user:
            delegated_admin = FrontendUser(
                username=admin_user, password=hash_password(admin_password), role="admin",
                permissions=list(DEFAULT_USER_PERMISSIONS), is_active=True,
            )
            db.add(delegated_admin); db.flush()
            print(f"Seeded delegated admin: {admin_user}")
        elif delegated_admin and admin_password != "admin" and verify_password("admin", str(delegated_admin.password)):
            delegated_admin.password = hash_password(admin_password)
            delegated_admin.token_version = int(delegated_admin.token_version or 1) + 1
        standard = db.query(FrontendUser).filter(FrontendUser.username == normal_user).first()
        if not standard and normal_user not in {seed_user, admin_user}:
            standard = FrontendUser(
                username=normal_user, password=hash_password(normal_password), role="user",
                permissions=list(DEFAULT_USER_PERMISSIONS),
                managed_by_user_id=delegated_admin.id if delegated_admin else None, is_active=True,
            )
            db.add(standard)
            print(f"Seeded normal user: {normal_user}")
        elif standard and normal_password != "user1234" and verify_password("user1234", str(standard.password)):
            standard.password = hash_password(normal_password)
            standard.token_version = int(standard.token_version or 1) + 1
        db.commit()
        # A fresh database has no seed owner during the first migration pass.
        # Re-run idempotent backfills now that the superuser exists.
        ensure_performance_indexes()
        print("Database tables are ready.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
