"""Reusable equity screening view over combined market cache."""

from __future__ import annotations

from sqlalchemy.orm import Session

SCREEN_VIEW_NAME = "v_nepse_stock_screen"

EXCLUDED_SECTORS = ("Mutual Fund", "Corporate Debenture")


def _numeric_cast(column: str, dialect_name: str) -> str:
    if dialect_name == "sqlite":
        return f"CAST({column} AS REAL)"
    return f"{column}::numeric"


def build_v_nepse_stock_screen_subquery(db: Session) -> str:
    """Inline equivalent of CREATE VIEW v_nepse_stock_screen."""
    from utils.market_data.sql_screener import build_market_combined_subquery

    dialect_name = db.get_bind().dialect.name
    combined = build_market_combined_subquery(db)
    qty_numeric = _numeric_cast("qty", dialect_name)
    avg_vol_numeric = _numeric_cast("avg_volume_30d", dialect_name)

    return f"""
        SELECT
            e.*,
            PERCENT_RANK() OVER (ORDER BY avg_volume_30d) AS liquidity_rank,
            PERCENT_RANK() OVER (ORDER BY market_cap) AS market_cap_rank,
            PERCENT_RANK() OVER (
                ORDER BY volatility_50d NULLS FIRST
            ) AS volatility_rank,
            PERCENT_RANK() OVER (
                ORDER BY ABS(daily_var_95) NULLS FIRST
            ) AS var_risk_rank
        FROM (
            SELECT
                d.*,
                CASE
                    WHEN fifty_two_week_high > fifty_two_week_low
                    THEN (
                        (ltp - fifty_two_week_low)
                        / NULLIF(fifty_two_week_high - fifty_two_week_low, 0)
                    ) * 100.0
                END AS position_52_week_pct,
                CASE
                    WHEN avg_volume_30d > 0
                    THEN {qty_numeric} / NULLIF({avg_vol_numeric}, 0)
                END AS current_volume_ratio
            FROM ({combined}) AS d
            WHERE symbol IS NOT NULL
              AND ltp > 0
              AND market_cap > 0
              AND avg_volume_30d > 0
              AND sector IS NOT NULL
              AND sector NOT IN ('Mutual Fund', 'Corporate Debenture')
        ) AS e
    """
