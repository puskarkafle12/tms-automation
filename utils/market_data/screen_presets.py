"""Production NEPSE stock/trader screen presets backed by v_nepse_stock_screen."""

from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy import text
from sqlalchemy.orm import Session

from utils.market_data.screen_view import SCREEN_VIEW_NAME

PRESET_VIEW = SCREEN_VIEW_NAME

SCREEN_PRESET_SEEDS: List[Dict[str, Any]] = [
    {
        "preset_code": "quality_compounders",
        "preset_name": "Quality Compounders",
        "category": "INVESTOR",
        "risk_level": "MEDIUM",
        "time_horizon": "6–24 months",
        "description": "Strong profitability, positive earnings and acceptable valuation.",
        "display_order": 1,
        "query_sql": """
WITH ranked AS (
    SELECT
        s.*,
        PERCENT_RANK() OVER (PARTITION BY sector ORDER BY fundamental_roe_ttm) AS roe_rank,
        PERCENT_RANK() OVER (PARTITION BY sector ORDER BY fundamental_roa_ttm) AS roa_rank,
        PERCENT_RANK() OVER (PARTITION BY sector ORDER BY fundamental_yoy_earnings_growth) AS yoy_growth_rank,
        PERCENT_RANK() OVER (PARTITION BY sector ORDER BY fundamental_qoq_earnings_growth) AS qoq_growth_rank,
        PERCENT_RANK() OVER (PARTITION BY sector ORDER BY pe_ratio DESC) AS pe_value_rank,
        PERCENT_RANK() OVER (ORDER BY sharpe_ratio_annualized) AS sharpe_rank
    FROM v_nepse_stock_screen s
    WHERE eps > 0
      AND fundamental_roe_ttm >= 8
      AND fundamental_roa_ttm > 0
      AND fundamental_yoy_earnings_growth >= -10
      AND fundamental_qoq_earnings_growth >= -20
      AND pe_ratio BETWEEN 3 AND 50
      AND pbv BETWEEN 0.20 AND 8
      AND liquidity_rank >= 0.25
      AND (
          sector IN (
              'Commercial Banks', 'Development Bank Limited', 'Finance',
              'Microfinance', 'Life Insurance', 'Non Life Insurance'
          )
          OR fundamental_debt_to_equity IS NULL
          OR fundamental_debt_to_equity <= fundamental_debt_to_equity_sector_high * 0.75
      )
)
SELECT
    symbol, sector, ltp, market_cap, avg_volume_30d, eps, pe_ratio, pbv,
    fundamental_roe_ttm, fundamental_roa_ttm, fundamental_yoy_earnings_growth,
    fundamental_qoq_earnings_growth, sharpe_ratio_annualized,
    ROUND((
        100.0 * (
            roe_rank * 0.25 + roa_rank * 0.15 + yoy_growth_rank * 0.20 +
            qoq_growth_rank * 0.10 + pe_value_rank * 0.15 + sharpe_rank * 0.15
        )
    )::numeric, 2) AS preset_score
FROM ranked
ORDER BY preset_score DESC
LIMIT 25
""",
    },
    {
        "preset_code": "quality_value",
        "preset_name": "Quality Value",
        "category": "INVESTOR",
        "risk_level": "MEDIUM",
        "time_horizon": "6–18 months",
        "description": "Lower PE and PBV, excluding loss-making value traps.",
        "display_order": 2,
        "query_sql": """
WITH ranked AS (
    SELECT
        s.*,
        PERCENT_RANK() OVER (PARTITION BY sector ORDER BY pe_ratio DESC) AS pe_value_rank,
        PERCENT_RANK() OVER (PARTITION BY sector ORDER BY pbv DESC) AS pbv_value_rank,
        PERCENT_RANK() OVER (PARTITION BY sector ORDER BY fundamental_distance_from_graham_number DESC) AS graham_value_rank,
        PERCENT_RANK() OVER (PARTITION BY sector ORDER BY fundamental_roe_ttm) AS roe_rank,
        PERCENT_RANK() OVER (PARTITION BY sector ORDER BY fundamental_yoy_earnings_growth) AS growth_rank
    FROM v_nepse_stock_screen s
    WHERE eps > 0
      AND pe_ratio BETWEEN 2 AND 30
      AND pbv BETWEEN 0.20 AND 4
      AND fundamental_roe_ttm >= 5
      AND fundamental_yoy_earnings_growth >= -20
      AND fundamental_distance_from_graham_number IS NOT NULL
      AND liquidity_rank >= 0.20
)
SELECT
    symbol, sector, ltp, eps, pe_ratio, pbv, book_value,
    fundamental_distance_from_graham_number, fundamental_roe_ttm,
    fundamental_yoy_earnings_growth, avg_volume_30d,
    ROUND((
        100.0 * (
            pe_value_rank * 0.30 + pbv_value_rank * 0.25 + graham_value_rank * 0.20 +
            roe_rank * 0.15 + growth_rank * 0.10
        )
    )::numeric, 2) AS preset_score
FROM ranked
ORDER BY preset_score DESC
LIMIT 25
""",
    },
    {
        "preset_code": "growth_at_reasonable_price",
        "preset_name": "Growth at a Reasonable Price",
        "category": "INVESTOR",
        "risk_level": "MEDIUM_HIGH",
        "time_horizon": "6–24 months",
        "description": "Growing companies whose valuation is not excessively high.",
        "display_order": 3,
        "query_sql": """
WITH ranked AS (
    SELECT
        s.*,
        PERCENT_RANK() OVER (PARTITION BY sector ORDER BY fundamental_peg_3_5_yrs DESC) AS peg_value_rank,
        PERCENT_RANK() OVER (PARTITION BY sector ORDER BY fundamental_yoy_earnings_growth) AS yoy_growth_rank,
        PERCENT_RANK() OVER (PARTITION BY sector ORDER BY fundamental_qoq_earnings_growth) AS qoq_growth_rank,
        PERCENT_RANK() OVER (PARTITION BY sector ORDER BY fundamental_roe_ttm) AS roe_rank,
        PERCENT_RANK() OVER (ORDER BY sharpe_ratio_annualized) AS sharpe_rank
    FROM v_nepse_stock_screen s
    WHERE eps > 0
      AND fundamental_peg_3_5_yrs BETWEEN 0.10 AND 2.50
      AND fundamental_yoy_earnings_growth >= 8
      AND fundamental_qoq_earnings_growth >= 0
      AND fundamental_roe_ttm >= 8
      AND pe_ratio BETWEEN 3 AND 45
      AND liquidity_rank >= 0.20
)
SELECT
    symbol, sector, ltp, eps, pe_ratio, fundamental_peg_3_5_yrs,
    fundamental_roe_ttm, fundamental_yoy_earnings_growth, fundamental_qoq_earnings_growth,
    sharpe_ratio_annualized,
    ROUND((
        100.0 * (
            peg_value_rank * 0.25 + yoy_growth_rank * 0.25 + qoq_growth_rank * 0.20 +
            roe_rank * 0.20 + sharpe_rank * 0.10
        )
    )::numeric, 2) AS preset_score
FROM ranked
ORDER BY preset_score DESC
LIMIT 25
""",
    },
    {
        "preset_code": "sustainable_dividend",
        "preset_name": "Sustainable Dividend",
        "category": "INVESTOR",
        "risk_level": "LOW_MEDIUM",
        "time_horizon": "12–36 months",
        "description": "Dividend stocks with positive earnings and manageable payout ratio.",
        "display_order": 4,
        "query_sql": """
WITH ranked AS (
    SELECT
        s.*,
        PERCENT_RANK() OVER (PARTITION BY sector ORDER BY fundamental_dividend_yield) AS dividend_rank,
        PERCENT_RANK() OVER (PARTITION BY sector ORDER BY fundamental_roe_ttm) AS roe_rank,
        PERCENT_RANK() OVER (PARTITION BY sector ORDER BY fundamental_yoy_earnings_growth) AS growth_rank,
        PERCENT_RANK() OVER (ORDER BY sharpe_ratio_annualized) AS sharpe_rank
    FROM v_nepse_stock_screen s
    WHERE eps > 0
      AND fundamental_dividend_yield BETWEEN 1.50 AND 15
      AND fundamental_payout_ratio BETWEEN 10 AND 85
      AND fundamental_roe_ttm >= 8
      AND fundamental_yoy_earnings_growth >= -10
      AND liquidity_rank >= 0.20
)
SELECT
    symbol, sector, ltp, eps, pe_ratio, fundamental_dividend_yield,
    fundamental_payout_ratio, fundamental_roe_ttm, fundamental_yoy_earnings_growth,
    sharpe_ratio_annualized,
    ROUND((
        100.0 * (
            dividend_rank * 0.35 +
            GREATEST(0, 1 - ABS(fundamental_payout_ratio - 50) / 50.0) * 0.20 +
            roe_rank * 0.20 + growth_rank * 0.15 + sharpe_rank * 0.10
        )
    )::numeric, 2) AS preset_score
FROM ranked
ORDER BY preset_score DESC
LIMIT 25
""",
    },
    {
        "preset_code": "earnings_acceleration",
        "preset_name": "Earnings Acceleration",
        "category": "INVESTOR",
        "risk_level": "MEDIUM_HIGH",
        "time_horizon": "3–12 months",
        "description": "Companies with both quarterly and yearly earnings growth.",
        "display_order": 5,
        "query_sql": """
WITH ranked AS (
    SELECT
        s.*,
        PERCENT_RANK() OVER (PARTITION BY sector ORDER BY fundamental_qoq_earnings_growth) AS qoq_rank,
        PERCENT_RANK() OVER (PARTITION BY sector ORDER BY fundamental_yoy_earnings_growth) AS yoy_rank,
        PERCENT_RANK() OVER (PARTITION BY sector ORDER BY fundamental_roe_ttm) AS roe_rank,
        PERCENT_RANK() OVER (ORDER BY sharpe_ratio_annualized) AS sharpe_rank,
        PERCENT_RANK() OVER (PARTITION BY sector ORDER BY technical_price_relative_strength) AS strength_rank
    FROM v_nepse_stock_screen s
    WHERE eps > 0
      AND fundamental_qoq_earnings_growth >= 10
      AND fundamental_yoy_earnings_growth >= 10
      AND fundamental_roe_ttm >= 8
      AND pe_ratio BETWEEN 3 AND 60
      AND liquidity_rank >= 0.20
)
SELECT
    symbol, sector, ltp, eps, pe_ratio, fundamental_qoq_earnings_growth,
    fundamental_yoy_earnings_growth, fundamental_roe_ttm, technical_price_relative_strength,
    sharpe_ratio_annualized,
    ROUND((
        100.0 * (
            qoq_rank * 0.30 + yoy_rank * 0.30 + roe_rank * 0.20 +
            strength_rank * 0.10 + sharpe_rank * 0.10
        )
    )::numeric, 2) AS preset_score
FROM ranked
ORDER BY preset_score DESC
LIMIT 25
""",
    },
    {
        "preset_code": "defensive_large_liquid",
        "preset_name": "Defensive Large and Liquid",
        "category": "INVESTOR",
        "risk_level": "LOW",
        "time_horizon": "12–36 months",
        "description": "Larger, liquid and relatively lower-risk stocks.",
        "display_order": 6,
        "query_sql": """
WITH ranked AS (
    SELECT
        s.*,
        PERCENT_RANK() OVER (ORDER BY sharpe_ratio_annualized) AS sharpe_rank,
        PERCENT_RANK() OVER (ORDER BY one_year_yield) AS yield_rank
    FROM v_nepse_stock_screen s
    WHERE market_cap_rank >= 0.60
      AND liquidity_rank >= 0.40
      AND beta_3_month BETWEEN 0.10 AND 1.05
      AND volatility_50d IS NOT NULL
      AND daily_var_95 IS NOT NULL
      AND sharpe_ratio_annualized > 0
      AND eps > 0
      AND fundamental_yoy_earnings_growth >= -20
)
SELECT
    symbol, sector, ltp, market_cap, avg_volume_30d, beta_3_month,
    volatility_50d, daily_var_95, sharpe_ratio_annualized, one_year_yield,
    ROUND((
        100.0 * (
            (1 - volatility_rank) * 0.25 + (1 - var_risk_rank) * 0.15 +
            sharpe_rank * 0.25 + market_cap_rank * 0.15 + liquidity_rank * 0.10 +
            GREATEST(0, 1 - ABS(beta_3_month - 0.70) / 0.70) * 0.10
        )
    )::numeric, 2) AS preset_score
FROM ranked
ORDER BY preset_score DESC
LIMIT 25
""",
    },
    {
        "preset_code": "liquid_bullish_momentum",
        "preset_name": "Liquid Bullish Momentum",
        "category": "TRADER",
        "risk_level": "HIGH",
        "time_horizon": "Several days to 6 weeks",
        "description": "Stocks in a confirmed bullish trend with liquidity.",
        "display_order": 11,
        "query_sql": """
WITH ranked AS (
    SELECT
        s.*,
        PERCENT_RANK() OVER (PARTITION BY sector ORDER BY technical_price_relative_strength) AS strength_rank,
        PERCENT_RANK() OVER (ORDER BY alpha_annualized) AS alpha_rank,
        PERCENT_RANK() OVER (ORDER BY current_volume_ratio) AS volume_rank,
        PERCENT_RANK() OVER (ORDER BY percent_change) AS change_rank
    FROM v_nepse_stock_screen s
    WHERE LOWER(technical_macd) = 'bullish'
      AND LOWER(technical_sma_20) = 'above'
      AND LOWER(technical_sma_50) = 'above'
      AND technical_rsi_14 BETWEEN 50 AND 72
      AND technical_mfi_14 BETWEEN 40 AND 82
      AND LOWER(technical_volume_trend) = 'trending up'
      AND technical_price_relative_strength >= 45
      AND liquidity_rank >= 0.55
      AND current_volume_ratio >= 0.30
)
SELECT
    symbol, sector, ltp, percent_change, qty, avg_volume_30d, current_volume_ratio,
    technical_rsi_14, technical_mfi_14, technical_macd, technical_price_relative_strength,
    alpha_annualized,
    ROUND((
        100.0 * (
            strength_rank * 0.30 + alpha_rank * 0.20 + volume_rank * 0.25 +
            change_rank * 0.10 +
            GREATEST(0, 1 - ABS(technical_rsi_14 - 60) / 20.0) * 0.15
        )
    )::numeric, 2) AS preset_score
FROM ranked
ORDER BY preset_score DESC
LIMIT 25
""",
    },
    {
        "preset_code": "breakout_ready",
        "preset_name": "Breakout Ready",
        "category": "TRADER",
        "risk_level": "HIGH",
        "time_horizon": "1 day to 4 weeks",
        "description": "Stocks near 52-week high with volume and trend confirmation.",
        "display_order": 12,
        "query_sql": """
WITH ranked AS (
    SELECT
        s.*,
        PERCENT_RANK() OVER (ORDER BY position_52_week_pct) AS breakout_rank,
        PERCENT_RANK() OVER (ORDER BY current_volume_ratio) AS volume_rank,
        PERCENT_RANK() OVER (PARTITION BY sector ORDER BY technical_price_relative_strength) AS strength_rank,
        PERCENT_RANK() OVER (ORDER BY alpha_annualized) AS alpha_rank
    FROM v_nepse_stock_screen s
    WHERE position_52_week_pct BETWEEN 80 AND 105
      AND LOWER(technical_macd) = 'bullish'
      AND LOWER(technical_sma_20) = 'above'
      AND LOWER(technical_sma_50) = 'above'
      AND technical_percent_b BETWEEN 75 AND 115
      AND technical_rsi_14 BETWEEN 52 AND 75
      AND LOWER(technical_volume_trend) = 'trending up'
      AND liquidity_rank >= 0.60
      AND current_volume_ratio >= 0.50
)
SELECT
    symbol, sector, ltp, fifty_two_week_high, position_52_week_pct, percent_change,
    qty, avg_volume_30d, current_volume_ratio, technical_percent_b, technical_rsi_14,
    technical_price_relative_strength, alpha_annualized,
    ROUND((
        100.0 * (
            breakout_rank * 0.30 + volume_rank * 0.30 +
            strength_rank * 0.25 + alpha_rank * 0.15
        )
    )::numeric, 2) AS preset_score
FROM ranked
ORDER BY preset_score DESC
LIMIT 25
""",
    },
    {
        "preset_code": "trend_pullback",
        "preset_name": "Trend Pullback",
        "category": "TRADER",
        "risk_level": "MEDIUM_HIGH",
        "time_horizon": "Several days to 8 weeks",
        "description": "Pullback while the larger trend remains bullish.",
        "display_order": 13,
        "query_sql": """
WITH ranked AS (
    SELECT
        s.*,
        PERCENT_RANK() OVER (PARTITION BY sector ORDER BY technical_price_relative_strength) AS strength_rank,
        PERCENT_RANK() OVER (ORDER BY alpha_annualized) AS alpha_rank,
        PERCENT_RANK() OVER (ORDER BY current_volume_ratio) AS volume_rank
    FROM v_nepse_stock_screen s
    WHERE LOWER(technical_3m_price_tend) = 'trending'
      AND LOWER(technical_macd) IN ('bullish', 'neutral')
      AND LOWER(technical_sma_50) = 'above'
      AND LOWER(technical_sma_200) = 'above'
      AND (
          LOWER(technical_sma_10) = 'below'
          OR LOWER(technical_sma_20) = 'below'
      )
      AND technical_rsi_14 BETWEEN 35 AND 62
      AND technical_stochastic_14 BETWEEN 15 AND 55
      AND technical_percent_b BETWEEN 10 AND 60
      AND liquidity_rank >= 0.35
      AND current_volume_ratio >= 0.20
)
SELECT
    symbol, sector, ltp, percent_change, technical_3m_price_tend, technical_macd,
    technical_rsi_14, technical_stochastic_14, technical_percent_b,
    technical_sma_20, technical_sma_50, technical_sma_200,
    technical_price_relative_strength, current_volume_ratio,
    ROUND((
        100.0 * (
            strength_rank * 0.35 + alpha_rank * 0.20 + volume_rank * 0.20 +
            CASE WHEN LOWER(technical_macd) = 'bullish' THEN 1 ELSE 0 END * 0.15 +
            GREATEST(0, 1 - ABS(technical_rsi_14 - 45) / 15.0) * 0.10
        )
    )::numeric, 2) AS preset_score
FROM ranked
ORDER BY preset_score DESC
LIMIT 25
""",
    },
    {
        "preset_code": "confirmed_oversold_reversal",
        "preset_name": "Confirmed Oversold Reversal",
        "category": "TRADER",
        "risk_level": "HIGH",
        "time_horizon": "1 day to 4 weeks",
        "description": "Oversold stocks recovering with price and volume confirmation.",
        "display_order": 14,
        "query_sql": """
WITH ranked AS (
    SELECT
        s.*,
        PERCENT_RANK() OVER (ORDER BY current_volume_ratio) AS volume_rank,
        PERCENT_RANK() OVER (ORDER BY percent_change) AS recovery_rank,
        PERCENT_RANK() OVER (PARTITION BY sector ORDER BY technical_price_relative_strength) AS strength_rank
    FROM v_nepse_stock_screen s
    WHERE technical_rsi_14 BETWEEN 25 AND 43
      AND technical_stochastic_14 <= 35
      AND technical_percent_b <= 30
      AND technical_mfi_14 <= 45
      AND percent_change > 0
      AND (ltp >= open OR percent_change >= 0.5)
      AND LOWER(technical_volume_trend) != 'trending down'
      AND liquidity_rank >= 0.15
      AND current_volume_ratio >= 0.25
)
SELECT
    symbol, sector, ltp, open, percent_change, qty, avg_volume_30d, current_volume_ratio,
    technical_macd, technical_rsi_14, technical_stochastic_14, technical_percent_b,
    technical_mfi_14,
    ROUND((
        100.0 * (
            volume_rank * 0.35 + recovery_rank * 0.30 + strength_rank * 0.15 +
            CASE WHEN LOWER(technical_macd) = 'bullish' THEN 1 ELSE 0 END * 0.20
        )
    )::numeric, 2) AS preset_score
FROM ranked
ORDER BY preset_score DESC
LIMIT 25
""",
    },
    {
        "preset_code": "alpha_swing_leaders",
        "preset_name": "Alpha Swing Leaders",
        "category": "TRADER",
        "risk_level": "MEDIUM_HIGH",
        "time_horizon": "1–8 weeks",
        "description": "Risk-adjusted outperformers with technical strength.",
        "display_order": 15,
        "query_sql": """
WITH ranked AS (
    SELECT
        s.*,
        PERCENT_RANK() OVER (ORDER BY alpha_annualized) AS alpha_rank,
        PERCENT_RANK() OVER (ORDER BY sharpe_ratio_annualized) AS sharpe_rank,
        PERCENT_RANK() OVER (PARTITION BY sector ORDER BY technical_price_relative_strength) AS strength_rank
    FROM v_nepse_stock_screen s
    WHERE alpha_annualized > 0
      AND sharpe_ratio_annualized > 0
      AND beta_3_month BETWEEN 0.40 AND 1.80
      AND technical_price_relative_strength >= 45
      AND technical_rsi_14 BETWEEN 45 AND 72
      AND LOWER(technical_sma_50) = 'above'
      AND liquidity_rank >= 0.45
)
SELECT
    symbol, sector, ltp, percent_change, alpha_annualized, sharpe_ratio_annualized,
    beta_3_month, technical_price_relative_strength, technical_rsi_14,
    avg_volume_30d, liquidity_rank,
    ROUND((
        100.0 * (
            alpha_rank * 0.35 + sharpe_rank * 0.25 +
            strength_rank * 0.25 + liquidity_rank * 0.15
        )
    )::numeric, 2) AS preset_score
FROM ranked
ORDER BY preset_score DESC
LIMIT 25
""",
    },
    {
        "preset_code": "liquid_high_volatility_traders",
        "preset_name": "Liquid High-Volatility Traders",
        "category": "TRADER",
        "risk_level": "VERY_HIGH",
        "time_horizon": "Intraday to several weeks",
        "description": "Fast-moving stocks with enough liquidity for active traders.",
        "display_order": 16,
        "query_sql": """
WITH ranked AS (
    SELECT
        s.*,
        PERCENT_RANK() OVER (ORDER BY beta_3_month) AS beta_rank,
        PERCENT_RANK() OVER (ORDER BY current_volume_ratio) AS volume_rank,
        PERCENT_RANK() OVER (ORDER BY ABS(percent_change)) AS movement_rank
    FROM v_nepse_stock_screen s
    WHERE volatility_rank >= 0.80
      AND beta_3_month >= 1.05
      AND liquidity_rank >= 0.60
      AND current_volume_ratio >= 0.50
      AND technical_rsi_14 BETWEEN 35 AND 78
)
SELECT
    symbol, sector, ltp, percent_change, volatility_50d, beta_3_month, daily_var_95,
    qty, avg_volume_30d, current_volume_ratio, technical_rsi_14, technical_macd,
    ROUND((
        100.0 * (
            volatility_rank * 0.35 + beta_rank * 0.15 +
            volume_rank * 0.30 + movement_rank * 0.20
        )
    )::numeric, 2) AS preset_score
FROM ranked
ORDER BY preset_score DESC
LIMIT 25
""",
    },
    {
        "preset_code": "high_roe_leaders",
        "preset_name": "High ROE Leaders",
        "category": "INVESTOR",
        "risk_level": "MEDIUM",
        "time_horizon": "6–18 months",
        "description": "Top return-on-equity names with positive earnings.",
        "display_order": 7,
        "query_sql": """
WITH ranked AS (
    SELECT s.*,
        PERCENT_RANK() OVER (PARTITION BY sector ORDER BY fundamental_roe_ttm) AS roe_rank,
        PERCENT_RANK() OVER (ORDER BY sharpe_ratio_annualized) AS sharpe_rank
    FROM v_nepse_stock_screen s
    WHERE eps > 0 AND fundamental_roe_ttm >= 12 AND pe_ratio BETWEEN 3 AND 45
      AND liquidity_rank >= 0.20
)
SELECT symbol, sector, ltp, pe_ratio, pbv, eps, fundamental_roe_ttm, fundamental_roa_ttm,
       sharpe_ratio_annualized,
       ROUND((100.0 * (roe_rank * 0.70 + sharpe_rank * 0.30))::numeric, 2) AS preset_score
FROM ranked ORDER BY preset_score DESC LIMIT 25
""",
    },
    {
        "preset_code": "low_debt_quality",
        "preset_name": "Low Debt Quality",
        "category": "INVESTOR",
        "risk_level": "LOW_MEDIUM",
        "time_horizon": "12–24 months",
        "description": "Manageable leverage with solid profitability.",
        "display_order": 8,
        "query_sql": """
WITH ranked AS (
    SELECT s.*,
        PERCENT_RANK() OVER (PARTITION BY sector ORDER BY fundamental_debt_to_equity DESC) AS debt_rank,
        PERCENT_RANK() OVER (PARTITION BY sector ORDER BY fundamental_roe_ttm) AS roe_rank
    FROM v_nepse_stock_screen s
    WHERE eps > 0 AND fundamental_debt_to_equity IS NOT NULL
      AND fundamental_debt_to_equity <= 1
      AND fundamental_roe_ttm >= 10 AND liquidity_rank >= 0.20
)
SELECT symbol, sector, ltp, pe_ratio, eps, fundamental_debt_to_equity, fundamental_roe_ttm,
       market_cap, avg_volume_30d,
       ROUND((100.0 * (debt_rank * 0.55 + roe_rank * 0.45))::numeric, 2) AS preset_score
FROM ranked ORDER BY preset_score DESC LIMIT 25
""",
    },
    {
        "preset_code": "graham_deep_value",
        "preset_name": "Graham Deep Value",
        "category": "INVESTOR",
        "risk_level": "MEDIUM",
        "time_horizon": "6–18 months",
        "description": "Stocks trading below Graham-number distance with positive EPS.",
        "display_order": 9,
        "query_sql": """
WITH ranked AS (
    SELECT s.*,
        PERCENT_RANK() OVER (PARTITION BY sector ORDER BY fundamental_distance_from_graham_number DESC) AS graham_rank,
        PERCENT_RANK() OVER (PARTITION BY sector ORDER BY pe_ratio DESC) AS pe_rank
    FROM v_nepse_stock_screen s
    WHERE eps > 0 AND pe_ratio BETWEEN 2 AND 20 AND pbv <= 3
      AND fundamental_distance_from_graham_number IS NOT NULL
      AND fundamental_distance_from_graham_number >= 80 AND liquidity_rank >= 0.15
)
SELECT symbol, sector, ltp, eps, pe_ratio, pbv, book_value,
       fundamental_distance_from_graham_number, market_cap,
       ROUND((100.0 * (graham_rank * 0.60 + pe_rank * 0.40))::numeric, 2) AS preset_score
FROM ranked ORDER BY preset_score DESC LIMIT 25
""",
    },
    {
        "preset_code": "dividend_growth_combo",
        "preset_name": "Dividend + Growth",
        "category": "INVESTOR",
        "risk_level": "MEDIUM",
        "time_horizon": "12–36 months",
        "description": "Income names with positive earnings growth.",
        "display_order": 10,
        "query_sql": """
WITH ranked AS (
    SELECT s.*,
        PERCENT_RANK() OVER (PARTITION BY sector ORDER BY fundamental_dividend_yield) AS div_rank,
        PERCENT_RANK() OVER (PARTITION BY sector ORDER BY fundamental_yoy_earnings_growth) AS growth_rank
    FROM v_nepse_stock_screen s
    WHERE eps > 0 AND fundamental_dividend_yield >= 2
      AND fundamental_yoy_earnings_growth >= 5
      AND fundamental_payout_ratio <= 85 AND liquidity_rank >= 0.15
)
SELECT symbol, sector, ltp, eps, pe_ratio, fundamental_dividend_yield, fundamental_payout_ratio,
       fundamental_yoy_earnings_growth, market_cap,
       ROUND((100.0 * (div_rank * 0.55 + growth_rank * 0.45))::numeric, 2) AS preset_score
FROM ranked ORDER BY preset_score DESC LIMIT 25
""",
    },
    {
        "preset_code": "rsi_momentum_runners",
        "preset_name": "RSI Momentum Runners",
        "category": "TRADER",
        "risk_level": "HIGH",
        "time_horizon": "Several days to 4 weeks",
        "description": "Strong RSI zone with bullish MACD and volume.",
        "display_order": 17,
        "query_sql": """
WITH ranked AS (
    SELECT s.*,
        PERCENT_RANK() OVER (ORDER BY percent_change) AS move_rank,
        PERCENT_RANK() OVER (ORDER BY current_volume_ratio) AS vol_rank
    FROM v_nepse_stock_screen s
    WHERE technical_rsi_14 BETWEEN 55 AND 72
      AND LOWER(technical_macd) = 'bullish'
      AND LOWER(technical_sma_20) = 'above'
      AND liquidity_rank >= 0.40 AND current_volume_ratio >= 0.30
)
SELECT symbol, sector, ltp, percent_change, qty, avg_volume_30d, technical_rsi_14,
       technical_macd, technical_sma_20, alpha_annualized,
       ROUND((100.0 * (move_rank * 0.55 + vol_rank * 0.45))::numeric, 2) AS preset_score
FROM ranked ORDER BY preset_score DESC LIMIT 25
""",
    },
    {
        "preset_code": "sma_bullish_alignment",
        "preset_name": "SMA Bullish Alignment",
        "category": "TRADER",
        "risk_level": "MEDIUM_HIGH",
        "time_horizon": "1–6 weeks",
        "description": "Price above key SMAs with bullish MACD.",
        "display_order": 18,
        "query_sql": """
WITH ranked AS (
    SELECT s.*,
        PERCENT_RANK() OVER (PARTITION BY sector ORDER BY technical_price_relative_strength) AS strength_rank
    FROM v_nepse_stock_screen s
    WHERE LOWER(technical_sma_20) = 'above'
      AND LOWER(technical_sma_50) = 'above'
      AND LOWER(technical_macd) = 'bullish'
      AND technical_rsi_14 BETWEEN 48 AND 70 AND liquidity_rank >= 0.35
)
SELECT symbol, sector, ltp, percent_change, technical_sma_10, technical_sma_20, technical_sma_50,
       technical_macd, technical_rsi_14, technical_price_relative_strength,
       ROUND((100.0 * strength_rank)::numeric, 2) AS preset_score
FROM ranked ORDER BY preset_score DESC LIMIT 25
""",
    },
    {
        "preset_code": "relative_strength_leaders",
        "preset_name": "Relative Strength Leaders",
        "category": "TRADER",
        "risk_level": "MEDIUM_HIGH",
        "time_horizon": "1–8 weeks",
        "description": "Top price relative strength with trend confirmation.",
        "display_order": 19,
        "query_sql": """
WITH ranked AS (
    SELECT s.*,
        PERCENT_RANK() OVER (ORDER BY technical_price_relative_strength) AS rs_rank,
        PERCENT_RANK() OVER (ORDER BY alpha_annualized) AS alpha_rank
    FROM v_nepse_stock_screen s
    WHERE technical_price_relative_strength >= 50
      AND LOWER(technical_sma_50) = 'above'
      AND alpha_annualized > 0 AND liquidity_rank >= 0.35
)
SELECT symbol, sector, ltp, percent_change, qty, technical_price_relative_strength,
       alpha_annualized, beta_3_month, technical_rsi_14, technical_macd,
       ROUND((100.0 * (rs_rank * 0.65 + alpha_rank * 0.35))::numeric, 2) AS preset_score
FROM ranked ORDER BY preset_score DESC LIMIT 25
""",
    },
    {
        "preset_code": "volume_surge_movers",
        "preset_name": "Volume Surge Movers",
        "category": "TRADER",
        "risk_level": "VERY_HIGH",
        "time_horizon": "Intraday to 2 weeks",
        "description": "Unusual volume vs 30-day average with active price movement.",
        "display_order": 20,
        "query_sql": """
WITH ranked AS (
    SELECT s.*,
        PERCENT_RANK() OVER (ORDER BY current_volume_ratio) AS vol_rank,
        PERCENT_RANK() OVER (ORDER BY ABS(percent_change)) AS move_rank
    FROM v_nepse_stock_screen s
    WHERE current_volume_ratio >= 0.80
      AND liquidity_rank >= 0.45
      AND ABS(percent_change) >= 0.5
      AND technical_rsi_14 BETWEEN 40 AND 75
)
SELECT symbol, sector, ltp, percent_change, qty, avg_volume_30d, current_volume_ratio,
       technical_rsi_14, technical_volume_trend, volatility_50d,
       ROUND((100.0 * (vol_rank * 0.60 + move_rank * 0.40))::numeric, 2) AS preset_score
FROM ranked ORDER BY preset_score DESC LIMIT 25
""",
    },
]


def ensure_market_screen_presets(db: Session) -> int:
    """Create preset table rows and upsert built-in presets."""
    updated = 0
    for preset in SCREEN_PRESET_SEEDS:
        db.execute(
            text(
                """
                INSERT INTO market_screen_presets (
                    preset_code, preset_name, category, risk_level, time_horizon,
                    description, query_sql, display_order, enabled
                )
                VALUES (
                    :preset_code, :preset_name, :category, :risk_level, :time_horizon,
                    :description, :query_sql, :display_order, TRUE
                )
                ON CONFLICT (preset_code) DO UPDATE SET
                    preset_name = EXCLUDED.preset_name,
                    category = EXCLUDED.category,
                    risk_level = EXCLUDED.risk_level,
                    time_horizon = EXCLUDED.time_horizon,
                    description = EXCLUDED.description,
                    query_sql = EXCLUDED.query_sql,
                    display_order = EXCLUDED.display_order,
                    enabled = EXCLUDED.enabled,
                    updated_at = NOW()
                """
            ),
            {
                **preset,
                "query_sql": preset["query_sql"].strip(),
            },
        )
        updated += 1
    db.commit()
    return updated


def list_market_screen_presets(db: Session) -> List[Dict[str, Any]]:
    rows = db.execute(
        text(
            """
            SELECT
                preset_code, preset_name, category, risk_level, time_horizon,
                description, query_sql, display_order
            FROM market_screen_presets
            WHERE enabled = TRUE
            ORDER BY display_order, preset_name
            """
        )
    ).mappings().all()
    return [
        {
            "id": row["preset_code"],
            "title": row["preset_name"],
            "subtitle": row["description"],
            "category": row["category"],
            "risk_level": row["risk_level"],
            "time_horizon": row["time_horizon"],
            "query": row["query_sql"].strip(),
            "preset_code": row["preset_code"],
            "display_order": row["display_order"],
        }
        for row in rows
    ]


def get_market_screen_preset(db: Session, preset_code: str) -> Dict[str, Any] | None:
    row = db.execute(
        text(
            """
            SELECT preset_code, preset_name, description, query_sql
            FROM market_screen_presets
            WHERE preset_code = :preset_code AND enabled = TRUE
            """
        ),
        {"preset_code": preset_code},
    ).mappings().first()
    if not row:
        return None
    return {
        "id": row["preset_code"],
        "title": row["preset_name"],
        "subtitle": row["description"],
        "query": row["query_sql"].strip(),
    }
