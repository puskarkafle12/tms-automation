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
        "ALTER TABLE logged_in_users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMP",
        "CREATE INDEX IF NOT EXISTS ix_scheduled_orders_status_client_script ON scheduled_orders (status, client_id, script_name)",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS strategy_type VARCHAR DEFAULT 'Fixed Price'",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS side VARCHAR",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS symbol VARCHAR",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS company_name VARCHAR",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS remaining_quantity INTEGER",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS limit_price FLOAT",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS stop_loss_price FLOAT",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS stop_limit_price FLOAT",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS book_profit_price FLOAT",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS profit_target_price FLOAT",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS trailing_drop_percent FLOAT",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS stable_band_percent FLOAT",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS minimum_wait_minutes INTEGER",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS consecutive_drop_checks INTEGER",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS activation_price FLOAT",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS target_reached BOOLEAN DEFAULT FALSE",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS target_reached_at TIMESTAMP",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS highest_tracked_price FLOAT",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS highest_tracked_at TIMESTAMP",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS protected_price FLOAT",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS average_buy_price FLOAT",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS partial_legs JSON",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS executed_legs JSON",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS execution_price FLOAT",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS execution_price_source VARCHAR",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS execution_reason VARCHAR",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS executed_at TIMESTAMP",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS cancelled_reason VARCHAR",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS failed_reason VARCHAR",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS expiry_time TIMESTAMP",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS expiry_action VARCHAR",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS max_allowed_slippage_percent FLOAT",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS emergency_execution BOOLEAN DEFAULT FALSE",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS user_allocation JSON",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS last_checked_ltp FLOAT",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS last_checked_at TIMESTAMP",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS below_stop_loss_check_count INTEGER DEFAULT 0",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS consecutive_drop_count INTEGER DEFAULT 0",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS runner_lock_id VARCHAR",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW()",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW()",
        "CREATE INDEX IF NOT EXISTS ix_scheduled_orders_strategy_status ON scheduled_orders (strategy_type, status)",
        "CREATE INDEX IF NOT EXISTS ix_order_logs_client_script ON order_logs (client_id, script_name)",
        "CREATE INDEX IF NOT EXISTS ix_order_status_logs_timestamp_client_script ON order_status_logs (timestamp, client_id, script_name)",
    ]
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
