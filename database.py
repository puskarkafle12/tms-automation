from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from config.db_config import DATABASE_URL
from sqlalchemy.ext.declarative import declarative_base
import os

engine = create_engine(
    DATABASE_URL,
    echo=os.getenv("SQL_ECHO", "false").lower() == "true",
    pool_size=50,
    max_overflow=20,
    pool_timeout=60,
    pool_pre_ping=True,
)
# Set up session factory with tracking setting
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()  # Added for model declaration
def get_db_session():
    """Return a DB session for use outside FastAPI dependency injection."""
    return SessionLocal()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def ensure_performance_indexes():
    statements = [
        "CREATE INDEX IF NOT EXISTS ix_logged_in_users_status_last_updated ON logged_in_users (status, last_updated)",
        "CREATE INDEX IF NOT EXISTS ix_scheduled_orders_status_client_script ON scheduled_orders (status, client_id, script_name)",
        "CREATE INDEX IF NOT EXISTS ix_order_logs_client_script ON order_logs (client_id, script_name)",
        "CREATE INDEX IF NOT EXISTS ix_order_status_logs_timestamp_client_script ON order_status_logs (timestamp, client_id, script_name)",
    ]
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
