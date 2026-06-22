"""Pre-built Ask AI prompts with validated SQL for instant screening (no LLM)."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

QUICK_AI_SCREENS: List[Dict[str, str]] = [
    {
        "id": "oversold_quiet_bounce",
        "prompt": "Which stocks look oversold but are quietly bouncing back today?",
        "summary": (
            "Looks for oversold RSI readings that are turning up with a green day and bullish MACD, "
            "favoring slower recoveries first."
        ),
        "query_sql": """
SELECT symbol, ltp, percent_change, qty, sector, technical_rsi_14, technical_macd, open, high, low, avg_volume_30d
FROM market_combined
WHERE technical_rsi_14 BETWEEN 30 AND 45
  AND percent_change > 0
  AND technical_macd = 'Bullish'
ORDER BY percent_change ASC
LIMIT 25
""",
    },
    {
        "id": "solid_banks_not_expensive",
        "prompt": "Find solid commercial banks that trade often and are not too expensive",
        "summary": (
            "Commercial banks with reasonable PE, healthy trading volume, and enough liquidity "
            "to enter and exit comfortably."
        ),
        "query_sql": """
SELECT symbol, ltp, percent_change, qty, sector, pe_ratio, pbv, eps, avg_volume_30d, market_cap
FROM market_combined
WHERE sector = 'Commercial Banks'
  AND pe_ratio > 0
  AND pe_ratio < 15
  AND avg_volume_30d >= 500
ORDER BY avg_volume_30d DESC
LIMIT 25
""",
    },
    {
        "id": "rising_with_real_volume",
        "prompt": "What's rising today with stronger than usual trading activity?",
        "summary": (
            "Today's gainers where volume is at least 80% of the 30-day average, "
            "so the move has participation behind it."
        ),
        "query_sql": """
SELECT symbol, ltp, percent_change, qty, sector, technical_rsi_14, avg_volume_30d, current_volume_ratio
FROM v_nepse_stock_screen
WHERE percent_change > 0
  AND current_volume_ratio >= 0.80
  AND technical_rsi_14 < 70
ORDER BY percent_change DESC
LIMIT 25
""",
    },
    {
        "id": "profitable_manageable_debt",
        "prompt": "Show me profitable companies with manageable debt — the steadier picks",
        "summary": (
            "Positive earnings, return on equity above 15%, and debt-to-equity at or below 1 — "
            "a balance-sheet-conscious screen."
        ),
        "query_sql": """
SELECT symbol, ltp, percent_change, qty, sector, pe_ratio, fundamental_roe_ttm, fundamental_debt_to_equity, market_cap
FROM market_combined
WHERE fundamental_debt_to_equity IS NOT NULL
  AND fundamental_debt_to_equity <= 1
  AND fundamental_roe_ttm >= 15
  AND eps > 0
ORDER BY market_cap DESC
LIMIT 25
""",
    },
    {
        "id": "bullish_still_moving_up",
        "prompt": "Which stocks are in a bullish mood and still moving up today?",
        "summary": (
            "Bullish MACD, RSI in a strong but not extreme zone, positive day change, "
            "and enough average volume to trade."
        ),
        "query_sql": """
SELECT symbol, ltp, percent_change, qty, sector, technical_rsi_14, technical_macd, alpha_annualized, avg_volume_30d
FROM market_combined
WHERE LOWER(technical_macd) = 'bullish'
  AND technical_rsi_14 BETWEEN 50 AND 75
  AND avg_volume_30d >= 300
  AND percent_change > 0
ORDER BY percent_change DESC
LIMIT 25
""",
    },
    {
        "id": "hydropower_good_day",
        "prompt": "Which hydropower stocks are having a good day on the market?",
        "summary": (
            "Hydro Power sector names closing green today, sorted by the strongest daily gain."
        ),
        "query_sql": """
SELECT symbol, ltp, percent_change, qty, sector, pe_ratio, avg_volume_30d, market_cap
FROM market_combined
WHERE sector = 'Hydro Power'
  AND percent_change > 0
ORDER BY percent_change DESC
LIMIT 25
""",
    },
    {
        "id": "dividend_and_growing",
        "prompt": "Find dividend-paying stocks that are still growing their earnings",
        "summary": (
            "Income-oriented names with dividend yield at least 2% and year-on-year earnings growth "
            "still positive."
        ),
        "query_sql": """
SELECT symbol, ltp, percent_change, qty, sector, fundamental_dividend_yield, fundamental_yoy_earnings_growth, pe_ratio, market_cap
FROM market_combined
WHERE fundamental_dividend_yield >= 2
  AND fundamental_yoy_earnings_growth >= 5
  AND eps > 0
ORDER BY fundamental_dividend_yield DESC
LIMIT 25
""",
    },
    {
        "id": "biggest_listed_names",
        "prompt": "What are the biggest listed companies in NEPSE right now?",
        "summary": (
            "The largest market-cap names in the full NEPSE universe — "
            "useful for blue-chip and liquidity context."
        ),
        "query_sql": """
SELECT symbol, ltp, percent_change, qty, sector, market_cap, pe_ratio, avg_volume_30d
FROM market_combined
WHERE market_cap > 0
ORDER BY market_cap DESC
LIMIT 25
""",
    },
    {
        "id": "cheap_but_quality",
        "prompt": "Show cheap-looking stocks that still earn a decent return for shareholders",
        "summary": (
            "Value tilt: PE at or below 20, PBV at or below 3, ROE at least 10%, "
            "with positive earnings."
        ),
        "query_sql": """
SELECT symbol, ltp, percent_change, qty, sector, pe_ratio, pbv, eps, fundamental_roe_ttm, market_cap
FROM market_combined
WHERE eps > 0
  AND pe_ratio > 0
  AND pe_ratio <= 20
  AND pbv <= 3
  AND fundamental_roe_ttm >= 10
ORDER BY pe_ratio ASC
LIMIT 25
""",
    },
    {
        "id": "near_yearly_highs",
        "prompt": "Which names are trading close to their yearly highs and still climbing?",
        "summary": (
            "Stocks in the upper part of their 52-week range with a green day — "
            "potential continuation candidates."
        ),
        "query_sql": """
SELECT symbol, ltp, percent_change, qty, sector, fifty_two_week_high, position_52_week_pct, technical_rsi_14, avg_volume_30d
FROM v_nepse_stock_screen
WHERE position_52_week_pct >= 65
  AND percent_change > 0
  AND technical_rsi_14 < 80
ORDER BY position_52_week_pct DESC
LIMIT 25
""",
    },
    {
        "id": "pullback_in_uptrend",
        "prompt": "Find stocks pulling back slightly but still in a broader uptrend",
        "summary": (
            "Trending 3-month profile, price above the 50-day trend, short-term dip on the 10/20-day view, "
            "RSI reset zone."
        ),
        "query_sql": """
SELECT symbol, ltp, percent_change, qty, sector, technical_3m_price_tend, technical_rsi_14, technical_sma_20, technical_sma_50, avg_volume_30d
FROM v_nepse_stock_screen
WHERE LOWER(technical_3m_price_tend) = 'trending'
  AND LOWER(technical_sma_50) = 'above'
  AND (
      LOWER(technical_sma_10) = 'below'
      OR LOWER(technical_sma_20) = 'below'
  )
  AND technical_rsi_14 BETWEEN 35 AND 65
ORDER BY technical_rsi_14 ASC
LIMIT 25
""",
    },
    {
        "id": "insurance_active_watchlist",
        "prompt": "Which insurance companies are actively traded and still earning a profit?",
        "summary": (
            "Life and non-life insurers with positive earnings and meaningful average volume — "
            "liquid enough to watch without chasing illiquid names."
        ),
        "query_sql": """
SELECT symbol, ltp, percent_change, qty, sector, pe_ratio, pbv, eps, avg_volume_30d, market_cap
FROM market_combined
WHERE sector LIKE '%Insurance%'
  AND eps > 0
  AND avg_volume_30d >= 100
ORDER BY avg_volume_30d DESC
LIMIT 25
""",
    },
    {
        "id": "most_active_today",
        "prompt": "Show me today's most active stocks with meaningful price movement",
        "summary": (
            "Liquid names with above-average volume participation and at least half a percent move — "
            "where traders are actually engaged."
        ),
        "query_sql": """
SELECT symbol, ltp, percent_change, qty, sector, avg_volume_30d, current_volume_ratio, volatility_50d
FROM v_nepse_stock_screen
WHERE liquidity_rank >= 0.35
  AND ABS(percent_change) >= 0.5
  AND current_volume_ratio >= 0.50
ORDER BY ABS(percent_change) DESC
LIMIT 25
""",
    },
    {
        "id": "microfinance_healthy",
        "prompt": "What microfinance stocks have healthy fundamentals worth watching?",
        "summary": (
            "Microfinance sector with positive EPS and ROE at least 8%, ranked by profitability."
        ),
        "query_sql": """
SELECT symbol, ltp, percent_change, qty, sector, pe_ratio, fundamental_roe_ttm, eps, market_cap
FROM market_combined
WHERE sector = 'Microfinance'
  AND eps > 0
  AND fundamental_roe_ttm >= 8
ORDER BY fundamental_roe_ttm DESC
LIMIT 25
""",
    },
    {
        "id": "beating_market_risk_adjusted",
        "prompt": "Which stocks have been beating the market on a risk-adjusted basis?",
        "summary": (
            "Positive alpha and Sharpe with tradable volume — names that have rewarded shareholders "
            "without being illiquid."
        ),
        "query_sql": """
SELECT symbol, ltp, percent_change, qty, sector, alpha_annualized, sharpe_ratio_annualized, beta_3_month, avg_volume_30d
FROM market_combined
WHERE alpha_annualized > 0
  AND sharpe_ratio_annualized > 0
  AND avg_volume_30d >= 200
ORDER BY alpha_annualized DESC
LIMIT 25
""",
    },
]


def normalize_quick_prompt(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip().lower())
    return cleaned.rstrip("?.!")


def list_quick_ai_screens() -> List[Dict[str, str]]:
    return [
        {
            "id": item["id"],
            "prompt": item["prompt"],
            "summary": item["summary"],
            "query": item["query_sql"].strip(),
        }
        for item in QUICK_AI_SCREENS
    ]


def match_quick_ai_screen(message: str) -> Optional[Dict[str, str]]:
    normalized = normalize_quick_prompt(message)
    if not normalized:
        return None
    for screen in QUICK_AI_SCREENS:
        if normalize_quick_prompt(screen["prompt"]) == normalized:
            return screen
    return None


def build_quick_ai_screen_payload(screen: Dict[str, str], screener_payload: Dict[str, Any]) -> Dict[str, Any]:
    query = screen["query_sql"].strip()
    return {
        **screener_payload,
        "ai_status": "ok",
        "ai_summary": screen["summary"],
        "generated_query": query,
        "ai_source": "quick_screen",
        "ai_quick_screen_id": screen["id"],
        "ai_raw_response": f"STATUS: OK\n\nSummary:\n- {screen['summary']}\n\nQuery:\n```sql\n{query}\n```",
    }
