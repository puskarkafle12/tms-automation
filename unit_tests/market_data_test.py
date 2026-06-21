import unittest
from datetime import date, timedelta
from unittest.mock import patch

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from utils.market_data.combined_screener import parse_combined_screener_query, run_combined_screener_from_db
from utils.market_data.canonical_fields import build_combined_record, canonicalize_merolagani_record, ordered_columns_for_source
from utils.market_data.merolagani_fields import flatten_merolagani_row, merge_merolagani_records
from utils.market_data.repository import get_new_symbols, load_latest_daily_stock_rows


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
                VALUES ('BBB', :today, :today, 1)
                """
            ),
            {"today": today},
        )
        db.commit()

        new_symbols = get_new_symbols(db, days=15)
        self.assertEqual([item["symbol"] for item in new_symbols], ["BBB"])

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
            [
                {"field": "ltp", "operator": "gte", "value": 90},
                {"field": "alpha_annualized", "operator": "gte", "value": 10},
            ],
            limit=10,
        )
        self.assertEqual(len(payload["results"]), 1)
        self.assertEqual(payload["results"][0]["symbol"], "AAA")

    def test_parse_combined_query_supports_market_field_aliases(self):
        parsed = parse_combined_screener_query(
            "WHERE pe_ratio <= 25 AND alpha_annualized >= 5 ORDER BY ltp DESC LIMIT 10"
        )
        self.assertEqual(parsed["filters"][0]["field"], "pe_ratio")
        self.assertEqual(parsed["rank_by"], "ltp")

        legacy = parse_combined_screener_query(
            "WHERE ml_pe_ratio <= 25 ORDER BY ml_ltp DESC LIMIT 10"
        )
        self.assertEqual(legacy["filters"][0]["field"], "pe_ratio")
        self.assertEqual(legacy["rank_by"], "ltp")


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


if __name__ == "__main__":
    unittest.main()
