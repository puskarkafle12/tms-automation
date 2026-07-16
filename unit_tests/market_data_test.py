import json
import unittest
from datetime import date, timedelta
from unittest.mock import patch

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from utils.market_data.combined_screener import parse_combined_screener_query, run_combined_screener_from_db
from utils.market_data.canonical_fields import (
    build_combined_record,
    canonicalize_merolagani_record,
    ordered_columns_for_source,
)
from utils.market_data.dynamic_catalog import (
    GROQ_AI_SYSTEM_PROMPT_MAX_CHARS,
    build_dynamic_ai_system_prompt_from_records,
    build_dynamic_field_catalog,
    build_dynamic_query_spec,
    discover_combined_field_keys,
)
from utils.market_data.merolagani_fields import flatten_merolagani_row, merge_merolagani_records
from utils.market_data.repository import (
    daily_snapshot_has_source,
    get_new_symbols,
    load_latest_daily_stock_rows,
    set_new_symbol_watchlist_status,
)


class MarketDataRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE merolagani_daily_snapshots (
                        id INTEGER PRIMARY KEY,
                        snapshot_date DATE NOT NULL UNIQUE,
                        symbol_count INTEGER NOT NULL DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE merolagani_daily_stocks (
                        id INTEGER PRIMARY KEY,
                        snapshot_date DATE NOT NULL,
                        symbol VARCHAR NOT NULL,
                        data TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(snapshot_date, symbol)
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE market_symbol_registry (
                        symbol VARCHAR PRIMARY KEY,
                        first_seen_date DATE NOT NULL,
                        last_seen_date DATE NOT NULL,
                        is_watchlist BOOLEAN DEFAULT 1,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE market_screener_cache (
                        symbol VARCHAR PRIMARY KEY,
                        merolagani_data TEXT,
                        nepse_alpha_data TEXT,
                        combined_data TEXT,
                        merolagani_fetched_at TIMESTAMP,
                        nepse_alpha_fetched_at TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE market_data_refresh_log (
                        id INTEGER PRIMARY KEY,
                        refresh_type VARCHAR NOT NULL,
                        status VARCHAR NOT NULL,
                        symbol_count INTEGER,
                        message TEXT,
                        started_at TIMESTAMP,
                        completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
        self.Session = sessionmaker(bind=self.engine)

    def test_save_daily_snapshot_registers_new_symbols(self):
        db = self.Session()
        today = date.today()
        yesterday = today - timedelta(days=20)
        db.execute(
            text(
                """
                INSERT INTO market_symbol_registry (symbol, first_seen_date, last_seen_date, is_watchlist)
                VALUES ('AAA', :yesterday, :yesterday, 1)
                """
            ),
            {"yesterday": yesterday},
        )
        db.execute(
            text(
                """
                INSERT INTO market_symbol_registry (symbol, first_seen_date, last_seen_date, is_watchlist)
                VALUES ('ABC', :today, :today, 1)
                """
            ),
            {"today": today},
        )
        db.commit()

        # Discovery time is not listing time; a missing exchange listing date must not
        # make an old security appear newly listed.
        self.assertEqual(get_new_symbols(db, days=15), [])

    def test_get_new_symbols_filters_to_recent_equity_listings(self):
        db = self.Session()
        today = date.today()
        older_snapshot = today - timedelta(days=120)
        db.execute(
            text(
                """
                INSERT INTO merolagani_daily_snapshots (snapshot_date, symbol_count)
                VALUES (:older_snapshot, 1)
                """
            ),
            {"older_snapshot": older_snapshot},
        )
        db.execute(
            text(
                """
                INSERT INTO merolagani_daily_snapshots (snapshot_date, symbol_count)
                VALUES (:today, 5)
                """
            ),
            {"today": today},
        )
        db.execute(
            text(
                """
                INSERT INTO merolagani_daily_stocks (snapshot_date, symbol, data)
                VALUES
                    (:today, 'AAA', :aaa_data),
                    (:today, 'ADBLB', '{"Symbol":"ADBLB","Sector":"Others"}'),
                    (:today, 'GBBLPO', '{"Symbol":"GBBLPO","Sector":"Promotor Share"}'),
                    (:today, 'SRLIP', '{"Symbol":"SRLIP"}'),
                    (:today, 'LBLD86', '{"Symbol":"LBLD86"}')
                """
            ),
            {
                "today": today,
                "aaa_data": json.dumps(
                    {
                        "symbol": "AAA",
                        "company_name": "AAA Limited",
                        "sector": "Commercial Bank",
                        "listing_date": today.isoformat(),
                        "listing_age_days": 0,
                        "security_type": "ordinary_share",
                    }
                ),
            },
        )
        db.execute(
            text(
                """
                INSERT INTO market_screener_cache (symbol, combined_data)
                VALUES ('AAA', :combined_data)
                """
            ),
            {"combined_data": json.dumps({"symbol": "AAA", "qty": 12345})},
        )
        db.execute(
            text(
                """
                INSERT INTO market_symbol_registry (symbol, first_seen_date, last_seen_date, is_watchlist)
                VALUES
                    ('AAA', :today, :today, 1),
                    ('ADBLB', :today, :today, 1),
                    ('GBBLPO', :today, :today, 1),
                    ('SRLIP', :today, :today, 1),
                    ('LBLD86', :today, :today, 1)
                """
            ),
            {"today": today},
        )
        db.commit()

        new_symbols = get_new_symbols(db, days=15)
        self.assertEqual([item["symbol"] for item in new_symbols], ["AAA"])
        self.assertEqual(new_symbols[0]["sector"], "Commercial Bank")
        self.assertEqual(new_symbols[0]["company_name"], "AAA Limited")
        self.assertEqual(new_symbols[0]["volume"], 12345.0)

    def test_set_new_symbol_watchlist_status_updates_registry(self):
        db = self.Session()
        today = date.today()
        db.execute(
            text(
                """
                INSERT INTO market_symbol_registry (symbol, first_seen_date, last_seen_date, is_watchlist)
                VALUES ('AAA', :today, :today, 1)
                """
            ),
            {"today": today},
        )
        db.commit()

        updated = set_new_symbol_watchlist_status(db, ["AAA"], is_watchlist=False)
        db.commit()

        self.assertEqual(updated, 1)
        flag = db.execute(text("SELECT is_watchlist FROM market_symbol_registry WHERE symbol = 'AAA'")).scalar()
        self.assertIn(flag, (0, False))
        self.assertEqual(get_new_symbols(db, days=15), [])

    def test_load_latest_daily_stock_rows(self):
        db = self.Session()
        today = date.today()
        db.execute(
            text(
                """
                INSERT INTO merolagani_daily_snapshots (snapshot_date, symbol_count)
                VALUES (:today, 2)
                """
            ),
            {"today": today},
        )
        db.execute(
            text(
                """
                INSERT INTO merolagani_daily_stocks (snapshot_date, symbol, data)
                VALUES
                    (:today, 'AAA', '{"Symbol":"AAA","LTP":"100"}'),
                    (:today, 'BBB', '{"Symbol":"BBB","LTP":"200"}')
                """
            ),
            {"today": today},
        )
        db.commit()

        rows = load_latest_daily_stock_rows(db)
        self.assertEqual(len(rows), 2)
        self.assertEqual(flatten_merolagani_row(rows[0])["symbol"], "AAA")

    def test_daily_snapshot_source_detection_distinguishes_legacy_rows(self):
        db = self.Session()
        today = date.today()
        db.execute(
            text(
                """
                INSERT INTO merolagani_daily_stocks (snapshot_date, symbol, data)
                VALUES
                    (:today, 'OLD', '{"Symbol":"OLD"}'),
                    (:today, 'NEW', :new_data)
                """
            ),
            {
                "today": today,
                "new_data": json.dumps(
                    {
                        "symbol": "NEW",
                        "market_data_source": "sharesansar_company_list",
                        "market_snapshot_version": 2,
                    }
                ),
            },
        )
        db.commit()

        self.assertTrue(daily_snapshot_has_source(db, today, "sharesansar_company_list"))
        self.assertTrue(daily_snapshot_has_source(db, today, "sharesansar_company_list", min_version=2))
        self.assertFalse(daily_snapshot_has_source(db, today, "sharesansar_company_list", min_version=3))
        self.assertFalse(daily_snapshot_has_source(db, today, "another_source"))

    def test_combined_screener_filters_merolagani_and_nepse_fields(self):
        db = self.Session()
        db.execute(
            text(
                """
                INSERT INTO market_screener_cache (symbol, combined_data)
                VALUES (:symbol, :combined_data)
                """
            ),
            {
                "symbol": "AAA",
                "combined_data": '{"symbol":"AAA","ltp":100,"alpha_annualized":12,"pe_ratio":18}',
            },
        )
        db.commit()

        payload = run_combined_screener_from_db(
            db,
            ["AAA"],
            filters=[
                {"field": "ltp", "operator": "gte", "value": 90},
                {"field": "alpha_annualized", "operator": "gte", "value": 10},
            ],
            limit=10,
        )
        self.assertEqual(len(payload["results"]), 1)
        self.assertEqual(payload["results"][0]["symbol"], "AAA")

    def test_parse_combined_query_validates_sql(self):
        db = self.Session()
        db.execute(
            text(
                """
                INSERT INTO market_screener_cache (symbol, combined_data)
                VALUES (:symbol, :combined_data)
                """
            ),
            {
                "symbol": "AAA",
                "combined_data": '{"symbol":"AAA","ltp":100,"pe_ratio":18,"market_cap":1000000}',
            },
        )
        db.commit()

        parsed = parse_combined_screener_query(
            "SELECT * FROM market_combined WHERE pe_ratio <= 25 ORDER BY ltp DESC LIMIT 10",
            db=db,
        )
        self.assertTrue(parsed["valid"])
        self.assertIn("market_combined", parsed["sql"].lower())

        legacy = parse_combined_screener_query(
            "WHERE market_cap <= 5000000000 ORDER BY market_cap ASC LIMIT 10",
            db=db,
        )
        self.assertTrue(legacy["valid"])
        self.assertIn("market_cap", legacy["sql"].lower())

    def test_combined_parse_accepts_market_cap(self):
        db = self.Session()
        db.execute(
            text(
                """
                INSERT INTO market_screener_cache (symbol, combined_data)
                VALUES (:symbol, :combined_data)
                """
            ),
            {
                "symbol": "AAA",
                "combined_data": '{"symbol":"AAA","market_cap":1000000,"ltp":100}',
            },
        )
        db.commit()

        parsed = parse_combined_screener_query(
            "SELECT * FROM market_combined WHERE market_cap <= 5000000000 ORDER BY market_cap ASC LIMIT 25",
            db=db,
        )
        self.assertTrue(parsed["valid"])
        self.assertIn("market_cap", parsed["sql"].lower())


class MerolaganiFieldsTest(unittest.TestCase):
    def test_flatten_merolagani_row_maps_symbol_and_numeric_fields(self):
        record = flatten_merolagani_row(
            {
                "Symbol": "nabil",
                "LTP": "512.00",
                "% Change": "1.25%",
                "P/E Ratio": "14.5",
            }
        )
        self.assertEqual(record["symbol"], "NABIL")
        stored = canonicalize_merolagani_record(record)
        self.assertEqual(stored["ltp"], 512.0)
        self.assertEqual(stored["percent_change"], 1.25)
        self.assertEqual(stored["pe_ratio"], 14.5)

    def test_merge_merolagani_records_keeps_detail_and_live_prices(self):
        daily = flatten_merolagani_row(
            {
                "Symbol": "NABIL",
                "LTP": "500",
                "P/E Ratio": "12",
                "Market Capitalization": "1000",
            }
        )
        live = flatten_merolagani_row(
            {
                "Symbol": "NABIL",
                "LTP": "512",
                "% Change": "1.2",
            }
        )
        merged = merge_merolagani_records(daily, live)
        stored = canonicalize_merolagani_record(merged)
        self.assertEqual(stored["ltp"], 512.0)
        self.assertEqual(stored["pe_ratio"], 12.0)
        self.assertEqual(stored["market_cap"], 1000.0)
        self.assertEqual(stored["percent_change"], 1.2)

    def test_build_combined_record_merges_duplicate_price_fields(self):
        combined = build_combined_record(
            {"ml_ltp": 500, "ml_pe_ratio": 12.0},
            {"ltp": 505, "fundamental_pe_ttm": 13.5, "alpha_annualized": 8.2},
        )
        self.assertEqual(combined["ltp"], 505)
        self.assertEqual(combined["pe_ratio"], 13.5)
        self.assertEqual(combined["alpha_annualized"], 8.2)
        self.assertNotIn("ml_ltp", combined)


class CanonicalFieldsTest(unittest.TestCase):
    def test_ordered_columns_puts_all_empty_columns_last(self):
        rows = [
            {"symbol": "AAA", "ltp": 100, "percent_change": 1.2, "technical_macd": None},
            {"symbol": "BBB", "ltp": 200, "percent_change": -0.5, "technical_macd": ""},
        ]
        columns = ordered_columns_for_source("combined", rows)
        self.assertLess(columns.index("ltp"), columns.index("technical_macd"))
        self.assertEqual(columns[-1], "technical_macd")


class DynamicCatalogTest(unittest.TestCase):
    def test_build_dynamic_catalog_from_records(self):
        records = [
            {"symbol": "AAA", "ltp": 100, "alpha_annualized": 12, "custom_source_score": 0.8},
            {"symbol": "BBB", "ltp": 200, "alpha_annualized": 8, "custom_source_score": 0.4},
        ]
        catalog = build_dynamic_field_catalog(None, records=records)
        keys = [item["key"] for item in catalog]
        self.assertIn("ltp", keys)
        self.assertIn("custom_source_score", keys)

    def test_dynamic_query_spec_includes_custom_field(self):
        records = [{"symbol": "AAA", "custom_beta": 1.2, "ltp": 50}]
        spec = build_dynamic_query_spec(None, records=records)
        self.assertIn("custom_beta", spec["allowed_filter_keys"])
        self.assertTrue(spec.get("dynamic"))
        self.assertEqual(spec.get("unsupported_user_terms"), [])

    def test_company_fundamentals_are_queryable_with_natural_aliases(self):
        records = [
            {
                "symbol": "CZBIL",
                "company_name": "Citizens Bank International Limited",
                "security_type": "ordinary_share",
                "paid_up_capital": 15_507_463_800,
                "shares_outstanding": 155_074_638,
                "listing_date": "2017-01-10",
                "listing_age_days": 3473,
            }
        ]
        spec = build_dynamic_query_spec(None, records=records)
        self.assertIn("paid_up_capital", spec["allowed_filter_keys"])
        self.assertIn("shares_outstanding", spec["allowed_filter_keys"])
        self.assertEqual(spec["alias_map"]["listed_shares"], "shares_outstanding")

        prompt = build_dynamic_ai_system_prompt_from_records(records)
        self.assertIn("paid up capital", prompt.lower())
        self.assertIn("listed shares", prompt.lower())
        self.assertIn("security_type = 'ordinary_share'", prompt)

    def test_company_fundamentals_execute_in_market_sql(self):
        from utils.market_data.sql_screener import run_market_sql_screener

        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE market_screener_cache (
                        symbol VARCHAR PRIMARY KEY,
                        merolagani_data TEXT,
                        nepse_alpha_data TEXT,
                        combined_data TEXT,
                        merolagani_fetched_at TIMESTAMP,
                        nepse_alpha_fetched_at TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE merolagani_daily_snapshots (
                        snapshot_date DATE,
                        symbol_count INTEGER,
                        created_at TIMESTAMP
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE market_data_refresh_log (
                        refresh_type VARCHAR,
                        status VARCHAR,
                        completed_at TIMESTAMP
                    )
                    """
                )
            )
            connection.execute(
                text("INSERT INTO market_screener_cache (symbol, combined_data) VALUES (:symbol, :data)"),
                {
                    "symbol": "CZBIL",
                    "data": json.dumps(
                        {
                            "symbol": "CZBIL",
                            "company_name": "Citizens Bank International Limited",
                            "security_type": "ordinary_share",
                            "paid_up_capital": 15_507_463_800,
                            "shares_outstanding": 155_074_638,
                            "listing_date": "2017-01-10",
                        }
                    ),
                },
            )
        db = sessionmaker(bind=engine)()
        result = run_market_sql_screener(
            db,
            "SELECT symbol, paid_up_capital, shares_outstanding, listing_date "
            "FROM market_combined WHERE security_type = 'ordinary_share' "
            "ORDER BY paid_up_capital DESC LIMIT 10",
        )
        self.assertEqual(result["results"][0]["symbol"], "CZBIL")
        self.assertEqual(result["results"][0]["paid_up_capital"], 15_507_463_800)
        self.assertEqual(result["results"][0]["shares_outstanding"], 155_074_638)
        db.close()

    def test_build_combined_record_merges_new_source_fields(self):
        combined = build_combined_record(
            {"ltp": 100, "ml_pe_ratio": 10},
            {"fundamental_pe_ttm": 12, "custom_signal": "buy"},
            {"custom_signal": "hold", "new_metric": 5},
        )
        self.assertEqual(combined["ltp"], 100)
        self.assertEqual(combined["pe_ratio"], 12)
        self.assertEqual(combined["custom_signal"], "hold")
    def test_dynamic_ai_prompt_includes_market_cap_when_available(self):
        records = [
            {"symbol": "AAA", "market_cap": 1_000_000, "ltp": 100},
            {"symbol": "BBB", "market_cap": 5_000_000_000, "ltp": 500},
        ]
        spec = build_dynamic_query_spec(None, records=records)
        self.assertIn("market_cap", spec["allowed_filter_keys"])
        prompt = build_dynamic_ai_system_prompt_from_records(records)
        self.assertIn("market_cap", prompt)
        self.assertIn("low cap", prompt.lower())
        self.assertIn("market_combined", prompt.lower())
        self.assertIn("never use select *", prompt.lower())

    def test_dynamic_ai_prompt_fits_groq_budget_with_large_catalog(self):
        flat_records = []
        for i in range(8):
            row = {
                "symbol": f"SYM{i}",
                "ltp": 100 + i,
                "percent_change": i % 5,
                "qty": 1000 * i,
                "market_cap": 1_000_000 * i,
            }
            for j in range(12):
                row[f"fundamental_metric_{j}"] = float(j)
            for k in range(10):
                row[f"technical_indicator_{k}"] = float(k)
            flat_records.append(row)

        prompt = build_dynamic_ai_system_prompt_from_records(
            flat_records,
            max_chars=GROQ_AI_SYSTEM_PROMPT_MAX_CHARS,
        )
        self.assertLessEqual(len(prompt), GROQ_AI_SYSTEM_PROMPT_MAX_CHARS)
        self.assertIn("symbol, ltp, percent_change, qty", prompt)
        self.assertIn("SEMANTIC MAP", prompt)
        self.assertIn("market_combined", prompt)
        self.assertIn("fundamental_metric_0", prompt)
        self.assertIn("STATUS: OK", prompt)

    def test_validate_market_sql_rejects_select_star_for_ai(self):
        from utils.market_data.sql_screener import MarketSqlError, validate_market_sql_query

        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE market_screener_cache (
                        symbol VARCHAR PRIMARY KEY,
                        combined_data TEXT
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO market_screener_cache (symbol, combined_data)
                    VALUES (:symbol, :combined_data)
                    """
                ),
                {
                    "symbol": "AAA",
                    "combined_data": '{"symbol":"AAA","ltp":100,"pe_ratio":18}',
                },
            )
        Session = sessionmaker(bind=engine)
        db = Session()

        with self.assertRaises(MarketSqlError):
            validate_market_sql_query(
                db,
                "SELECT * FROM market_combined ORDER BY ltp DESC LIMIT 10",
                allow_select_star=False,
            )
        parsed = validate_market_sql_query(
            db,
            "SELECT symbol, ltp, pe_ratio FROM market_combined ORDER BY ltp DESC LIMIT 10",
            allow_select_star=False,
        )
        self.assertTrue(parsed["valid"])
        db.close()

    def test_discover_combined_field_keys_recovers_after_sql_failure(self):
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE market_screener_cache (
                        symbol VARCHAR PRIMARY KEY,
                        combined_data TEXT
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO market_screener_cache (symbol, combined_data)
                    VALUES (:symbol, :combined_data)
                    """
                ),
                {
                    "symbol": "AAA",
                    "combined_data": '{"symbol":"AAA","ltp":100,"pe_ratio":18,"qty":500}',
                },
            )
        Session = sessionmaker(bind=engine)
        db = Session()
        keys = discover_combined_field_keys(db)
        self.assertIn("ltp", keys)
        self.assertIn("pe_ratio", keys)
        self.assertIn("qty", keys)
        db.close()

    def test_ensure_ai_select_injects_symbol_and_basics(self):
        from utils.market_data.sql_screener import _ensure_ai_display_columns

        fixed = _ensure_ai_display_columns(
            "SELECT sector, ltp, technical_rsi_14, technical_macd "
            "FROM market_combined ORDER BY technical_rsi_14 DESC LIMIT 25"
        )
        lowered = fixed.lower()
        self.assertIn("symbol", lowered)
        self.assertIn("percent_change", lowered)
        self.assertIn("qty", lowered)
        self.assertIn("updated_at", lowered)
        self.assertTrue(lowered.index("symbol") < lowered.index("sector"))

    def test_ai_sql_rejects_group_by_with_unaggregated_display_columns(self):
        from utils.market_data.sql_screener import MarketSqlError, validate_market_sql_query

        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE market_screener_cache (
                        symbol VARCHAR PRIMARY KEY,
                        combined_data TEXT
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO market_screener_cache (symbol, combined_data)
                    VALUES (:symbol, :combined_data)
                    """
                ),
                {
                    "symbol": "AAA",
                    "combined_data": '{"symbol":"AAA","ltp":100,"percent_change":-0.2,"qty":500,"updated_at":"2023-02-01"}',
                },
            )
        Session = sessionmaker(bind=engine)
        db = Session()

        with self.assertRaises(MarketSqlError) as ctx:
            validate_market_sql_query(
                db,
                """
                SELECT symbol, ltp, percent_change, qty
                FROM (
                    SELECT symbol, ltp, percent_change, qty, updated_at
                    FROM market_combined
                ) AS market_combined
                WHERE percent_change < -0.1
                GROUP BY symbol, ltp
                HAVING MAX(ABS(percent_change)) < 0.05
                ORDER BY MAX(ABS(percent_change)) DESC
                LIMIT 25
                """,
                allow_select_star=False,
            )
        self.assertIn("Invalid GROUP BY query", str(ctx.exception))
        db.close()

    def test_forbidden_sql_error_explains_exact_syntax(self):
        from utils.market_data.sql_screener import MarketSqlError, validate_market_sql_query

        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE market_screener_cache (
                        symbol VARCHAR PRIMARY KEY,
                        combined_data TEXT
                    )
                    """
                )
            )
        Session = sessionmaker(bind=engine)
        db = Session()

        with self.assertRaises(MarketSqlError) as ctx:
            validate_market_sql_query(
                db,
                """
                SELECT symbol, ltp
                FROM market_combined
                UNION
                SELECT symbol, ltp
                FROM market_combined
                """,
                allow_select_star=False,
            )
        message = str(ctx.exception)
        self.assertIn("UNION is not allowed", message)
        self.assertIn("one simple SELECT", message)
        self.assertIn("SELECT symbol, ltp, percent_change, qty FROM market_combined", message)
        db.close()

    def test_combined_screener_ai_mode_rejects_invalid_group_by_before_execution(self):
        from utils.market_data.sql_screener import MarketSqlError

        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE market_screener_cache (
                        symbol VARCHAR PRIMARY KEY,
                        combined_data TEXT
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO market_screener_cache (symbol, combined_data)
                    VALUES (:symbol, :combined_data)
                    """
                ),
                {
                    "symbol": "AAA",
                    "combined_data": '{"symbol":"AAA","ltp":100,"percent_change":-0.2,"qty":500,"updated_at":"2023-02-01"}',
                },
            )
        Session = sessionmaker(bind=engine)
        db = Session()

        with self.assertRaises(MarketSqlError) as ctx:
            run_combined_screener_from_db(
                db,
                ["AAA"],
                sql="""
                SELECT symbol, ltp, percent_change, qty
                FROM (
                    SELECT symbol, ltp, percent_change, qty, updated_at
                    FROM market_combined
                ) AS market_combined
                WHERE percent_change < -0.1
                GROUP BY symbol, ltp
                HAVING MAX(ABS(percent_change)) < 0.05
                ORDER BY MAX(ABS(percent_change)) DESC
                LIMIT 25
                """,
                allow_select_star=False,
            )
        self.assertIn("Invalid GROUP BY query", str(ctx.exception))
        db.close()

    def test_attach_freshness_metadata_from_cache(self):
        from sqlalchemy import create_engine, text
        from sqlalchemy.orm import sessionmaker

        from utils.market_data.sql_screener import _attach_freshness_metadata

        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE market_screener_cache (
                        symbol TEXT PRIMARY KEY,
                        updated_at TEXT,
                        merolagani_fetched_at TEXT,
                        nepse_alpha_fetched_at TEXT
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO market_screener_cache
                    (symbol, updated_at, merolagani_fetched_at, nepse_alpha_fetched_at)
                    VALUES
                    ('AAA', '2026-06-22T01:00:00', '2026-06-22T01:10:00', '2026-06-22T01:05:00'),
                    ('BBB', NULL, '2026-06-22T02:00:00', NULL)
                    """
                )
            )
        Session = sessionmaker(bind=engine)
        db = Session()
        results = [
            {"symbol": "AAA", "ltp": 100},
            {"symbol": "BBB", "ltp": 50, "updated_at": None},
        ]
        keys = _attach_freshness_metadata(db, results, ["symbol", "ltp"])
        self.assertIn("updated_at", keys)
        self.assertEqual(results[0]["updated_at"], "2026-06-22T01:10:00")
        self.assertEqual(results[1]["updated_at"], "2026-06-22T02:00:00")
        db.close()

    def test_ensure_market_cache_ready_skips_full_enrich_when_populated(self):
        from sqlalchemy import create_engine, text
        from sqlalchemy.orm import sessionmaker

        from utils.market_data.nepse_alpha_bulk import ensure_market_cache_ready

        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE market_screener_cache (
                        symbol TEXT PRIMARY KEY,
                        merolagani_data TEXT,
                        combined_data TEXT,
                        updated_at TEXT
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO market_screener_cache (symbol, merolagani_data, combined_data, updated_at)
                    VALUES (:symbol, :merolagani_data, :combined_data, :updated_at)
                    """
                ),
                {
                    "symbol": "AAA",
                    "merolagani_data": '{"symbol":"AAA","ltp":100}',
                    "combined_data": '{"symbol":"AAA","ltp":100}',
                    "updated_at": "2026-06-22T01:00:00",
                },
            )
        Session = sessionmaker(bind=engine)
        db = Session()
        result = ensure_market_cache_ready(db)
        self.assertEqual(result.get("status"), "ok")
        self.assertEqual(result.get("reason"), "cache_ready")
        db.close()

    def test_ensure_market_cache_ready_reports_empty_without_scraping(self):
        from sqlalchemy import create_engine, text
        from sqlalchemy.orm import sessionmaker

        from utils.market_data.nepse_alpha_bulk import ensure_market_cache_ready

        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE market_screener_cache (
                        symbol TEXT PRIMARY KEY
                    )
                    """
                )
            )
        Session = sessionmaker(bind=engine)
        db = Session()
        result = ensure_market_cache_ready(db)
        self.assertEqual(result.get("status"), "empty")
        self.assertEqual(result.get("symbol_count"), 0)
        db.close()


if __name__ == "__main__":
    unittest.main()
