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


def ensure_read_session(db) -> None:
    """Reset an aborted transaction so the next SELECT can run (Postgres requirement)."""
    try:
        db.rollback()
    except Exception:
        pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        ensure_read_session(db)
        raise
    finally:
        db.close()

def ensure_performance_indexes():
    statements = [
        "CREATE INDEX IF NOT EXISTS ix_logged_in_users_status_last_updated ON logged_in_users (status, last_updated)",
        "ALTER TABLE logged_in_users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMP",
        "ALTER TABLE logged_in_users ADD COLUMN IF NOT EXISTS collateral JSON",
        "ALTER TABLE logged_in_users ADD COLUMN IF NOT EXISTS collateral_updated_at TIMESTAMP",
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
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS reference_ltp FLOAT",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS trigger_price FLOAT",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS reference_ltp_captured_at TIMESTAMP",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS drop_percent FLOAT",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS emergency_execution BOOLEAN DEFAULT FALSE",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS user_allocation JSON",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS last_checked_ltp FLOAT",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS last_checked_at TIMESTAMP",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS below_stop_loss_check_count INTEGER DEFAULT 0",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS consecutive_drop_count INTEGER DEFAULT 0",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS runner_lock_id VARCHAR",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS scan_price_history JSON",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS scan_volume_history JSON",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS strategy_config JSON",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS tms_scan_count INTEGER DEFAULT 0",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS nepse_alpha_scan_count INTEGER DEFAULT 0",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS nepse_alpha_last_source VARCHAR",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS nepse_alpha_last_fetched_at TIMESTAMP",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW()",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW()",
        "CREATE INDEX IF NOT EXISTS ix_scheduled_orders_strategy_status ON scheduled_orders (strategy_type, status)",
        "CREATE INDEX IF NOT EXISTS ix_order_logs_client_script ON order_logs (client_id, script_name)",
        "CREATE INDEX IF NOT EXISTS ix_order_status_logs_timestamp_client_script ON order_status_logs (timestamp, client_id, script_name)",
        """CREATE TABLE IF NOT EXISTS tradebook_history_cache (
            id SERIAL PRIMARY KEY,
            client_id VARCHAR NOT NULL,
            trade_uid VARCHAR NOT NULL UNIQUE,
            symbol VARCHAR,
            side VARCHAR,
            trade_date DATE,
            trade_price FLOAT,
            quantity FLOAT,
            raw_row JSON,
            fetched_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS ix_tradebook_history_cache_client_date ON tradebook_history_cache (client_id, trade_date)",
        "CREATE INDEX IF NOT EXISTS ix_tradebook_history_cache_client_symbol ON tradebook_history_cache (client_id, symbol)",
        """CREATE TABLE IF NOT EXISTS dp_holdings_cache (
            client_id VARCHAR PRIMARY KEY,
            holdings_json JSON NOT NULL,
            source VARCHAR,
            market_phase VARCHAR,
            refreshed_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS ix_dp_holdings_cache_refreshed_at ON dp_holdings_cache (refreshed_at DESC)",
        """CREATE TABLE IF NOT EXISTS tradebook_history_refreshes (
            id SERIAL PRIMARY KEY,
            client_id VARCHAR NOT NULL,
            from_date DATE NOT NULL,
            to_date DATE NOT NULL,
            refreshed_at TIMESTAMP DEFAULT NOW(),
            CONSTRAINT uq_tradebook_history_refresh UNIQUE (client_id, from_date, to_date)
        )""",
        "CREATE INDEX IF NOT EXISTS ix_tradebook_history_refreshes_client_range ON tradebook_history_refreshes (client_id, from_date, to_date)",
        "ALTER TABLE order_status_logs ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP",
        """CREATE TABLE IF NOT EXISTS portal_settings (
            id INTEGER PRIMARY KEY,
            settings_json TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        "ALTER TABLE order_status_logs ADD COLUMN IF NOT EXISTS strategy_type VARCHAR",
        "ALTER TABLE order_status_logs ADD COLUMN IF NOT EXISTS requested_price FLOAT",
        "ALTER TABLE order_status_logs ADD COLUMN IF NOT EXISTS execution_price FLOAT",
        "ALTER TABLE order_status_logs ADD COLUMN IF NOT EXISTS execution_price_source VARCHAR",
        "ALTER TABLE order_status_logs ADD COLUMN IF NOT EXISTS execution_reason VARCHAR",
        "ALTER TABLE order_status_logs ADD COLUMN IF NOT EXISTS stop_loss_price FLOAT",
        "ALTER TABLE order_status_logs ADD COLUMN IF NOT EXISTS average_buy_price FLOAT",
        "ALTER TABLE order_status_logs ADD COLUMN IF NOT EXISTS max_allowed_slippage_percent FLOAT",
        "CREATE TABLE IF NOT EXISTS strategy_plans (id SERIAL PRIMARY KEY, user_id VARCHAR NOT NULL, client_id VARCHAR NOT NULL, name VARCHAR NOT NULL, side VARCHAR NOT NULL, strategy_type VARCHAR NOT NULL, rule_source VARCHAR NOT NULL DEFAULT 'custom_query', query_text TEXT, query_version INTEGER DEFAULT 1, compiled_plan JSON, status VARCHAR DEFAULT 'draft', execution_mode VARCHAR DEFAULT 'paper', portfolio_limits JSON, form_symbol VARCHAR, created_at TIMESTAMP DEFAULT NOW(), updated_at TIMESTAMP DEFAULT NOW(), activated_at TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS strategy_rules (id SERIAL PRIMARY KEY, plan_id INTEGER NOT NULL, rule_name VARCHAR NOT NULL, priority INTEGER DEFAULT 0, rule_ast JSON, order_config JSON, confirmation_config JSON, execution_config JSON, risk_config JSON, created_at TIMESTAMP DEFAULT NOW(), updated_at TIMESTAMP DEFAULT NOW())",
        "CREATE TABLE IF NOT EXISTS strategy_targets (id SERIAL PRIMARY KEY, rule_id INTEGER NOT NULL, plan_id INTEGER NOT NULL, symbol VARCHAR NOT NULL, status VARCHAR DEFAULT 'MONITORING', warning_codes JSON, last_evaluation_status VARCHAR, last_match_at TIMESTAMP, execution_count INTEGER DEFAULT 0, cooldown_until TIMESTAMP, target_state JSON, created_at TIMESTAMP DEFAULT NOW(), updated_at TIMESTAMP DEFAULT NOW())",
        "CREATE TABLE IF NOT EXISTS rule_evaluations (id SERIAL PRIMARY KEY, plan_id INTEGER NOT NULL, rule_id INTEGER, target_id INTEGER, symbol VARCHAR NOT NULL, snapshot_id VARCHAR, rule_version INTEGER DEFAULT 1, matched BOOLEAN DEFAULT FALSE, status VARCHAR, condition_results JSON, warning_codes JSON, evaluated_at TIMESTAMP DEFAULT NOW())",
        "CREATE TABLE IF NOT EXISTS execution_batches (id SERIAL PRIMARY KEY, plan_id INTEGER NOT NULL, evaluation_cycle_id VARCHAR, side VARCHAR, status VARCHAR DEFAULT 'PLANNED', total_candidates INTEGER DEFAULT 0, total_intents INTEGER DEFAULT 0, submitted_count INTEGER DEFAULT 0, skipped_count INTEGER DEFAULT 0, failed_count INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT NOW(), completed_at TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS order_intents (id SERIAL PRIMARY KEY, batch_id INTEGER, plan_id INTEGER NOT NULL, rule_id INTEGER, symbol VARCHAR NOT NULL, side VARCHAR NOT NULL, requested_quantity INTEGER, effective_quantity INTEGER, requested_amount FLOAT, order_price FLOAT, max_slippage_pct FLOAT, idempotency_key VARCHAR NOT NULL UNIQUE, status VARCHAR DEFAULT 'PENDING', broker_order_id VARCHAR, request_payload JSON, response_payload JSON, created_at TIMESTAMP DEFAULT NOW(), submitted_at TIMESTAMP, confirmed_at TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS strategy_warnings (id SERIAL PRIMARY KEY, plan_id INTEGER NOT NULL, rule_id INTEGER, symbol VARCHAR, warning_code VARCHAR NOT NULL, message TEXT NOT NULL, is_acknowledged BOOLEAN DEFAULT FALSE, created_at TIMESTAMP DEFAULT NOW())",
        "CREATE INDEX IF NOT EXISTS ix_strategy_plans_client_status ON strategy_plans (client_id, status)",
        "CREATE INDEX IF NOT EXISTS ix_strategy_targets_plan_symbol ON strategy_targets (plan_id, symbol)",
        """CREATE TABLE IF NOT EXISTS scheduled_field_references (
            id SERIAL PRIMARY KEY,
            scheduled_order_id INTEGER NOT NULL REFERENCES scheduled_orders(order_id) ON DELETE CASCADE,
            rule_name VARCHAR NOT NULL,
            symbol VARCHAR NOT NULL,
            field_key VARCHAR NOT NULL,
            field_type VARCHAR NOT NULL,
            numeric_value FLOAT,
            text_value VARCHAR,
            boolean_value BOOLEAN,
            captured_at TIMESTAMP DEFAULT NOW(),
            source VARCHAR,
            refreshed_at TIMESTAMP,
            refresh_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),
            CONSTRAINT uq_scheduled_field_reference UNIQUE (scheduled_order_id, rule_name, symbol, field_key)
        )""",
        "CREATE INDEX IF NOT EXISTS ix_scheduled_field_references_order ON scheduled_field_references (scheduled_order_id)",
        """CREATE TABLE IF NOT EXISTS scheduled_field_reference_audits (
            id SERIAL PRIMARY KEY,
            reference_id INTEGER NOT NULL REFERENCES scheduled_field_references(id) ON DELETE CASCADE,
            previous_numeric FLOAT,
            previous_text VARCHAR,
            previous_boolean BOOLEAN,
            new_numeric FLOAT,
            new_text VARCHAR,
            new_boolean BOOLEAN,
            refreshed_at TIMESTAMP DEFAULT NOW(),
            refreshed_by VARCHAR
        )""",
        "CREATE INDEX IF NOT EXISTS ix_scheduled_field_reference_audits_ref ON scheduled_field_reference_audits (reference_id)",
        """CREATE TABLE IF NOT EXISTS merolagani_daily_snapshots (
            id SERIAL PRIMARY KEY,
            snapshot_date DATE NOT NULL UNIQUE,
            symbol_count INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS merolagani_daily_stocks (
            id SERIAL PRIMARY KEY,
            snapshot_date DATE NOT NULL,
            symbol VARCHAR NOT NULL,
            data JSON NOT NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            CONSTRAINT uq_merolagani_daily_stock UNIQUE (snapshot_date, symbol)
        )""",
        "CREATE INDEX IF NOT EXISTS ix_merolagani_daily_stocks_date ON merolagani_daily_stocks (snapshot_date)",
        "CREATE INDEX IF NOT EXISTS ix_merolagani_daily_stocks_symbol ON merolagani_daily_stocks (symbol)",
        """CREATE TABLE IF NOT EXISTS market_symbol_registry (
            symbol VARCHAR PRIMARY KEY,
            first_seen_date DATE NOT NULL,
            last_seen_date DATE NOT NULL,
            is_watchlist BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS market_screener_cache (
            symbol VARCHAR PRIMARY KEY,
            merolagani_data JSON,
            nepse_alpha_data JSON,
            combined_data JSON,
            merolagani_fetched_at TIMESTAMP,
            nepse_alpha_fetched_at TIMESTAMP,
            updated_at TIMESTAMP DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS market_data_refresh_log (
            id SERIAL PRIMARY KEY,
            refresh_type VARCHAR NOT NULL,
            status VARCHAR NOT NULL,
            symbol_count INTEGER,
            message TEXT,
            started_at TIMESTAMP,
            completed_at TIMESTAMP DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS ix_market_data_refresh_log_type ON market_data_refresh_log (refresh_type, completed_at DESC)",
        """CREATE TABLE IF NOT EXISTS market_screen_presets (
            id SERIAL PRIMARY KEY,
            preset_code VARCHAR(100) NOT NULL UNIQUE,
            preset_name VARCHAR(150) NOT NULL,
            category VARCHAR(20) NOT NULL CHECK (category IN ('INVESTOR', 'TRADER')),
            risk_level VARCHAR(20) NOT NULL,
            time_horizon VARCHAR(100),
            description TEXT NOT NULL,
            query_sql TEXT NOT NULL,
            display_order INTEGER NOT NULL DEFAULT 0,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS ix_market_screen_presets_category ON market_screen_presets (category, display_order)",
    ]
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
