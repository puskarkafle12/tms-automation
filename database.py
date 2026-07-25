from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from config.db_config import DATABASE_URL
from sqlalchemy.ext.declarative import declarative_base
import os

engine = create_engine(
    DATABASE_URL,
    echo=os.getenv("SQL_ECHO", "false").lower() == "true",
    # Keep the bundled PostgreSQL responsive under browser polling and scans.
    # A huge pool turns a request burst into dozens of competing PostgreSQL
    # processes; bounded queues give normal traffic fair access instead.
    pool_size=max(2, int(os.getenv("DB_POOL_SIZE", "10"))),
    max_overflow=max(0, int(os.getenv("DB_MAX_OVERFLOW", "10"))),
    pool_timeout=max(1, int(os.getenv("DB_POOL_TIMEOUT", "10"))),
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
        "ALTER TABLE frontend_users ADD COLUMN IF NOT EXISTS role VARCHAR NOT NULL DEFAULT 'user'",
        "ALTER TABLE frontend_users ADD COLUMN IF NOT EXISTS permissions JSON NOT NULL DEFAULT '[]'::json",
        "ALTER TABLE frontend_users ADD COLUMN IF NOT EXISTS managed_by_user_id INTEGER",
        "ALTER TABLE frontend_users ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE",
        "ALTER TABLE frontend_users ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE frontend_users ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT NOW()",
        "ALTER TABLE frontend_users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT NOW()",
        "ALTER TABLE frontend_users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMP",
        "CREATE INDEX IF NOT EXISTS ix_frontend_users_manager ON frontend_users (managed_by_user_id, role, is_active)",
        """CREATE TABLE IF NOT EXISTS signup_captcha_challenges (
            challenge_id VARCHAR(100) PRIMARY KEY, answer_digest VARCHAR(64) NOT NULL,
            nonce VARCHAR(100) NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 3, expires_at TIMESTAMPTZ NOT NULL,
            consumed_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS ix_signup_captcha_expiry ON signup_captcha_challenges (expires_at)",
        "ALTER TABLE signup_captcha_challenges ADD COLUMN IF NOT EXISTS request_ip VARCHAR(100)",
        "CREATE INDEX IF NOT EXISTS ix_signup_captcha_ip_created ON signup_captcha_challenges (request_ip, created_at DESC)",
        """CREATE TABLE IF NOT EXISTS frontend_user_audit_log (
            id BIGSERIAL PRIMARY KEY,
            actor_user_id INTEGER REFERENCES frontend_users(id) ON DELETE SET NULL,
            target_user_id INTEGER REFERENCES frontend_users(id) ON DELETE SET NULL,
            action VARCHAR(80) NOT NULL, before_data JSONB, after_data JSONB,
            ip_address VARCHAR(100), user_agent VARCHAR(500),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS ix_frontend_user_audit_target ON frontend_user_audit_log (target_user_id, created_at DESC)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS owner_user_id INTEGER",
        "ALTER TABLE scheduled_orders ADD COLUMN IF NOT EXISTS owner_user_id INTEGER",
        "ALTER TABLE order_logs ADD COLUMN IF NOT EXISTS owner_user_id INTEGER",
        "ALTER TABLE order_status_logs ADD COLUMN IF NOT EXISTS owner_user_id INTEGER",
        "CREATE INDEX IF NOT EXISTS ix_users_owner ON users (owner_user_id, client_id)",
        "CREATE INDEX IF NOT EXISTS ix_scheduled_orders_owner ON scheduled_orders (owner_user_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_order_logs_owner ON order_logs (owner_user_id, timestamp DESC)",
        "CREATE INDEX IF NOT EXISTS ix_order_status_logs_owner ON order_status_logs (owner_user_id, timestamp DESC)",
        """CREATE OR REPLACE FUNCTION assign_trading_owner_from_client() RETURNS TRIGGER AS $$
           BEGIN
             IF NEW.owner_user_id IS NULL THEN
               SELECT owner_user_id INTO NEW.owner_user_id FROM users WHERE client_id=NEW.client_id;
             END IF;
             RETURN NEW;
           END; $$ LANGUAGE plpgsql""",
        "DROP TRIGGER IF EXISTS trg_scheduled_orders_owner ON scheduled_orders",
        """CREATE TRIGGER trg_scheduled_orders_owner BEFORE INSERT OR UPDATE OF client_id
           ON scheduled_orders FOR EACH ROW EXECUTE FUNCTION assign_trading_owner_from_client()""",
        "DROP TRIGGER IF EXISTS trg_order_logs_owner ON order_logs",
        """CREATE TRIGGER trg_order_logs_owner BEFORE INSERT OR UPDATE OF client_id
           ON order_logs FOR EACH ROW EXECUTE FUNCTION assign_trading_owner_from_client()""",
        "DROP TRIGGER IF EXISTS trg_order_status_logs_owner ON order_status_logs",
        """CREATE TRIGGER trg_order_status_logs_owner BEFORE INSERT OR UPDATE OF client_id
           ON order_status_logs FOR EACH ROW EXECUTE FUNCTION assign_trading_owner_from_client()""",
        """UPDATE frontend_users SET role='superuser',permissions=CAST(:all_permissions AS JSON),is_active=TRUE
           WHERE username=:seed_username""",
        """UPDATE frontend_users SET permissions=CAST(:default_permissions AS JSON)
           WHERE role='user' AND (permissions IS NULL OR permissions::jsonb='[]'::jsonb)""",
        """UPDATE frontend_users SET managed_by_user_id=(
               SELECT id FROM frontend_users WHERE username=:admin_username AND role='admin'
           ) WHERE role='user' AND managed_by_user_id IS NULL AND username<>:seed_username
             AND EXISTS (SELECT 1 FROM frontend_users WHERE username=:admin_username AND role='admin')""",
        """UPDATE users SET owner_user_id=(SELECT id FROM frontend_users WHERE username=:seed_username)
           WHERE owner_user_id IS NULL""",
        """UPDATE scheduled_orders o SET owner_user_id=u.owner_user_id FROM users u
           WHERE o.owner_user_id IS NULL AND u.client_id=o.client_id""",
        """UPDATE order_logs o SET owner_user_id=u.owner_user_id FROM users u
           WHERE o.owner_user_id IS NULL AND u.client_id=o.client_id""",
        """UPDATE order_status_logs o SET owner_user_id=u.owner_user_id FROM users u
           WHERE o.owner_user_id IS NULL AND u.client_id=o.client_id""",
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
        """CREATE TABLE IF NOT EXISTS market_technical_indicators (
            symbol VARCHAR PRIMARY KEY,
            as_of_date DATE NOT NULL,
            indicators JSONB NOT NULL,
            engine_version VARCHAR(40) NOT NULL,
            bars_count INTEGER NOT NULL,
            history_start DATE,
            history_end DATE,
            latest_volume DOUBLE PRECISION,
            average_volume_20 DOUBLE PRECISION,
            median_volume_20 DOUBLE PRECISION,
            average_turnover_20 DOUBLE PRECISION,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS ix_market_technical_indicators_updated ON market_technical_indicators (updated_at DESC)",
        "ALTER TABLE market_technical_indicators ADD COLUMN IF NOT EXISTS latest_volume DOUBLE PRECISION",
        "ALTER TABLE market_technical_indicators ADD COLUMN IF NOT EXISTS average_volume_20 DOUBLE PRECISION",
        "ALTER TABLE market_technical_indicators ADD COLUMN IF NOT EXISTS median_volume_20 DOUBLE PRECISION",
        "ALTER TABLE market_technical_indicators ADD COLUMN IF NOT EXISTS average_turnover_20 DOUBLE PRECISION",
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
        """CREATE TABLE IF NOT EXISTS backtest_batch_jobs (
            job_id VARCHAR(64) PRIMARY KEY,
            status VARCHAR(20) NOT NULL DEFAULT 'queued',
            parameters JSONB NOT NULL,
            result JSONB,
            error TEXT,
            symbols_completed INTEGER NOT NULL DEFAULT 0,
            symbols_total INTEGER NOT NULL DEFAULT 0,
            combinations_completed INTEGER NOT NULL DEFAULT 0,
            current_symbol VARCHAR(30),
            percent_complete FLOAT NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            deleted_at TIMESTAMPTZ
        )""",
        """CREATE UNIQUE INDEX IF NOT EXISTS uq_backtest_batch_jobs_one_active
            ON backtest_batch_jobs ((1))
            WHERE deleted_at IS NULL AND status IN ('queued', 'running')""",
        "CREATE INDEX IF NOT EXISTS ix_backtest_batch_jobs_created ON backtest_batch_jobs (created_at DESC) WHERE deleted_at IS NULL",
        """CREATE TABLE IF NOT EXISTS backtest_batch_job_symbols (
            job_id VARCHAR(64) NOT NULL REFERENCES backtest_batch_jobs(job_id) ON DELETE CASCADE,
            symbol VARCHAR(30) NOT NULL,
            output JSONB NOT NULL,
            completed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (job_id, symbol)
        )""",
        """CREATE TABLE IF NOT EXISTS market_ohlcv_daily (
            symbol VARCHAR(30) NOT NULL,
            session_date DATE NOT NULL,
            source VARCHAR(40) NOT NULL,
            adjusted BOOLEAN NOT NULL DEFAULT TRUE,
            open_price DOUBLE PRECISION NOT NULL,
            high_price DOUBLE PRECISION NOT NULL,
            low_price DOUBLE PRECISION NOT NULL,
            close_price DOUBLE PRECISION NOT NULL,
            volume DOUBLE PRECISION NOT NULL DEFAULT 0,
            source_timestamp BIGINT,
            quality_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
            content_hash VARCHAR(64) NOT NULL,
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (symbol, session_date, source, adjusted)
        )""",
        "CREATE INDEX IF NOT EXISTS ix_market_ohlcv_daily_date ON market_ohlcv_daily (session_date DESC, symbol)",
        "CREATE INDEX IF NOT EXISTS ix_market_ohlcv_daily_symbol ON market_ohlcv_daily (symbol, session_date)",
        """WITH sessions AS (
               SELECT DISTINCT ON (symbol,trading_date) symbol,trading_date,volume,close_price
               FROM (
                   SELECT symbol,CASE WHEN source_timestamp IS NOT NULL
                                      THEN (to_timestamp(source_timestamp) AT TIME ZONE 'UTC')::date
                                      ELSE session_date END AS trading_date,
                          volume,close_price,fetched_at
                   FROM market_ohlcv_daily WHERE adjusted=TRUE
               ) normalized
               ORDER BY symbol,trading_date,fetched_at DESC
           ), ranked AS (
               SELECT symbol,volume,close_price,
                      ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY trading_date DESC) AS row_number
               FROM sessions
           ), volume_stats AS (
               SELECT symbol,
                      MAX(volume) FILTER (WHERE row_number=1) AS latest_volume,
                      AVG(volume) FILTER (WHERE row_number<=20) AS average_volume_20,
                      PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY volume)
                          FILTER (WHERE row_number<=20) AS median_volume_20,
                      AVG(volume*close_price) FILTER (WHERE row_number<=20) AS average_turnover_20
               FROM ranked GROUP BY symbol
           )
           UPDATE market_technical_indicators t SET
               latest_volume=v.latest_volume,average_volume_20=v.average_volume_20,
               median_volume_20=v.median_volume_20,average_turnover_20=v.average_turnover_20,
               indicators=t.indicators || jsonb_build_object(
                   'latest_volume',v.latest_volume,'average_volume_20',v.average_volume_20,
                   'median_volume_20',v.median_volume_20,'average_turnover_20',v.average_turnover_20,
                   'technical_as_of_date',t.as_of_date,'technical_engine_version',t.engine_version
               )
           FROM volume_stats v
           WHERE v.symbol=t.symbol AND (t.latest_volume IS NULL OR t.average_volume_20 IS NULL)""",
        """UPDATE market_screener_cache c SET
               combined_data=COALESCE(c.combined_data::jsonb,'{}'::jsonb) || t.indicators,
               updated_at=NOW()
           FROM market_technical_indicators t
           WHERE t.symbol=c.symbol AND t.average_volume_20 IS NOT NULL
             AND (c.combined_data IS NULL OR NOT (c.combined_data::jsonb ? 'average_volume_20'))""",
        """CREATE TABLE IF NOT EXISTS market_history_cache_state (
            symbol VARCHAR(30) NOT NULL,
            source VARCHAR(40) NOT NULL,
            adjusted BOOLEAN NOT NULL DEFAULT TRUE,
            requested_start DATE,
            requested_end DATE,
            history_start DATE,
            history_end DATE,
            bars_count INTEGER NOT NULL DEFAULT 0,
            status VARCHAR(20) NOT NULL DEFAULT 'ready',
            error TEXT,
            data_hash VARCHAR(64),
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (symbol, source, adjusted)
        )""",
        """CREATE TABLE IF NOT EXISTS market_indicator_daily (
            symbol VARCHAR(30) NOT NULL,
            session_date DATE NOT NULL,
            engine_version VARCHAR(40) NOT NULL,
            rsi_14 DOUBLE PRECISION,
            macd_histogram DOUBLE PRECISION,
            adx_14 DOUBLE PRECISION,
            atr_percent DOUBLE PRECISION,
            mfi_14 DOUBLE PRECISION,
            volume_ratio_20 DOUBLE PRECISION,
            signal VARCHAR(30),
            signal_score DOUBLE PRECISION,
            indicators JSONB NOT NULL,
            calculated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (symbol, session_date, engine_version)
        )""",
        "CREATE INDEX IF NOT EXISTS ix_market_indicator_daily_date ON market_indicator_daily (session_date DESC, symbol)",
        """CREATE TABLE IF NOT EXISTS backtest_data_snapshots (
            snapshot_id VARCHAR(64) PRIMARY KEY,
            source VARCHAR(40) NOT NULL,
            universe JSONB NOT NULL,
            manifest JSONB NOT NULL,
            data_hash VARCHAR(64) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS backtest_runs (
            run_id VARCHAR(64) PRIMARY KEY,
            owner_id VARCHAR(100) NOT NULL DEFAULT 'local',
            scan_key VARCHAR(64),
            name VARCHAR(200) NOT NULL,
            notes TEXT,
            run_type VARCHAR(20) NOT NULL DEFAULT 'market_scan',
            status VARCHAR(20) NOT NULL DEFAULT 'queued',
            configuration JSONB NOT NULL,
            strategy_version VARCHAR(40) NOT NULL DEFAULT 'strategy-v1',
            engine_version VARCHAR(40) NOT NULL,
            indicator_engine_version VARCHAR(40) NOT NULL,
            data_snapshot_id VARCHAR(64) REFERENCES backtest_data_snapshots(snapshot_id),
            symbols_completed INTEGER NOT NULL DEFAULT 0,
            symbols_total INTEGER NOT NULL DEFAULT 0,
            combinations_completed INTEGER NOT NULL DEFAULT 0,
            progress_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
            current_symbol VARCHAR(30),
            cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
            pause_requested BOOLEAN NOT NULL DEFAULT FALSE,
            lease_owner VARCHAR(100),
            lease_expires_at TIMESTAMPTZ,
            heartbeat_at TIMESTAMPTZ,
            error_summary TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            last_refresh_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            deleted_at TIMESTAMPTZ
        )""",
        "ALTER TABLE backtest_runs ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ",
        "CREATE INDEX IF NOT EXISTS ix_backtest_runs_owner_created ON backtest_runs (owner_id, created_at DESC) WHERE deleted_at IS NULL AND archived_at IS NULL",
        "ALTER TABLE backtest_runs ADD COLUMN IF NOT EXISTS scan_key VARCHAR(64)",
        "ALTER TABLE backtest_runs ADD COLUMN IF NOT EXISTS last_refresh_at TIMESTAMPTZ",
        """UPDATE backtest_runs
           SET run_type='ipo_research'
           WHERE run_type<>'ipo_research'
             AND jsonb_typeof(configuration->'preset_ids')='array'
             AND jsonb_array_length(configuration->'preset_ids')>0
             AND NOT EXISTS (
                 SELECT 1 FROM jsonb_array_elements_text(configuration->'preset_ids') preset_id
                 WHERE preset_id NOT LIKE 'ipo_%'
             )""",
        "DROP INDEX IF EXISTS uq_backtest_runs_owner_scan_key",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_backtest_runs_owner_scan_key ON backtest_runs (owner_id, scan_key) WHERE deleted_at IS NULL AND archived_at IS NULL AND scan_key IS NOT NULL",
        "CREATE INDEX IF NOT EXISTS ix_backtest_runs_queue ON backtest_runs (status, created_at) WHERE deleted_at IS NULL AND archived_at IS NULL",
        "CREATE INDEX IF NOT EXISTS ix_backtest_runs_archived ON backtest_runs (owner_id, archived_at) WHERE deleted_at IS NULL AND archived_at IS NOT NULL",
        """UPDATE backtest_runs SET owner_id=(SELECT id::text FROM frontend_users WHERE username=:seed_username)
           WHERE owner_id='local' AND EXISTS (SELECT 1 FROM frontend_users WHERE username=:seed_username)""",
        """CREATE TABLE IF NOT EXISTS backtest_run_symbols (
            run_id VARCHAR(64) NOT NULL REFERENCES backtest_runs(run_id) ON DELETE CASCADE,
            symbol VARCHAR(30) NOT NULL,
            security_type VARCHAR(50),
            sector VARCHAR(150),
            listing_age_days INTEGER,
            ltp DOUBLE PRECISION,
            latest_volume DOUBLE PRECISION,
            average_volume_20 DOUBLE PRECISION,
            median_volume_20 DOUBLE PRECISION,
            average_turnover_20 DOUBLE PRECISION,
            status VARCHAR(20) NOT NULL DEFAULT 'queued',
            bars_count INTEGER NOT NULL DEFAULT 0,
            combinations_completed INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            last_tested_session DATE,
            PRIMARY KEY (run_id, symbol)
        )""",
        "CREATE INDEX IF NOT EXISTS ix_backtest_run_symbols_status ON backtest_run_symbols (run_id, status)",
        "ALTER TABLE backtest_run_symbols ADD COLUMN IF NOT EXISTS average_volume_20 DOUBLE PRECISION",
        "ALTER TABLE backtest_run_symbols ADD COLUMN IF NOT EXISTS last_tested_session DATE",
        """UPDATE backtest_run_symbols s
           SET average_volume_20=(
               SELECT AVG(recent.volume) FROM (
                   SELECT m.volume FROM market_ohlcv_daily m
                   WHERE m.symbol=s.symbol AND m.adjusted=TRUE AND m.volume IS NOT NULL
                   ORDER BY m.source_timestamp DESC NULLS LAST,m.session_date DESC LIMIT 20
               ) recent
           )
           WHERE s.average_volume_20 IS NULL""",
        """CREATE TABLE IF NOT EXISTS backtest_results (
            result_id BIGSERIAL PRIMARY KEY,
            run_id VARCHAR(64) NOT NULL REFERENCES backtest_runs(run_id) ON DELETE CASCADE,
            symbol VARCHAR(30) NOT NULL,
            preset_id VARCHAR(120) NOT NULL,
            preset_name VARCHAR(200) NOT NULL,
            preset_family VARCHAR(100),
            category VARCHAR(100),
            evaluation_split VARCHAR(20) NOT NULL DEFAULT 'full',
            bars INTEGER NOT NULL DEFAULT 0,
            total_trades INTEGER NOT NULL DEFAULT 0,
            wins INTEGER NOT NULL DEFAULT 0,
            losses INTEGER NOT NULL DEFAULT 0,
            win_rate_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
            win_rate_ci_low DOUBLE PRECISION,
            win_rate_ci_high DOUBLE PRECISION,
            confidence_score DOUBLE PRECISION NOT NULL DEFAULT 0,
            robust_score DOUBLE PRECISION NOT NULL DEFAULT 0,
            net_return_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
            max_drawdown_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
            sharpe_ratio DOUBLE PRECISION,
            sortino_ratio DOUBLE PRECISION,
            profit_factor DOUBLE PRECISION,
            expectancy_pct DOUBLE PRECISION,
            alpha_vs_benchmark_pct DOUBLE PRECISION,
            exposure_pct DOUBLE PRECISION,
            average_holding_days DOUBLE PRECISION,
            oos_trades INTEGER NOT NULL DEFAULT 0,
            oos_win_rate_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
            oos_return_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
            oos_expectancy_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
            oos_sharpe_ratio DOUBLE PRECISION,
            oos_max_drawdown_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
            walk_forward_profitable_pct DOUBLE PRECISION,
            p_value DOUBLE PRECISION,
            fdr_q_value DOUBLE PRECISION,
            data_completeness_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
            liquidity_score DOUBLE PRECISION NOT NULL DEFAULT 0,
            sample_quality VARCHAR(20) NOT NULL DEFAULT 'thin',
            recommendation_status VARCHAR(30) NOT NULL DEFAULT 'insufficient_sample',
            current_signal_active BOOLEAN NOT NULL DEFAULT FALSE,
            current_signal_status VARCHAR(30) NOT NULL DEFAULT 'no_signal',
            current_signal_date DATE,
            current_technical_score DOUBLE PRECISION NOT NULL DEFAULT 0,
            reliability_score DOUBLE PRECISION NOT NULL DEFAULT 0,
            strong_buy_qualified BOOLEAN NOT NULL DEFAULT FALSE,
            current_evidence JSONB,
            warning_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
            technical_snapshot JSONB,
            assumptions JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (run_id, symbol, preset_id, evaluation_split)
        )""",
        "ALTER TABLE backtest_results ADD COLUMN IF NOT EXISTS current_signal_active BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE backtest_results ADD COLUMN IF NOT EXISTS current_signal_status VARCHAR(30) NOT NULL DEFAULT 'no_signal'",
        "ALTER TABLE backtest_results ADD COLUMN IF NOT EXISTS current_signal_date DATE",
        "ALTER TABLE backtest_results ADD COLUMN IF NOT EXISTS current_technical_score DOUBLE PRECISION NOT NULL DEFAULT 0",
        "ALTER TABLE backtest_results ADD COLUMN IF NOT EXISTS reliability_score DOUBLE PRECISION NOT NULL DEFAULT 0",
        "ALTER TABLE backtest_results ADD COLUMN IF NOT EXISTS strong_buy_qualified BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE backtest_results ADD COLUMN IF NOT EXISTS current_evidence JSONB",
        "ALTER TABLE backtest_results ADD COLUMN IF NOT EXISTS configuration_hash VARCHAR(32)",
        "ALTER TABLE backtest_results ADD COLUMN IF NOT EXISTS configuration_identity_version INTEGER NOT NULL DEFAULT 1",
        """UPDATE backtest_results AS result SET configuration_hash=md5(concat_ws('|','simulation-identity-v2',result.symbol,result.preset_id,result.evaluation_split,
             COALESCE(run.engine_version,''),COALESCE(run.indicator_engine_version,''),
             COALESCE(assumptions->>'preset_source_hash',''),COALESCE(assumptions->>'preset_version',''),
             COALESCE(assumptions->>'strategy_query',''),COALESCE(assumptions->>'sell_strategy_query',''),
             COALESCE(assumptions->>'strategy_query_template',''),COALESCE(assumptions->>'strategy_mode',''),
             COALESCE(assumptions->>'entry',''),COALESCE(assumptions->>'intraday_priority',''),
             COALESCE(assumptions->>'exit_rule_id',''),COALESCE(assumptions->>'exit_condition',''),
             COALESCE(assumptions->>'min_holding_days',''),COALESCE(assumptions->>'max_holding_days',''),
             COALESCE(assumptions->>'stop_loss_pct',''),COALESCE(assumptions->>'take_profit_pct',''),
             COALESCE(assumptions->>'trailing_stop_pct',''),COALESCE(assumptions->>'charge_model',''),
             COALESCE(assumptions->>'investor_type',''),COALESCE(assumptions->>'capital_gains_tax_enabled',''),
             COALESCE(assumptions->>'fee_pct_each_side',''),COALESCE(assumptions->>'fixed_fee_each_order',''),
             COALESCE(assumptions->>'dp_charge_each_sell',''),COALESCE(assumptions->>'slippage_pct_each_side',''),
             COALESCE(assumptions->>'position_size_pct',''),COALESCE(assumptions->>'max_volume_participation_pct',''),
             COALESCE(assumptions->>'initial_capital',''),COALESCE(assumptions->>'brokerage_schedule',''),
             COALESCE(assumptions->>'risk_free_rate_pct',''),
             COALESCE(assumptions->'period'->>'start',''),COALESCE(assumptions->>'data_source','')))
             ,configuration_identity_version=2
           FROM backtest_runs AS run
           WHERE result.run_id=run.run_id AND result.configuration_identity_version<2""",
        "ALTER TABLE backtest_results ALTER COLUMN configuration_identity_version SET DEFAULT 2",
        "CREATE INDEX IF NOT EXISTS ix_backtest_results_rank ON backtest_results (run_id, evaluation_split, robust_score DESC, total_trades DESC)",
        "CREATE INDEX IF NOT EXISTS ix_backtest_results_current_buy ON backtest_results (run_id, strong_buy_qualified, reliability_score DESC) WHERE current_signal_active = TRUE",
        "CREATE INDEX IF NOT EXISTS ix_backtest_results_symbol ON backtest_results (run_id, symbol, robust_score DESC)",
        "CREATE INDEX IF NOT EXISTS ix_backtest_results_preset ON backtest_results (run_id, preset_id, robust_score DESC)",
        "CREATE INDEX IF NOT EXISTS ix_backtest_results_configuration ON backtest_results (configuration_hash)",
        "DROP INDEX IF EXISTS ix_backtest_results_retained_run_rank",
        "DROP INDEX IF EXISTS ix_backtest_results_retained_configuration",
        """CREATE INDEX IF NOT EXISTS ix_backtest_results_retained_run_rank_v2
           ON backtest_results (run_id,robust_score DESC,total_trades DESC,result_id)
           WHERE (total_trades>=16 AND win_rate_pct>=50)
              OR (total_trades>=9 AND win_rate_pct>=60)""",
        """CREATE INDEX IF NOT EXISTS ix_backtest_results_retained_configuration_v2
           ON backtest_results (configuration_hash,result_id)
           WHERE (total_trades>=16 AND win_rate_pct>=50)
              OR (total_trades>=9 AND win_rate_pct>=60)""",
        "CREATE INDEX IF NOT EXISTS ix_backtest_runs_owner_active ON backtest_runs (owner_id, run_id) WHERE deleted_at IS NULL AND archived_at IS NULL",
        """CREATE TABLE IF NOT EXISTS backtest_canonical_results (
            owner_id VARCHAR(100) NOT NULL,
            configuration_hash VARCHAR(32) NOT NULL,
            result_id BIGINT NOT NULL UNIQUE REFERENCES backtest_results(result_id) ON DELETE CASCADE,
            run_id VARCHAR(64),
            symbol VARCHAR(32),
            security_type VARCHAR(40),
            data_session DATE,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (owner_id, configuration_hash)
        )""",
        "ALTER TABLE backtest_canonical_results ADD COLUMN IF NOT EXISTS run_id VARCHAR(64)",
        "ALTER TABLE backtest_canonical_results ADD COLUMN IF NOT EXISTS symbol VARCHAR(32)",
        "ALTER TABLE backtest_canonical_results ADD COLUMN IF NOT EXISTS security_type VARCHAR(40)",
        """UPDATE backtest_canonical_results canonical
           SET run_id=r.run_id,symbol=r.symbol,security_type=s.security_type
           FROM backtest_results r
           JOIN backtest_run_symbols s ON s.run_id=r.run_id AND s.symbol=r.symbol
           WHERE canonical.result_id=r.result_id
             AND (canonical.run_id IS NULL OR canonical.symbol IS NULL OR canonical.security_type IS NULL)""",
        "CREATE INDEX IF NOT EXISTS ix_backtest_canonical_owner_result ON backtest_canonical_results (owner_id, result_id)",
        "CREATE INDEX IF NOT EXISTS ix_backtest_canonical_owner_security ON backtest_canonical_results (owner_id, security_type)",
        "CREATE INDEX IF NOT EXISTS ix_backtest_canonical_owner_run_security ON backtest_canonical_results (owner_id, run_id, security_type)",
        """DELETE FROM backtest_canonical_results canonical
           USING backtest_results r
           WHERE canonical.result_id=r.result_id
             AND canonical.configuration_hash<>r.configuration_hash""",
        """DELETE FROM backtest_canonical_results canonical
           WHERE NOT EXISTS (
               SELECT 1
               FROM backtest_results r
               JOIN backtest_runs br ON br.run_id=r.run_id
               WHERE r.result_id=canonical.result_id AND br.deleted_at IS NULL AND br.archived_at IS NULL
                 AND ((r.total_trades>=16 AND r.win_rate_pct>=50)
                      OR (r.total_trades>=9 AND r.win_rate_pct>=60))
           )""",
        """INSERT INTO backtest_canonical_results
               (owner_id,configuration_hash,result_id,run_id,symbol,security_type,data_session,updated_at)
           SELECT DISTINCT ON (br.owner_id,r.configuration_hash)
                  br.owner_id,r.configuration_hash,r.result_id,r.run_id,r.symbol,s.security_type,
                  r.current_signal_date,NOW()
           FROM backtest_results r
           JOIN backtest_runs br ON br.run_id=r.run_id
           JOIN backtest_run_symbols s ON s.run_id=r.run_id AND s.symbol=r.symbol
           WHERE br.deleted_at IS NULL AND br.archived_at IS NULL AND r.configuration_hash IS NOT NULL
             AND ((r.total_trades>=16 AND r.win_rate_pct>=50)
                  OR (r.total_trades>=9 AND r.win_rate_pct>=60))
           ORDER BY br.owner_id,r.configuration_hash,r.current_signal_date DESC NULLS LAST,r.result_id DESC
           ON CONFLICT (owner_id,configuration_hash) DO UPDATE SET
             result_id=EXCLUDED.result_id,run_id=EXCLUDED.run_id,symbol=EXCLUDED.symbol,
             security_type=EXCLUDED.security_type,data_session=EXCLUDED.data_session,updated_at=NOW()
           WHERE EXCLUDED.data_session IS NOT NULL
             AND (backtest_canonical_results.data_session IS NULL
                  OR EXCLUDED.data_session>backtest_canonical_results.data_session
                  OR (EXCLUDED.data_session=backtest_canonical_results.data_session
                      AND EXCLUDED.result_id>backtest_canonical_results.result_id))""",
        "CREATE INDEX IF NOT EXISTS ix_backtest_results_win_rate_sort ON backtest_results (win_rate_pct DESC NULLS LAST,total_trades DESC,result_id)",
        "CREATE INDEX IF NOT EXISTS ix_backtest_results_win_rate_asc_sort ON backtest_results (win_rate_pct ASC NULLS LAST,total_trades DESC,result_id)",
        "CREATE INDEX IF NOT EXISTS ix_backtest_results_win_rate_desc_v2 ON backtest_results (win_rate_pct DESC NULLS LAST,total_trades DESC NULLS LAST,result_id ASC)",
        "CREATE INDEX IF NOT EXISTS ix_backtest_results_win_rate_asc_v2 ON backtest_results (win_rate_pct ASC NULLS LAST,total_trades DESC NULLS LAST,result_id ASC)",
        "CREATE INDEX IF NOT EXISTS ix_backtest_results_robust_sort ON backtest_results (robust_score DESC NULLS LAST,total_trades DESC,result_id)",
        "CREATE INDEX IF NOT EXISTS ix_backtest_results_robust_desc_v2 ON backtest_results (robust_score DESC NULLS LAST,total_trades DESC NULLS LAST,result_id ASC)",
        "CREATE INDEX IF NOT EXISTS ix_backtest_results_robust_asc_v2 ON backtest_results (robust_score ASC NULLS LAST,total_trades DESC NULLS LAST,result_id ASC)",
        "CREATE INDEX IF NOT EXISTS ix_backtest_results_return_sort ON backtest_results (net_return_pct DESC NULLS LAST,total_trades DESC,result_id)",
        "CREATE INDEX IF NOT EXISTS ix_backtest_results_return_desc_v2 ON backtest_results (net_return_pct DESC NULLS LAST,total_trades DESC NULLS LAST,result_id ASC)",
        "CREATE INDEX IF NOT EXISTS ix_backtest_results_return_asc_v2 ON backtest_results (net_return_pct ASC NULLS LAST,total_trades DESC NULLS LAST,result_id ASC)",
        "CREATE INDEX IF NOT EXISTS ix_backtest_results_drawdown_sort ON backtest_results (max_drawdown_pct ASC NULLS LAST,total_trades DESC,result_id)",
        "CREATE INDEX IF NOT EXISTS ix_backtest_results_drawdown_asc_v2 ON backtest_results (max_drawdown_pct ASC NULLS LAST,total_trades DESC NULLS LAST,result_id ASC)",
        "CREATE INDEX IF NOT EXISTS ix_backtest_results_drawdown_desc_v2 ON backtest_results (max_drawdown_pct DESC NULLS LAST,total_trades DESC NULLS LAST,result_id ASC)",
        """CREATE TABLE IF NOT EXISTS backtest_result_artifacts (
            artifact_key VARCHAR(64) PRIMARY KEY,
            symbol VARCHAR(30) NOT NULL,
            strategy_id VARCHAR(120) NOT NULL,
            strategy_hash VARCHAR(64) NOT NULL,
            settings_hash VARCHAR(64) NOT NULL,
            data_source VARCHAR(40) NOT NULL,
            start_date DATE NOT NULL,
            data_session DATE NOT NULL,
            data_hash VARCHAR(64) NOT NULL,
            engine_version VARCHAR(40) NOT NULL,
            indicator_engine_version VARCHAR(40) NOT NULL,
            result_payload JSONB NOT NULL,
            market_profile JSONB NOT NULL DEFAULT '{}'::jsonb,
            technical_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
            use_count BIGINT NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_used_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS ix_backtest_artifacts_symbol_strategy ON backtest_result_artifacts (symbol, strategy_hash, settings_hash, data_session DESC)",
        "CREATE INDEX IF NOT EXISTS ix_backtest_artifacts_strategy_session ON backtest_result_artifacts (strategy_id, data_session DESC)",
        "CREATE INDEX IF NOT EXISTS ix_backtest_artifacts_last_used ON backtest_result_artifacts (last_used_at DESC)",
        """CREATE TABLE IF NOT EXISTS backtest_strategy_definitions (
            strategy_hash VARCHAR(64) PRIMARY KEY,
            strategy_id VARCHAR(120) NOT NULL,
            strategy_name VARCHAR(200) NOT NULL,
            definition JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS ix_backtest_strategy_definitions_id ON backtest_strategy_definitions (strategy_id,strategy_hash)",
        """CREATE TABLE IF NOT EXISTS backtest_rejected_strategies (
            rejection_key VARCHAR(64) PRIMARY KEY,
            symbol VARCHAR(30) NOT NULL,
            stock_name VARCHAR(200) NOT NULL,
            strategy_id VARCHAR(120) NOT NULL,
            strategy_name VARCHAR(200) NOT NULL,
            strategy_hash VARCHAR(64) NOT NULL,
            settings_hash VARCHAR(64) NOT NULL,
            engine_version VARCHAR(40) NOT NULL,
            indicator_engine_version VARCHAR(40) NOT NULL,
            total_trades INTEGER NOT NULL DEFAULT 0,
            win_rate_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
            rejection_reason VARCHAR(60) NOT NULL,
            policy_version VARCHAR(60) NOT NULL,
            strategy_definition JSONB NOT NULL DEFAULT '{}'::jsonb,
            owner_id VARCHAR(100),
            source_run_id VARCHAR(64),
            last_tested_session DATE,
            next_recheck_at TIMESTAMPTZ,
            revalidation_state VARCHAR(30) NOT NULL DEFAULT 'frozen',
            recheck_count INTEGER NOT NULL DEFAULT 0,
            last_revalidated_at TIMESTAMPTZ,
            promoted_at TIMESTAMPTZ,
            last_recheck_error TEXT,
            last_recheck_duration_seconds DOUBLE PRECISION,
            latest_signal_status VARCHAR(30),
            latest_signal_date DATE,
            latest_signal_evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
            lease_owner VARCHAR(100),
            lease_expires_at TIMESTAMPTZ,
            first_rejected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            skip_count BIGINT NOT NULL DEFAULT 0
        )""",
        "ALTER TABLE backtest_rejected_strategies ADD COLUMN IF NOT EXISTS stock_name VARCHAR(200)",
        "ALTER TABLE backtest_rejected_strategies ADD COLUMN IF NOT EXISTS strategy_name VARCHAR(200)",
        "ALTER TABLE backtest_rejected_strategies ADD COLUMN IF NOT EXISTS rejection_reason VARCHAR(60)",
        "ALTER TABLE backtest_rejected_strategies ADD COLUMN IF NOT EXISTS policy_version VARCHAR(60)",
        "ALTER TABLE backtest_rejected_strategies ADD COLUMN IF NOT EXISTS strategy_definition JSONB NOT NULL DEFAULT '{}'::jsonb",
        "ALTER TABLE backtest_rejected_strategies ADD COLUMN IF NOT EXISTS owner_id VARCHAR(100)",
        "ALTER TABLE backtest_rejected_strategies ADD COLUMN IF NOT EXISTS source_run_id VARCHAR(64)",
        "ALTER TABLE backtest_rejected_strategies ADD COLUMN IF NOT EXISTS last_tested_session DATE",
        "ALTER TABLE backtest_rejected_strategies ADD COLUMN IF NOT EXISTS next_recheck_at TIMESTAMPTZ",
        "ALTER TABLE backtest_rejected_strategies ADD COLUMN IF NOT EXISTS revalidation_state VARCHAR(30) NOT NULL DEFAULT 'frozen'",
        "ALTER TABLE backtest_rejected_strategies ADD COLUMN IF NOT EXISTS recheck_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE backtest_rejected_strategies ADD COLUMN IF NOT EXISTS last_revalidated_at TIMESTAMPTZ",
        "ALTER TABLE backtest_rejected_strategies ADD COLUMN IF NOT EXISTS promoted_at TIMESTAMPTZ",
        "ALTER TABLE backtest_rejected_strategies ADD COLUMN IF NOT EXISTS last_recheck_error TEXT",
        "ALTER TABLE backtest_rejected_strategies ADD COLUMN IF NOT EXISTS last_recheck_duration_seconds DOUBLE PRECISION",
        "ALTER TABLE backtest_rejected_strategies ADD COLUMN IF NOT EXISTS latest_signal_status VARCHAR(30)",
        "ALTER TABLE backtest_rejected_strategies ADD COLUMN IF NOT EXISTS latest_signal_date DATE",
        "ALTER TABLE backtest_rejected_strategies ADD COLUMN IF NOT EXISTS latest_signal_evidence JSONB NOT NULL DEFAULT '{}'::jsonb",
        "ALTER TABLE backtest_rejected_strategies ADD COLUMN IF NOT EXISTS trade_samples JSONB NOT NULL DEFAULT '[]'::jsonb",
        "ALTER TABLE backtest_rejected_strategies ADD COLUMN IF NOT EXISTS lease_owner VARCHAR(100)",
        "ALTER TABLE backtest_rejected_strategies ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ",
        """CREATE INDEX IF NOT EXISTS ix_backtest_rejected_policy_v2_pending
           ON backtest_rejected_strategies (rejection_key)
           WHERE policy_version IS NULL
              OR policy_version<>'trades-16-win-50-or-trades-9-win-60-v2'""",
        """DO $retention_policy$
           BEGIN
             IF EXISTS (
                 SELECT 1 FROM backtest_rejected_strategies
                 WHERE policy_version IS NULL
                    OR policy_version<>'trades-16-win-50-or-trades-9-win-60-v2'
                 LIMIT 1
             ) THEN
               UPDATE backtest_rejected_strategies
               SET stock_name=COALESCE(stock_name,symbol),
                   strategy_name=COALESCE(strategy_name,strategy_id),
                   rejection_reason=COALESCE(rejection_reason,'legacy_rejection'),
                   policy_version='trades-16-win-50-or-trades-9-win-60-v2',
                   revalidation_state=CASE
                     WHEN (total_trades>=16 AND win_rate_pct>=50)
                       OR (total_trades>=9 AND win_rate_pct>=60) THEN 'promoted'
                     WHEN total_trades>=9 AND win_rate_pct>=35 THEN 'frozen'
                     ELSE 'ineligible'
                   END,
                   next_recheck_at=CASE
                     WHEN NOT ((total_trades>=16 AND win_rate_pct>=50)
                               OR (total_trades>=9 AND win_rate_pct>=60))
                      AND total_trades>=9 AND win_rate_pct>=35
                     THEN COALESCE(next_recheck_at,last_seen_at+INTERVAL '30 days')
                     ELSE NULL
                   END
               WHERE policy_version IS NULL
                  OR policy_version<>'trades-16-win-50-or-trades-9-win-60-v2';
             END IF;
           END
           $retention_policy$""",
        "ALTER TABLE backtest_rejected_strategies ALTER COLUMN stock_name SET NOT NULL",
        "ALTER TABLE backtest_rejected_strategies ALTER COLUMN strategy_name SET NOT NULL",
        "ALTER TABLE backtest_rejected_strategies ALTER COLUMN rejection_reason SET NOT NULL",
        "ALTER TABLE backtest_rejected_strategies ALTER COLUMN policy_version SET NOT NULL",
        """CREATE UNIQUE INDEX IF NOT EXISTS ix_backtest_rejected_identity
           ON backtest_rejected_strategies
           (symbol,strategy_hash,settings_hash,engine_version,indicator_engine_version)""",
        """CREATE INDEX IF NOT EXISTS ix_backtest_rejected_due
           ON backtest_rejected_strategies
           (next_recheck_at,win_rate_pct DESC,total_trades DESC,rejection_key)
           WHERE revalidation_state='frozen' AND next_recheck_at IS NOT NULL""",
        "CREATE INDEX IF NOT EXISTS ix_backtest_rejected_source_run ON backtest_rejected_strategies (source_run_id,strategy_id,symbol)",
        """UPDATE backtest_run_symbols s SET last_tested_session=(
               SELECT MAX(r.current_signal_date) FROM backtest_results r
               WHERE r.run_id=s.run_id AND r.symbol=s.symbol
           ) WHERE s.last_tested_session IS NULL""",
        """CREATE TABLE IF NOT EXISTS backtest_trades (
            trade_id BIGSERIAL PRIMARY KEY,
            result_id BIGINT NOT NULL REFERENCES backtest_results(result_id) ON DELETE CASCADE,
            sequence_no INTEGER NOT NULL,
            signal_date DATE,
            entry_date DATE NOT NULL,
            entry_price DOUBLE PRECISION NOT NULL,
            exit_date DATE NOT NULL,
            exit_price DOUBLE PRECISION NOT NULL,
            quantity INTEGER NOT NULL,
            holding_days INTEGER NOT NULL DEFAULT 0,
            exit_reason VARCHAR(50),
            fees DOUBLE PRECISION NOT NULL DEFAULT 0,
            broker_commission DOUBLE PRECISION NOT NULL DEFAULT 0,
            buy_broker_commission DOUBLE PRECISION NOT NULL DEFAULT 0,
            sell_broker_commission DOUBLE PRECISION NOT NULL DEFAULT 0,
            sebon_fee DOUBLE PRECISION NOT NULL DEFAULT 0,
            buy_sebon_fee DOUBLE PRECISION NOT NULL DEFAULT 0,
            sell_sebon_fee DOUBLE PRECISION NOT NULL DEFAULT 0,
            dp_charge DOUBLE PRECISION NOT NULL DEFAULT 0,
            capital_gains_tax DOUBLE PRECISION NOT NULL DEFAULT 0,
            capital_gains_tax_rate_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
            total_charges DOUBLE PRECISION NOT NULL DEFAULT 0,
            gross_pnl DOUBLE PRECISION NOT NULL DEFAULT 0,
            net_pnl_before_tax DOUBLE PRECISION NOT NULL DEFAULT 0,
            slippage_cost DOUBLE PRECISION NOT NULL DEFAULT 0,
            pnl DOUBLE PRECISION NOT NULL DEFAULT 0,
            return_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
            UNIQUE (result_id, sequence_no)
        )""",
        "ALTER TABLE backtest_trades ADD COLUMN IF NOT EXISTS broker_commission DOUBLE PRECISION NOT NULL DEFAULT 0",
        "ALTER TABLE backtest_trades ADD COLUMN IF NOT EXISTS buy_broker_commission DOUBLE PRECISION NOT NULL DEFAULT 0",
        "ALTER TABLE backtest_trades ADD COLUMN IF NOT EXISTS sell_broker_commission DOUBLE PRECISION NOT NULL DEFAULT 0",
        "ALTER TABLE backtest_trades ADD COLUMN IF NOT EXISTS sebon_fee DOUBLE PRECISION NOT NULL DEFAULT 0",
        "ALTER TABLE backtest_trades ADD COLUMN IF NOT EXISTS buy_sebon_fee DOUBLE PRECISION NOT NULL DEFAULT 0",
        "ALTER TABLE backtest_trades ADD COLUMN IF NOT EXISTS sell_sebon_fee DOUBLE PRECISION NOT NULL DEFAULT 0",
        "ALTER TABLE backtest_trades ADD COLUMN IF NOT EXISTS dp_charge DOUBLE PRECISION NOT NULL DEFAULT 0",
        "ALTER TABLE backtest_trades ADD COLUMN IF NOT EXISTS capital_gains_tax DOUBLE PRECISION NOT NULL DEFAULT 0",
        "ALTER TABLE backtest_trades ADD COLUMN IF NOT EXISTS capital_gains_tax_rate_pct DOUBLE PRECISION NOT NULL DEFAULT 0",
        "ALTER TABLE backtest_trades ADD COLUMN IF NOT EXISTS total_charges DOUBLE PRECISION NOT NULL DEFAULT 0",
        "ALTER TABLE backtest_trades ADD COLUMN IF NOT EXISTS gross_pnl DOUBLE PRECISION NOT NULL DEFAULT 0",
        "ALTER TABLE backtest_trades ADD COLUMN IF NOT EXISTS net_pnl_before_tax DOUBLE PRECISION NOT NULL DEFAULT 0",
        "CREATE INDEX IF NOT EXISTS ix_backtest_trades_result ON backtest_trades (result_id, sequence_no)",
        """CREATE TABLE IF NOT EXISTS backtest_portfolio_results (
            portfolio_result_id BIGSERIAL PRIMARY KEY,
            run_id VARCHAR(64) NOT NULL REFERENCES backtest_runs(run_id) ON DELETE CASCADE,
            preset_id VARCHAR(120) NOT NULL,
            preset_name VARCHAR(200) NOT NULL,
            summary JSONB NOT NULL,
            equity_curve JSONB,
            allocation_config JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (run_id, preset_id)
        )""",
        """CREATE TABLE IF NOT EXISTS backtest_saved_views (
            view_id BIGSERIAL PRIMARY KEY,
            owner_id VARCHAR(100) NOT NULL DEFAULT 'local',
            name VARCHAR(150) NOT NULL,
            filters JSONB NOT NULL,
            columns JSONB NOT NULL,
            sort_config JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (owner_id, name)
        )""",
        """CREATE TABLE IF NOT EXISTS market_backtest_recommendations (
            owner_id VARCHAR(100) NOT NULL DEFAULT 'local',
            symbol VARCHAR(30) NOT NULL,
            result_id BIGINT NOT NULL REFERENCES backtest_results(result_id) ON DELETE CASCADE,
            run_id VARCHAR(64) NOT NULL REFERENCES backtest_runs(run_id) ON DELETE CASCADE,
            preset_id VARCHAR(120) NOT NULL,
            preset_name VARCHAR(200) NOT NULL,
            signal_status VARCHAR(30) NOT NULL,
            signal_date DATE NOT NULL,
            recommendation_score DOUBLE PRECISION NOT NULL DEFAULT 0,
            win_rate_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
            total_trades INTEGER NOT NULL DEFAULT 0,
            net_return_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
            average_volume_20 DOUBLE PRECISION,
            payload JSONB NOT NULL,
            refreshed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (owner_id, symbol)
        )""",
        "CREATE INDEX IF NOT EXISTS ix_market_backtest_recommendations_rank ON market_backtest_recommendations (owner_id, signal_date DESC, recommendation_score DESC)",
        "DROP INDEX IF EXISTS ix_market_backtest_recommendations_retained",
        """CREATE INDEX IF NOT EXISTS ix_market_backtest_recommendations_retained_v2
           ON market_backtest_recommendations
           (owner_id,signal_date DESC,signal_status,recommendation_score DESC,symbol)
           WHERE (total_trades>=16 AND win_rate_pct>=50)
              OR (total_trades>=9 AND win_rate_pct>=60)""",
        """UPDATE market_backtest_recommendations SET owner_id=(SELECT id::text FROM frontend_users WHERE username=:seed_username)
           WHERE owner_id='local' AND EXISTS (SELECT 1 FROM frontend_users WHERE username=:seed_username)""",
        """CREATE TABLE IF NOT EXISTS backtest_ai_audits (
            audit_id BIGSERIAL PRIMARY KEY,
            run_id VARCHAR(64) REFERENCES backtest_runs(run_id) ON DELETE SET NULL,
            owner_id VARCHAR(100) NOT NULL DEFAULT 'local',
            action VARCHAR(40) NOT NULL,
            provider VARCHAR(80),
            model VARCHAR(100),
            prompt_version VARCHAR(40) NOT NULL,
            user_message TEXT NOT NULL,
            generated_plan JSONB,
            validation_result JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
        """UPDATE backtest_ai_audits SET owner_id=(SELECT id::text FROM frontend_users WHERE username=:seed_username)
           WHERE owner_id='local' AND EXISTS (SELECT 1 FROM frontend_users WHERE username=:seed_username)""",
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
    parameters = {
        "seed_username": os.getenv("FRONTEND_SEED_USER", "admin"),
        "admin_username": os.getenv("FRONTEND_ADMIN_USER", "manager"),
        "all_permissions": '["order_logs","schedule_orders","portfolio","market_analysis","stock_grabber","strategy_details","backtest","recommendations","stock_table","edis","settings","tms_login","admin_users"]',
        "default_permissions": '["order_logs","schedule_orders","portfolio","market_analysis","strategy_details","backtest","recommendations","stock_table","edis","settings","tms_login"]',
    }
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement), parameters)
