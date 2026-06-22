"""Tests for pre-built Ask AI quick screens."""

from __future__ import annotations

import json
import unittest

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from utils.market_data.ai_quick_screens import (
    QUICK_AI_SCREENS,
    match_quick_ai_screen,
    normalize_quick_prompt,
)
from utils.market_data.sql_screener import prepare_market_sql


class AiQuickScreensTest(unittest.TestCase):
    def test_has_at_least_fifteen_quick_screens(self):
        self.assertGreaterEqual(len(QUICK_AI_SCREENS), 15)

    def test_match_quick_screen_by_prompt(self):
        screen = match_quick_ai_screen(
            "Find solid commercial banks that trade often and are not too expensive",
        )
        self.assertIsNotNone(screen)
        self.assertEqual(screen["id"], "solid_banks_not_expensive")

    def test_normalize_prompt_ignores_trailing_punctuation(self):
        left = normalize_quick_prompt(
            "Which hydropower stocks are having a good day on the market?",
        )
        right = normalize_quick_prompt(
            "Which hydropower stocks are having a good day on the market",
        )
        self.assertEqual(left, right)

    def test_all_quick_screen_sql_prepares(self):
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
                    "combined_data": json.dumps(
                        {
                            "symbol": "AAA",
                            "ltp": 100,
                            "percent_change": 1.2,
                            "qty": 900,
                            "sector": "Commercial Banks",
                            "pe_ratio": 12,
                            "pbv": 1.1,
                            "eps": 10,
                            "avg_volume_30d": 800,
                            "market_cap": 1_000_000_000,
                            "technical_rsi_14": 38,
                            "technical_macd": "Bullish",
                            "open": 98,
                            "high": 101,
                            "low": 97,
                            "fundamental_roe_ttm": 16,
                            "fundamental_debt_to_equity": 0.7,
                            "alpha_annualized": 12,
                            "sharpe_ratio_annualized": 1.1,
                            "beta_3_month": 0.9,
                            "fundamental_dividend_yield": 3.5,
                            "fundamental_yoy_earnings_growth": 8,
                            "fifty_two_week_high": 120,
                            "position_52_week_pct": 70,
                            "technical_3m_price_tend": "Trending",
                            "technical_sma_10": "below",
                            "technical_sma_20": "below",
                            "technical_sma_50": "above",
                            "current_volume_ratio": 1.1,
                            "volatility_50d": 20,
                            "liquidity_rank": 0.5,
                        }
                    ),
                },
            )
        Session = sessionmaker(bind=engine)
        db = Session()
        for screen in QUICK_AI_SCREENS:
            prepared = prepare_market_sql(db, screen["query_sql"].strip())
            self.assertIn("SELECT", prepared.upper(), screen["id"])
        db.close()


if __name__ == "__main__":
    unittest.main()
