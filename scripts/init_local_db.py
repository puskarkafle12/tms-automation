"""Create all tables and seed the default frontend login user."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database import Base, engine, SessionLocal
from models.frontend_user import FrontendUser
from models import frontend_user, logged_in_user, order_log, order_status_log, scheduled_order, tms_password_backup, user  # noqa: F401


def main() -> None:
    seed_user = os.getenv("FRONTEND_SEED_USER", "admin")
    seed_password = os.getenv("FRONTEND_SEED_PASSWORD", "admin")

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        existing = db.query(FrontendUser).filter(FrontendUser.username == seed_user).first()
        if not existing:
            db.add(FrontendUser(username=seed_user, password=seed_password))
            db.commit()
            print(f"Seeded frontend user: {seed_user}")
            print("Use FRONTEND_SEED_USER and FRONTEND_SEED_PASSWORD in .env to customize.")
        else:
            print(f"Frontend user already exists: {seed_user}")
        print("Database tables are ready.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
