#!/usr/bin/env python3
"""Export daily cross-sectional NEPSE features from point-in-time indicator rows."""

from __future__ import annotations

import argparse
import re

import pandas as pd
from sqlalchemy import text

from database import SessionLocal


SAFE_KEY = re.compile(r"^[a-z0-9_]+$")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_csv")
    args = parser.parse_args()
    session = SessionLocal()
    try:
        sample = session.execute(text("""
            SELECT indicators
            FROM market_indicator_daily
            ORDER BY session_date DESC,calculated_at DESC
            LIMIT 1
        """)).scalar() or {}
        numeric_keys = sorted(
            key for key, value in sample.items()
            if SAFE_KEY.fullmatch(key) and isinstance(value, (int, float))
        )
        categorical = {
            "technical_macd": "Bullish",
            "technical_psar": "Bullish",
            "technical_signal": "Strong Buy",
            "technical_sma_10": "above",
            "technical_sma_20": "above",
            "technical_sma_50": "above",
            "technical_sma_200": "above",
            "technical_squeeze": "On",
            "technical_supertrend": "Bullish",
            "technical_volume_trend": "Trending Up",
        }
        expressions = ["COUNT(*)::double precision AS xs_stock_count"]
        for key, value in categorical.items():
            escaped = value.replace("'", "''")
            expressions.append(
                "AVG(CASE WHEN indicators ? '{key}' THEN "
                "CASE WHEN indicators->>'{key}'='{value}' THEN 1.0 ELSE 0.0 END "
                'END) AS "xs_share__{key}__{slug}"'.format(
                    key=key, value=escaped, slug=re.sub(r"[^a-z0-9]+", "_", value.lower()),
                )
            )
        latest_cte = """
            WITH latest AS MATERIALIZED (
                SELECT DISTINCT ON (symbol,session_date)
                       symbol,session_date,indicators
                FROM market_indicator_daily
                ORDER BY symbol,session_date,calculated_at DESC,engine_version DESC
            )
        """
        numeric_rows = session.execute(text(latest_cte + """
            SELECT session_date,item.key,
                   AVG((item.value #>> '{}')::double precision) AS value
            FROM latest
            CROSS JOIN LATERAL jsonb_each(latest.indicators) AS item(key,value)
            WHERE jsonb_typeof(item.value)='number'
              AND item.key=ANY(:numeric_keys)
            GROUP BY session_date,item.key
            ORDER BY session_date,item.key
        """), {"numeric_keys": numeric_keys}).mappings().all()
        indicator_sql = latest_cte + """
            SELECT session_date,{expressions}
            FROM latest
            GROUP BY session_date
            ORDER BY session_date
        """.format(expressions=",\n".join(expressions))
        indicator_rows = session.execute(text(indicator_sql)).mappings().all()
        breadth_rows = session.execute(text("""
            WITH prices AS (
                SELECT DISTINCT ON (symbol,session_date)
                       symbol,session_date,close_price,volume,
                       LAG(close_price) OVER (
                           PARTITION BY symbol ORDER BY session_date
                       ) AS prior_close
                FROM market_ohlcv_daily
                WHERE adjusted=TRUE AND close_price>0
                ORDER BY symbol,session_date,fetched_at DESC
            ), returns AS (
                SELECT *,close_price/NULLIF(prior_close,0)-1 AS stock_return
                FROM prices
                WHERE prior_close IS NOT NULL
            )
            SELECT session_date,
                   AVG(stock_return) FILTER (WHERE stock_return BETWEEN -.2 AND .2)
                       AS xs_market_return,
                   PERCENTILE_CONT(.5) WITHIN GROUP (ORDER BY stock_return)
                       FILTER (WHERE stock_return BETWEEN -.2 AND .2) AS xs_median_return,
                   STDDEV_POP(stock_return) FILTER (WHERE stock_return BETWEEN -.2 AND .2)
                       AS xs_return_dispersion,
                   AVG((stock_return>0)::int::double precision)
                       FILTER (WHERE stock_return BETWEEN -.2 AND .2) AS xs_advance_ratio,
                   SUM(volume) FILTER (WHERE volume>0) AS xs_total_volume,
                   AVG(volume) FILTER (WHERE volume>0) AS xs_average_volume,
                   PERCENTILE_CONT(.5) WITHIN GROUP (ORDER BY volume)
                       FILTER (WHERE volume>0) AS xs_median_volume,
                   SUM(volume*close_price) FILTER (WHERE volume>0) AS xs_total_turnover,
                   SUM(volume) FILTER (WHERE volume>0 AND stock_return>0)
                     / NULLIF(SUM(volume) FILTER (WHERE volume>0),0) AS xs_up_volume_ratio
            FROM returns
            GROUP BY session_date
            ORDER BY session_date
        """)).mappings().all()
    finally:
        session.close()
    indicators = pd.DataFrame(indicator_rows)
    numeric = pd.DataFrame(numeric_rows)
    if not numeric.empty:
        numeric = numeric.pivot(index="session_date", columns="key", values="value")
        numeric.columns = [f"xs_mean__{column}" for column in numeric.columns]
        indicators = indicators.merge(
            numeric.reset_index(), on="session_date", how="outer",
        )
    breadth = pd.DataFrame(breadth_rows)
    frame = indicators.merge(breadth, on="session_date", how="outer").sort_values("session_date")
    frame.to_csv(args.output_csv, index=False)
    print({
        "rows": len(frame),
        "start": str(frame["session_date"].min()),
        "end": str(frame["session_date"].max()),
        "features": len(frame.columns) - 1,
        "numeric_indicator_fields": len(numeric_keys),
        "categorical_signal_fields": len(categorical),
    })


if __name__ == "__main__":
    main()
