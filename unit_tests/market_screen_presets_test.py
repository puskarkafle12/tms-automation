"""Unit tests for production market screen presets."""

from __future__ import annotations

import json
import unittest
from typing import Any, Dict, List

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from utils.market_data.screen_presets import SCREEN_PRESET_SEEDS
from utils.market_data.sql_screener import prepare_market_sql


def _base_stock(symbol: str, **overrides: Any) -> Dict[str, Any]:
    record: Dict[str, Any] = {
        "symbol": symbol,
        "ltp": 520.0,
        "open": 510.0,
        "high": 530.0,
        "low": 505.0,
        "qty": 1200.0,
        "percent_change": 1.5,
        "market_cap": 8_000_000_000.0,
        "avg_volume_30d": 900.0,
        "sector": "Commercial Banks",
        "eps": 42.0,
        "pe_ratio": 12.0,
        "pbv": 1.6,
        "book_value": 320.0,
        "one_year_yield": 10.0,
        "fifty_two_week_high": 620.0,
        "fifty_two_week_low": 420.0,
        "alpha_annualized": 28.0,
        "beta_3_month": 0.95,
        "sharpe_ratio_annualized": 1.4,
        "volatility_50d": 18.0,
        "daily_var_95": -2.2,
        "fundamental_roe_ttm": 16.0,
        "fundamental_roa_ttm": 1.8,
        "fundamental_yoy_earnings_growth": 14.0,
        "fundamental_qoq_earnings_growth": 12.0,
        "fundamental_debt_to_equity": 0.8,
        "fundamental_debt_to_equity_sector_high": 1.2,
        "fundamental_distance_from_graham_number": 85.0,
        "fundamental_peg_3_5_yrs": 0.9,
        "fundamental_dividend_yield": 4.0,
        "fundamental_payout_ratio": 45.0,
        "technical_macd": "Bullish",
        "technical_sma_10": "below",
        "technical_sma_20": "above",
        "technical_sma_50": "above",
        "technical_sma_200": "above",
        "technical_rsi_14": 58.0,
        "technical_mfi_14": 62.0,
        "technical_stochastic_14": 48.0,
        "technical_percent_b": 72.0,
        "technical_price_relative_strength": 62.0,
        "technical_volume_trend": "Trending Up",
        "technical_3m_price_tend": "Trending",
    }
    record.update(overrides)
    return record


def _sample_universe() -> List[Dict[str, Any]]:
    return [
        _base_stock("BANK1"),
        _base_stock(
            "BANK2",
            ltp=480.0,
            open=470.0,
            percent_change=2.1,
            pe_ratio=9.0,
            pbv=1.1,
            market_cap=12_000_000_000.0,
            avg_volume_30d=1500.0,
            fundamental_roe_ttm=18.0,
            fundamental_yoy_earnings_growth=20.0,
            fundamental_qoq_earnings_growth=15.0,
            alpha_annualized=35.0,
            beta_3_month=0.75,
            volatility_50d=12.0,
            daily_var_95=-1.5,
        ),
        _base_stock(
            "MICRO1",
            sector="Microfinance",
            market_cap=2_500_000_000.0,
            avg_volume_30d=650.0,
            pe_ratio=18.0,
            pbv=2.2,
            fundamental_debt_to_equity=0.5,
        ),
        _base_stock(
            "MOMO1",
            sector="Finance",
            ltp=610.0,
            open=600.0,
            percent_change=2.8,
            qty=1800.0,
            avg_volume_30d=1200.0,
            position_override=True,
            fifty_two_week_high=620.0,
            fifty_two_week_low=400.0,
            technical_rsi_14=61.0,
            technical_percent_b=90.0,
            alpha_annualized=40.0,
        ),
        _base_stock(
            "PULL1",
            sector="Finance",
            technical_3m_price_tend="Trending",
            technical_sma_10="below",
            technical_sma_20="below",
            technical_sma_50="above",
            technical_sma_200="above",
            technical_macd="Bearish",
            technical_rsi_14=44.0,
            technical_stochastic_14=28.0,
            technical_percent_b=35.0,
            percent_change=-0.8,
            qty=1800.0,
            avg_volume_30d=1400.0,
            market_cap=11_000_000_000.0,
        ),
        _base_stock(
            "REV1",
            sector="Hydropower",
            ltp=405.0,
            open=398.0,
            percent_change=1.2,
            technical_rsi_14=36.0,
            technical_stochastic_14=22.0,
            technical_percent_b=18.0,
            technical_mfi_14=38.0,
            technical_macd="Bullish",
            qty=900.0,
            avg_volume_30d=1000.0,
            market_cap=3_000_000_000.0,
        ),
        _base_stock(
            "VOL1",
            sector="Manufacturing And Processing",
            beta_3_month=1.35,
            volatility_50d=28.0,
            percent_change=4.5,
            avg_volume_30d=1100.0,
            qty=2000.0,
            technical_rsi_14=68.0,
        ),
        _base_stock(
            "DIV1",
            sector="Life Insurance",
            fundamental_dividend_yield=6.0,
            fundamental_payout_ratio=42.0,
            fundamental_roe_ttm=14.0,
        ),
        _base_stock(
            "GARP1",
            sector="Non Life Insurance",
            fundamental_peg_3_5_yrs=0.7,
            fundamental_yoy_earnings_growth=18.0,
            fundamental_qoq_earnings_growth=6.0,
            pe_ratio=16.0,
        ),
        _base_stock(
            "VAL1",
            sector="Development Bank Limited",
            pe_ratio=8.0,
            pbv=0.9,
            fundamental_distance_from_graham_number=-18.0,
            fundamental_roe_ttm=11.0,
            fundamental_yoy_earnings_growth=5.0,
        ),
    ]


class MarketScreenPresetsTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE market_screener_cache (
                        symbol VARCHAR PRIMARY KEY,
                        merolagani_data TEXT,
                        nepse_alpha_data TEXT,
                        combined_data TEXT,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
        self.Session = sessionmaker(bind=self.engine)
        db = self.Session()
        for record in _sample_universe():
            if record.pop("position_override", False):
                record["fifty_two_week_high"] = 620.0
                record["fifty_two_week_low"] = 400.0
                record["ltp"] = 610.0
            db.execute(
                text(
                    """
                    INSERT INTO market_screener_cache (symbol, combined_data)
                    VALUES (:symbol, :combined_data)
                    """
                ),
                {
                    "symbol": record["symbol"],
                    "combined_data": json.dumps(record),
                },
            )
        db.commit()
        db.close()

    def test_all_builtin_presets_return_results(self):
        db = self.Session()
        failures: List[str] = []
        for preset in SCREEN_PRESET_SEEDS:
            prepared = prepare_market_sql(db, preset["query_sql"].strip())
            rows = db.execute(text(prepared)).mappings().all()
            matched = len(rows)
            if matched == 0:
                failures.append(preset["preset_code"])
            self.assertGreater(
                matched,
                0,
                f"Preset {preset['preset_code']} returned zero rows",
            )
            if "preset_score" in preset["query_sql"].lower():
                self.assertIn("preset_score", dict(rows[0]))
        db.close()
        self.assertEqual(failures, [])

    def test_screen_view_excludes_mutual_fund_sector(self):
        db = self.Session()
        db.execute(
            text(
                """
                INSERT INTO market_screener_cache (symbol, combined_data)
                VALUES ('MF1', :combined_data)
                """
            ),
            {
                "combined_data": json.dumps(
                    _base_stock(
                        "MF1",
                        sector="Mutual Fund",
                        market_cap=1_000_000_000.0,
                        avg_volume_30d=500.0,
                    )
                ),
            },
        )
        db.commit()
        preset = next(p for p in SCREEN_PRESET_SEEDS if p["preset_code"] == "quality_compounders")
        prepared = prepare_market_sql(db, preset["query_sql"].strip())
        rows = db.execute(text(prepared)).mappings().all()
        symbols = {row["symbol"] for row in rows}
        self.assertNotIn("MF1", symbols)
        db.close()


if __name__ == "__main__":
    unittest.main()
