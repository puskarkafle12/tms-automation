import unittest

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from database import ensure_read_session
from utils.market_data.dynamic_catalog import discover_combined_field_keys


class DbSessionTest(unittest.TestCase):
    def test_ensure_read_session_recovers_after_failed_sql(self):
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
        with self.assertRaises(Exception):
            db.execute(text("SELECT missing_column FROM market_screener_cache"))

        ensure_read_session(db)
        keys = discover_combined_field_keys(db)
        self.assertIn("ltp", keys)
        self.assertIn("pe_ratio", keys)
        db.close()


if __name__ == "__main__":
    unittest.main()
