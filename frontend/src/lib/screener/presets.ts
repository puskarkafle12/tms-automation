export interface ScreenerPreset {
  id: string;
  title: string;
  subtitle: string;
  query: string;
  prompt: string;
}

const QUERY_SYNTAX_GUIDE = `How to write screener queries:
- Start with WHERE (optional), chain filters with AND
- Numbers: field >= 10, field BETWEEN 30 AND 45, field <= 25
- Text: field = 'Bullish', field IN ('Bullish', 'Neutral'), field CONTAINS 'Up'
- Sort: ORDER BY field_name DESC (or ASC)
- Limit: LIMIT 25 (max 500)
- Field keys use underscores, e.g. technical_rsi_14, fundamental_pe_ttm, alpha_annualized`;

export const SCREENER_QUERY_GUIDE = QUERY_SYNTAX_GUIDE;

export const SCREENER_PRESETS: ScreenerPreset[] = [
  {
    id: 'top-alpha',
    title: 'Top Alpha Leaders',
    subtitle: 'Highest risk-adjusted outperformance vs market',
    query: `WHERE alpha_annualized >= 0
ORDER BY alpha_annualized DESC
LIMIT 25`,
    prompt: `Screen: Top Alpha Leaders (Top 25)

What it looks for:
Stocks with the highest annualized alpha — meaning they beat the market benchmark on a risk-adjusted basis.

Filters:
- alpha_annualized >= 0 (positive alpha only)

Rank: alpha_annualized DESC

Customize: Raise the floor (e.g. alpha_annualized >= 50) for stronger picks.

${QUERY_SYNTAX_GUIDE}`,
  },
  {
    id: 'best-sharpe',
    title: 'Best Sharpe Ratio',
    subtitle: 'Top risk-adjusted returns',
    query: `WHERE sharpe_ratio_annualized >= 0.5
ORDER BY sharpe_ratio_annualized DESC
LIMIT 25`,
    prompt: `Screen: Best Sharpe Ratio (Top 25)

What it looks for:
Stocks delivering the best return per unit of risk (Sharpe ratio).

Filters:
- sharpe_ratio_annualized >= 0.5

Rank: sharpe_ratio_annualized DESC

Customize: Try sharpe_ratio_annualized >= 1 for elite names only.

${QUERY_SYNTAX_GUIDE}`,
  },
  {
    id: 'quality-fundamentals',
    title: 'Quality Fundamentals',
    subtitle: 'Strong ROE, low debt, solid earnings',
    query: `WHERE fundamental_roe_ttm >= 12
  AND fundamental_debt_to_equity <= 1
  AND fundamental_yoy_earnings_growth >= 5
ORDER BY fundamental_roe_ttm DESC
LIMIT 25`,
    prompt: `Screen: Quality Fundamentals (Top 25)

What it looks for:
Financially healthy companies with profitability and manageable leverage.

Filters:
- ROE TTM >= 12%
- Debt to equity <= 1
- YOY earnings growth >= 5%

Rank: fundamental_roe_ttm DESC

Customize: Tighten debt (<= 0.5) or raise ROE (>= 18) for stricter quality.

${QUERY_SYNTAX_GUIDE}`,
  },
  {
    id: 'value-picks',
    title: 'Value Picks',
    subtitle: 'Lower PE and PBV relative to market',
    query: `WHERE fundamental_pe_ttm >= 5
  AND fundamental_pe_ttm <= 25
  AND fundamental_pbv <= 4
ORDER BY fundamental_pe_ttm ASC
LIMIT 25`,
    prompt: `Screen: Value Picks (Top 25)

What it looks for:
Potentially undervalued stocks with reasonable PE and PBV.

Filters:
- PE TTM between 5 and 25
- PBV <= 4

Rank: fundamental_pe_ttm ASC (cheapest first)

Customize: Add fundamental_distance_from_graham_number <= 100 for Graham-style value.

${QUERY_SYNTAX_GUIDE}`,
  },
  {
    id: 'bullish-momentum',
    title: 'Bullish Momentum',
    subtitle: 'MACD bullish + price above key SMAs',
    query: `WHERE technical_macd = 'Bullish'
  AND technical_sma_20 = 'above'
  AND technical_rsi_14 BETWEEN 45 AND 65
ORDER BY technical_price_relative_strength DESC
LIMIT 25`,
    prompt: `Screen: Bullish Momentum (Top 25)

What it looks for:
Uptrending stocks with bullish MACD and price above the 20-day moving average.

Filters:
- MACD = Bullish
- SMA 20 = above
- RSI 14 between 45 and 65 (momentum without extreme overbought)

Rank: technical_price_relative_strength DESC

Customize: Require technical_sma_50 = 'above' for stronger trend confirmation.

${QUERY_SYNTAX_GUIDE}`,
  },
  {
    id: 'oversold-reversal',
    title: 'Oversold Reversal',
    subtitle: 'RSI and stochastic in oversold zone',
    query: `WHERE technical_rsi_14 BETWEEN 25 AND 40
  AND technical_stochastic_14 <= 25
  AND technical_percent_b <= 30
ORDER BY technical_stochastic_14 ASC
LIMIT 25`,
    prompt: `Screen: Oversold Reversal (Top 25)

What it looks for:
Stocks that may be oversold and due for a bounce.

Filters:
- RSI 14 between 25 and 40
- Stochastic 14 <= 25
- %B <= 30

Rank: technical_stochastic_14 ASC (most oversold first)

Customize: Add technical_macd = 'Bullish' to wait for reversal confirmation.

${QUERY_SYNTAX_GUIDE}`,
  },
  {
    id: 'high-dividend',
    title: 'High Dividend Yield',
    subtitle: 'Income-focused names with yield',
    query: `WHERE fundamental_dividend_yield >= 2
  AND fundamental_payout_ratio <= 80
ORDER BY fundamental_dividend_yield DESC
LIMIT 25`,
    prompt: `Screen: High Dividend Yield (Top 25)

What it looks for:
Stocks paying meaningful dividends with sustainable payout ratios.

Filters:
- Dividend yield >= 2%
- Payout ratio <= 80%

Rank: fundamental_dividend_yield DESC

Customize: Raise yield threshold (>= 4) or add fundamental_debt_to_equity <= 1 for safety.

${QUERY_SYNTAX_GUIDE}`,
  },
  {
    id: 'low-risk-defensive',
    title: 'Low Risk Defensive',
    subtitle: 'Low beta and volatility',
    query: `WHERE beta_3_month <= 1
  AND volatility_50d <= 25
  AND daily_var_95 >= -5
ORDER BY sharpe_ratio_annualized DESC
LIMIT 25`,
    prompt: `Screen: Low Risk Defensive (Top 25)

What it looks for:
Defensive stocks with lower market sensitivity and volatility.

Filters:
- Beta 3 month <= 1
- 50D volatility <= 25
- Daily VAR >= -5% (less extreme downside)

Rank: sharpe_ratio_annualized DESC

Customize: Add one_year_yield >= 0 to avoid declining names.

${QUERY_SYNTAX_GUIDE}`,
  },
  {
    id: 'relative-strength',
    title: 'Strong Relative Strength',
    subtitle: 'Outperforming peers on price strength',
    query: `WHERE technical_price_relative_strength >= 70
  AND one_year_yield >= 0
ORDER BY technical_price_relative_strength DESC
LIMIT 25`,
    prompt: `Screen: Strong Relative Strength (Top 25)

What it looks for:
Stocks showing strong price performance relative to the sector/market.

Filters:
- Price relative strength >= 70%
- 1 year yield >= 0 (not in sustained decline)

Rank: technical_price_relative_strength DESC

Customize: Combine with technical_macd = 'Bullish' for momentum + strength.

${QUERY_SYNTAX_GUIDE}`,
  },
  {
    id: 'earnings-growth',
    title: 'Earnings Growth Leaders',
    subtitle: 'Strong QOQ and YOY earnings growth',
    query: `WHERE fundamental_yoy_earnings_growth >= 15
  AND fundamental_qoq_earnings_growth >= 0
ORDER BY fundamental_yoy_earnings_growth DESC
LIMIT 25`,
    prompt: `Screen: Earnings Growth Leaders (Top 25)

What it looks for:
Companies with accelerating or strong earnings growth.

Filters:
- YOY earnings growth >= 15%
- QOQ earnings growth >= 0%

Rank: fundamental_yoy_earnings_growth DESC

Customize: Add fundamental_roe_ttm >= 10 to filter for profitable growers.

${QUERY_SYNTAX_GUIDE}`,
  },
];

export const buildPresetCopyText = (preset: ScreenerPreset): string => {
  return `${preset.title}\n${preset.subtitle}\n\n${preset.prompt}\n\n--- Query ---\n${preset.query}`;
};
