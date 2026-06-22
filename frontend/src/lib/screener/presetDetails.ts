import { ScreenerPreset } from './presets';

interface PresetDetailBase {
  goal: string;
  howItWorks: string[];
  looksFor: string[];
  examples: string[];
}

export interface PresetDetail extends PresetDetailBase {
  useCase: string;
  whatYouGet: string;
}

export const PRESET_DETAILS: Record<string, PresetDetailBase> = {
  quality_compounders: {
    goal: 'Find profitable companies that can reinvest and grow earnings over time.',
    howItWorks: [
      'Starts with stocks that have positive EPS and solid ROE/ROA.',
      'Requires earnings growth that is not collapsing quarter to quarter.',
      'Keeps valuation within a reasonable PE and PBV band.',
      'Ranks survivors by profitability, growth, value, and risk-adjusted return.',
    ],
    looksFor: [
      'Consistent earners with strong return on equity',
      'Manageable debt for non-financial sectors',
      'Enough daily liquidity to enter and exit comfortably',
    ],
    examples: [
      'A commercial bank with ROE above 8%, positive EPS, and PE under 50',
      'An insurer growing earnings YoY with acceptable leverage vs its sector',
    ],
  },
  quality_value: {
    goal: 'Spot cheaper names that still have real earnings—not deep value traps.',
    howItWorks: [
      'Filters for positive EPS and PE/PBV below typical market levels.',
      'Uses Graham-number distance as an extra value check.',
      'Penalizes stocks with weak profitability or excessive leverage.',
      'Scores by value metrics plus quality and Sharpe ratio.',
    ],
    looksFor: [
      'Undervalued on PE and PBV relative to peers',
      'Still profitable with decent ROE',
      'Trading with reasonable liquidity',
    ],
    examples: [
      'A stock at PE 9 and PBV 1.1 with positive EPS and ROE above 10%',
      'A name near its sector-low valuation but not loss-making',
    ],
  },
  growth_at_reasonable_price: {
    goal: 'Balance growth with valuation—avoid overpaying for momentum.',
    howItWorks: [
      'Requires positive YoY and QoQ earnings growth.',
      'Limits PE and PEG so growth is not priced too aggressively.',
      'Adds technical strength and alpha as tie-breakers.',
      'Ranks by growth quality vs price paid.',
    ],
    looksFor: [
      'Earnings growing year over year',
      'PEG in a sensible range for the sector',
      'Positive alpha with acceptable RSI',
    ],
    examples: [
      'A stock with 15% YoY earnings growth, PEG under 1.5, and PE below 35',
      'A growing finance name not stretched on RSI or PE',
    ],
  },
  sustainable_dividend: {
    goal: 'Income-oriented names with dividends that look sustainable.',
    howItWorks: [
      'Requires minimum dividend yield and positive EPS.',
      'Caps payout ratio so dividends are not overstretched.',
      'Checks debt and profitability so yield is supported by fundamentals.',
      'Ranks by yield, payout safety, and ROE.',
    ],
    looksFor: [
      'Dividend yield above ~2% with manageable payout',
      'Profitable companies with solid ROE',
      'Lower leverage than sector extremes',
    ],
    examples: [
      'A bank yielding 4% with payout under 60% and positive EPS',
      'An insurer paying dividends without excessive debt',
    ],
  },
  earnings_acceleration: {
    goal: 'Companies where earnings growth is speeding up, not slowing down.',
    howItWorks: [
      'Requires strong QoQ and YoY earnings growth.',
      'Keeps ROE and PE within investable ranges.',
      'Uses relative strength and Sharpe to favor quality momentum.',
      'Ranks by acceleration and risk-adjusted performance.',
    ],
    looksFor: [
      'Double-digit QoQ and YoY earnings growth',
      'ROE at least in mid-single digits or better',
      'Technical strength confirming the trend',
    ],
    examples: [
      'A stock with 12% QoQ and 14% YoY earnings growth and ROE above 8%',
      'A sector leader improving earnings faster than peers',
    ],
  },
  defensive_large_liquid: {
    goal: 'Large, liquid names suited to lower-turnover, defensive positioning.',
    howItWorks: [
      'Focuses on higher market cap and strong 30-day volume.',
      'Requires positive EPS and moderate volatility.',
      'Favors stable profitability (ROE) and acceptable valuation.',
      'Ranks by size, liquidity, and stability scores.',
    ],
    looksFor: [
      'Large-cap or upper mid-cap liquid stocks',
      'Lower volatility than the broad market',
      'Profitable with sensible PE/PBV',
    ],
    examples: [
      'A major commercial bank with high avg volume and moderate beta',
      'A large insurer with steady EPS and deep daily turnover',
    ],
  },
  high_roe_leaders: {
    goal: 'Highlight companies that deploy capital efficiently.',
    howItWorks: [
      'Requires ROE at or above 12% with positive EPS.',
      'Keeps PE in a range that avoids extreme outliers.',
      'Ensures minimum liquidity before ranking.',
      'Scores by ROE within sector plus Sharpe ratio.',
    ],
    looksFor: [
      'Top return-on-equity names in each sector',
      'Profitable businesses, not one-off earnings spikes',
      'Tradeable average volume',
    ],
    examples: [
      'A microfinance name with ROE 18% and PE between 12 and 30',
      'A bank ranking high on ROE vs its sector peers',
    ],
  },
  low_debt_quality: {
    goal: 'Quality balance sheets with manageable leverage.',
    howItWorks: [
      'Limits debt-to-equity to conservative levels.',
      'Requires ROE and EPS to confirm profitability.',
      'Ranks lower-debt names higher within each sector.',
      'Favors solid ROE alongside balance-sheet strength.',
    ],
    looksFor: [
      'Debt-to-equity at or below 1.0',
      'ROE above 10% with positive EPS',
      'Liquid enough for practical investing',
    ],
    examples: [
      'A stock with D/E 0.6, ROE 14%, and positive EPS',
      'A non-bank name with low leverage vs sector highs',
    ],
  },
  graham_deep_value: {
    goal: 'Classic deep-value candidates trading below intrinsic-style measures.',
    howItWorks: [
      'Uses distance from Graham number as a primary value signal.',
      'Requires low PE, PBV under 3, and positive EPS.',
      'Filters for names far enough below Graham reference.',
      'Ranks by value depth and PE attractiveness.',
    ],
    looksFor: [
      'Low PE (roughly 2–20) with positive earnings',
      'PBV not stretched vs book value',
      'High Graham-distance score (meaningfully undervalued)',
    ],
    examples: [
      'A stock at PE 8, PBV 1.2, with strong Graham discount',
      'A value name with EPS support—not a distressed shell',
    ],
  },
  dividend_growth_combo: {
    goal: 'Income plus growth—dividend payers that are still expanding earnings.',
    howItWorks: [
      'Requires dividend yield and positive YoY earnings growth.',
      'Caps payout ratio to avoid unsustainable dividends.',
      'Ranks by yield and growth together.',
      'Favors names balancing income and expansion.',
    ],
    looksFor: [
      'Yield at least ~2% with earnings growing 5%+ YoY',
      'Payout ratio not excessive',
      'Positive EPS backing the dividend',
    ],
    examples: [
      'A stock yielding 3.5% with 8% YoY earnings growth',
      'A dividend payer increasing profits while paying shareholders',
    ],
  },
  liquid_bullish_momentum: {
    goal: 'Catch strong uptrends with enough volume to trade actively.',
    howItWorks: [
      'Requires bullish MACD and price above key SMAs.',
      'RSI and MFI in a bullish but not exhausted zone.',
      'Volume trend and relative strength must confirm.',
      'Scores by strength, alpha, volume, and today’s move.',
    ],
    looksFor: [
      'Confirmed bullish trend with rising participation',
      'RSI roughly 50–72—not oversold, not extremely overbought',
      'Above-average volume vs the 30-day norm',
    ],
    examples: [
      'A stock up on the day with MACD bullish and volume trending up',
      'A sector leader with price above SMA 20/50 and strong RS',
    ],
  },
  breakout_ready: {
    goal: 'Names pressing toward 52-week highs with volume confirmation.',
    howItWorks: [
      'Position in 52-week range typically 80–105%.',
      'Bullish MACD and SMA alignment required.',
      'Percent B and RSI filter for momentum, not exhaustion.',
      'Ranks by breakout proximity, volume, and strength.',
    ],
    looksFor: [
      'Near or at 52-week highs with trend intact',
      'Volume picking up vs recent average',
      'Technical indicators aligned for continuation',
    ],
    examples: [
      'A stock at 92% of its 52-week range with volume surge',
      'A breakout candidate with bullish MACD and RS above peers',
    ],
  },
  trend_pullback: {
    goal: 'Buy pullbacks inside an still-intact longer-term uptrend.',
    howItWorks: [
      'Requires 3-month trend label and SMA 50/200 still bullish.',
      'Allows short-term SMA dip (pullback) while macro trend holds.',
      'RSI, stochastic, and %B screen for reset—not breakdown.',
      'Ranks by strength, alpha, and volume on recovery setup.',
    ],
    looksFor: [
      'Primary trend up, short-term dip to support',
      'RSI often 35–62 during the pullback',
      'MACD neutral or turning bullish again',
    ],
    examples: [
      'A leader below SMA 10 but still above SMA 50 with RSI 42',
      'A stock consolidating after a run, ready to resume trend',
    ],
  },
  confirmed_oversold_reversal: {
    goal: 'Oversold bounces with price and volume confirmation—not falling knives.',
    howItWorks: [
      'RSI, stochastic, %B, and MFI must show oversold readings.',
      'Requires positive percent change and price holding above open.',
      'Volume trend cannot be sharply negative.',
      'Ranks by recovery strength, volume, and relative strength.',
    ],
    looksFor: [
      'Oversold on multiple indicators (RSI ~25–43)',
      'Green day with volume picking up',
      'Early reversal, not a continued breakdown',
    ],
    examples: [
      'A stock down several days that closes green with RSI 38 and volume spike',
      'An oversold name bouncing with stochastic under 35 turning up',
    ],
  },
  alpha_swing_leaders: {
    goal: 'Swing-trade candidates outperforming on a risk-adjusted basis.',
    howItWorks: [
      'Requires positive alpha and Sharpe with controlled beta.',
      'Technical relative strength must be solid.',
      'RSI in a tradable mid-range for swings.',
      'Ranks by alpha, Sharpe, strength, and liquidity.',
    ],
    looksFor: [
      'Positive alpha and Sharpe vs the market',
      'Beta not extreme—manageable swing risk',
      'Price above SMA 50 with RS ≥ ~45',
    ],
    examples: [
      'A stock with alpha 20+, Sharpe above 1, and RS 50+',
      'A medium-term outperformer suitable for 1–8 week holds',
    ],
  },
  liquid_high_volatility_traders: {
    goal: 'Fast movers with enough liquidity for active short-term trading.',
    howItWorks: [
      'Targets high volatility rank and beta above market.',
      'Requires strong liquidity and volume ratio.',
      'RSI kept in a tradable band—not pinned at extremes.',
      'Scores movement, volume, beta, and volatility together.',
    ],
    looksFor: [
      'High 50-day volatility and elevated beta',
      'Strong average volume and today’s participation',
      'Active price movement intraday or over days',
    ],
    examples: [
      'A volatile stock with beta 1.2+ and volume well above average',
      'An active trader name moving 2%+ with deep liquidity',
    ],
  },
  rsi_momentum_runners: {
    goal: 'Momentum names in a strong—but not exhausted—RSI zone.',
    howItWorks: [
      'RSI between ~55 and 72 with bullish MACD.',
      'Price above SMA 20 confirms short-term trend.',
      'Volume and liquidity filters avoid illiquid spikes.',
      'Ranks by today’s move and volume participation.',
    ],
    looksFor: [
      'RSI in upper-mid range with bullish MACD',
      'Positive momentum with tradable volume',
      'Not yet in extreme overbought territory',
    ],
    examples: [
      'A stock with RSI 62, MACD bullish, and strong percent change',
      'A runner continuing a trend with volume support',
    ],
  },
  sma_bullish_alignment: {
    goal: 'Stocks with price aligned above key moving averages—classic trend follow.',
    howItWorks: [
      'Requires SMA 20 and SMA 50 both “above”.',
      'MACD must be bullish.',
      'RSI filtered to avoid exhausted blow-offs.',
      'Ranks by relative strength within sector.',
    ],
    looksFor: [
      'Price above medium-term averages',
      'Bullish MACD confirmation',
      'RSI roughly 48–70—trending, not parabolic',
    ],
    examples: [
      'A stock above SMA 20/50 with MACD bullish and RS leading its sector',
      'A steady climber respecting moving-average support',
    ],
  },
  relative_strength_leaders: {
    goal: 'Market leaders outperforming peers on price strength.',
    howItWorks: [
      'Price relative strength at or above 50.',
      'SMA 50 bullish and positive alpha required.',
      'Liquidity filter for practical entries.',
      'Ranks by RS and alpha combined.',
    ],
    looksFor: [
      'Top performers vs the broader market',
      'Trend confirmed above SMA 50',
      'Positive alpha backing the leadership',
    ],
    examples: [
      'A sector top-quartile RS name with alpha > 0',
      'A leader still trending while peers lag',
    ],
  },
  volume_surge_movers: {
    goal: 'Unusual volume today with meaningful price movement.',
    howItWorks: [
      'Current volume vs 30-day average must be elevated.',
      'Requires meaningful percent change (up or down).',
      'RSI kept in a tradable range.',
      'Ranks by volume surge magnitude and move size.',
    ],
    looksFor: [
      'Volume well above normal (high volume ratio)',
      'Active price action—movers attracting attention',
      'Enough liquidity for short-term trades',
    ],
    examples: [
      'A stock on 2x average volume with a 1%+ move',
      'An intraday or weekly mover with participation spike',
    ],
  },
};

const PRESET_USAGE: Record<string, Pick<PresetDetail, 'useCase' | 'whatYouGet'>> = {
  quality_compounders: {
    useCase: 'You want steady long-term holdings—profitable companies that can keep growing—not speculative punts.',
    whatYouGet:
      'Up to 25 ranked stocks with symbol, live price, today\'s change, and volume—plus earnings growth, ROE/ROA, PE/PBV, debt, and risk scores so you can compare quality names in one table.',
  },
  quality_value: {
    useCase: 'You want cheaper stocks that still earn money—not distressed companies that might never recover.',
    whatYouGet:
      'Up to 25 value names with LTP, % change, volume, PE, PBV, Graham discount, ROE, EPS, and liquidity so you see who is cheap but still profitable.',
  },
  growth_at_reasonable_price: {
    useCase: 'You want earnings growth without paying extreme momentum prices.',
    whatYouGet:
      'Up to 25 growers showing YoY/QoQ earnings, PEG, PE, alpha, RSI, and price action—ranked by growth quality vs what you pay.',
  },
  sustainable_dividend: {
    useCase: 'You are building income and care whether the dividend looks sustainable.',
    whatYouGet:
      'Up to 25 dividend payers with yield, payout ratio, EPS, ROE, debt, and live price/volume—so you can spot income that is backed by fundamentals.',
  },
  earnings_acceleration: {
    useCase: 'You want companies whose profits are speeding up—not just growing slowly.',
    whatYouGet:
      'Up to 25 accelerators with QoQ/YoY earnings growth, ROE, PE, relative strength, Sharpe, and today\'s price move.',
  },
  defensive_large_liquid: {
    useCase: 'You prefer big, stable names you can enter and exit easily with less drama.',
    whatYouGet:
      'Up to 25 large liquid stocks with market cap, average volume, volatility, EPS, PE/PBV, and stability scores.',
  },
  high_roe_leaders: {
    useCase: 'You care how efficiently a company uses shareholder capital.',
    whatYouGet:
      'Up to 25 high-ROE leaders with ROE vs sector, EPS, PE, Sharpe, volume, and live price/% change.',
  },
  low_debt_quality: {
    useCase: 'You want balance-sheet safety and less leverage risk in your picks.',
    whatYouGet:
      'Up to 25 lower-debt names with debt-to-equity, ROE, EPS, sector debt rank, and standard price/volume columns.',
  },
  graham_deep_value: {
    useCase: 'You hunt classic deep-value discounts—but only where earnings still support the story.',
    whatYouGet:
      'Up to 25 Graham-style value picks with PE, PBV, distance from Graham number, EPS, and live market data.',
  },
  dividend_growth_combo: {
    useCase: 'You want dividends plus growing earnings—not a high yield trap.',
    whatYouGet:
      'Up to 25 names combining dividend yield, YoY earnings growth, payout ratio, EPS, and price/volume.',
  },
  liquid_bullish_momentum: {
    useCase: 'You trade uptrends and need enough volume to get in and out quickly.',
    whatYouGet:
      'Up to 25 bullish momentum stocks with MACD, RSI, MFI, SMA signals, volume trend, alpha, and today\'s % change.',
  },
  breakout_ready: {
    useCase: 'You watch names pressing toward highs that may break out with volume.',
    whatYouGet:
      'Up to 25 breakout candidates with 52-week range position, MACD, volume surge, RSI, %B, and live price action.',
  },
  trend_pullback: {
    useCase: 'You buy dips inside a longer uptrend that is still intact.',
    whatYouGet:
      'Up to 25 pullback setups with trend label, SMA 20/50/200 status, RSI, stochastic, relative strength, and volume.',
  },
  confirmed_oversold_reversal: {
    useCase: 'You look for oversold bounce trades—not stocks still in free fall.',
    whatYouGet:
      'Up to 25 reversal candidates with RSI, stochastic, MFI, %B, today\'s change vs open, and volume trend.',
  },
  alpha_swing_leaders: {
    useCase: 'You swing-trade names beating the market on a risk-adjusted basis.',
    whatYouGet:
      'Up to 25 swing picks with alpha, Sharpe, beta, relative strength, RSI, liquidity, and live price/% change.',
  },
  liquid_high_volatility_traders: {
    useCase: 'You want fast movers with enough liquidity for short-term trades.',
    whatYouGet:
      'Up to 25 volatile liquid names with beta, volatility rank, volume ratio, RSI, and today\'s move size.',
  },
  rsi_momentum_runners: {
    useCase: 'You ride momentum when RSI is strong but not yet exhausted.',
    whatYouGet:
      'Up to 25 runners with RSI, MACD, SMA 20 status, percent change, volume, and symbol/LTP.',
  },
  sma_bullish_alignment: {
    useCase: 'You follow classic trend trades—price aligned above key moving averages.',
    whatYouGet:
      'Up to 25 trend-follow names with SMA 20/50 signals, MACD, RSI, sector relative strength, and live prices.',
  },
  relative_strength_leaders: {
    useCase: 'You want market leaders that are outperforming peers right now.',
    whatYouGet:
      'Up to 25 RS leaders with price relative strength, SMA 50 status, alpha, liquidity, and today\'s change.',
  },
  volume_surge_movers: {
    useCase: 'Unusual volume today tells you something is happening—you want those movers first.',
    whatYouGet:
      'Up to 25 volume-spike stocks with volume vs 30-day average, percent change, RSI, LTP, and symbol.',
  },
};

export const getPresetDetail = (preset: ScreenerPreset): PresetDetail => {
  const key = preset.preset_code || preset.id;
  const base = PRESET_DETAILS[key];
  const usage = PRESET_USAGE[key];
  const subtitle = preset.subtitle?.trim() || preset.title;
  return {
    goal: base?.goal ?? subtitle,
    useCase: usage?.useCase ?? `Use this when you want: ${subtitle}`,
    whatYouGet:
      usage?.whatYouGet
      ?? 'Up to 25 ranked stocks with symbol, live price (LTP), today\'s % change, volume, and the main metrics this screen filters on.',
    howItWorks: base?.howItWorks ?? [],
    looksFor: base?.looksFor ?? [],
    examples: base?.examples ?? [],
  };
};
