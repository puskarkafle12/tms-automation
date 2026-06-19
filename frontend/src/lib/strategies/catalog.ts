import { STRATEGY_DISCLAIMER, StrategyType } from './index';
import { STRATEGY_ON_EXECUTE, STRATEGY_TEST_SCENARIOS, StrategyTestScenario } from './scenarios';

export interface StrategyCatalogEntry {
  name: StrategyType;
  side: 'buy' | 'sell';
  purpose: string;
  bestFor: string;
  howItWorks: string[];
  expectedBehavior: string[];
  testScenarios: StrategyTestScenario[];
  onExecute: string;
  requiredData: string[];
  example: string;
  note: string;
}

const entry = (
  name: StrategyType,
  side: 'buy' | 'sell',
  data: Omit<StrategyCatalogEntry, 'name' | 'side' | 'note' | 'testScenarios' | 'onExecute'>,
): StrategyCatalogEntry => ({
  name,
  side,
  note: STRATEGY_DISCLAIMER,
  testScenarios: STRATEGY_TEST_SCENARIOS[name],
  onExecute: STRATEGY_ON_EXECUTE[name],
  ...data,
});

export const STRATEGY_CATALOG: StrategyCatalogEntry[] = [
  entry('Fixed Price Buy', 'buy', {
    purpose: 'Place a buy order at the exact price you choose.',
    bestFor: 'Known entry price without extra conditions.',
    howItWorks: [
      'Monitors live LTP on each scan.',
      'Places a limit buy when LTP is at or below your target.',
      'Risk guard checks run before the order is sent to TMS.',
    ],
    expectedBehavior: [
      'LTP above target → status stays Monitoring (no order).',
      'LTP at or below target → EXECUTE at your target price.',
    ],
    requiredData: ['Symbol', 'LTP', 'Target buy price'],
    example: 'Target Rs. 198. LTP 200 → wait. LTP 198 → buy limit at 198.',
  }),
  entry('Quality Pullback Recovery Buy', 'buy', {
    purpose: 'Buy quality stocks after a pullback starts recovering.',
    bestFor: 'Default smart buy when fundamentals and technicals align.',
    howItWorks: [
      'Checks ROE, earnings growth, PE/PBV quality filters.',
      'Requires bullish MACD, RSI/MFI in range, and live recovery above open.',
      'Buy score must meet your minimum threshold.',
    ],
    expectedBehavior: [
      'Score below minimum or weak setup → WATCH / NO_TRADE.',
      'Quality + recovery + score ≥ threshold → EXECUTE at LTP.',
    ],
    requiredData: ['Live snapshot', 'Nepse Alpha fundamentals', 'Scan history'],
    example: 'Open 200, scans 197→199→201, score 68 → buy allowed.',
  }),
  entry('Confirmed Breakout Buy', 'buy', {
    purpose: 'Buy when price breaks above the day high with confirmation.',
    bestFor: 'Momentum entries after strength is confirmed.',
    howItWorks: [
      'LTP must break high/open/prev close.',
      'Last 3 scans must rise with volume increase.',
      'Rejects overbought RSI or change % above 6%.',
    ],
    expectedBehavior: [
      'Chasing (+6% day) → NO_TRADE.',
      'Confirmed breakout with rising scans → EXECUTE.',
    ],
    requiredData: ['Live snapshot', 'Scan history', 'RSI'],
    example: 'High 202, scans 200→201→203, volume up → buy.',
  }),
  entry('Smart Pullback Buy', 'buy', {
    purpose: 'Buy after a controlled pullback from the day high recovers.',
    bestFor: 'Pullback entries (replaces Dip Buy / Buy Below Price).',
    howItWorks: [
      'Pullback 1.5%–4% from day high.',
      'Last scans must show recovery, not continued falling.',
      'Optional trigger price for simpler limit entries.',
    ],
    expectedBehavior: [
      'Still falling or no pullback → TRACK.',
      'Pullback + recovery scans → EXECUTE.',
    ],
    requiredData: ['Live snapshot', 'Scan history'],
    example: 'High 202, LTP 196, scans 196→198→199 → buy.',
  }),
  entry('Mean Reversion Bounce Buy', 'buy', {
    purpose: 'Buy mean-reverting setups after a bounce confirms.',
    bestFor: 'Oversold mean-reverting names with bounce confirmation.',
    howItWorks: [
      'Requires mean-reverting 3M trend and low stochastic/%B.',
      'Bounce must show rising LTP and volume.',
      'Beta and Sharpe risk filters apply.',
    ],
    expectedBehavior: [
      'Setup weak → WATCH.',
      'Mean reversion + bounce → EXECUTE or WATCH with high score.',
    ],
    requiredData: ['Nepse Alpha details', 'Live snapshot', 'Scan history'],
    example: 'Stochastic 25, scans rising, mean-reverting trend → buy/watch.',
  }),
  entry('Order Book Strength Buy', 'buy', {
    purpose: 'Buy when top-of-book buy pressure is strong and price rises.',
    bestFor: 'Short-term entries when market depth is available.',
    howItWorks: [
      'Buy pressure from top 5 levels must be ≥ 60%.',
      'LTP must be above open and rising.',
      'Skipped when depth is unavailable.',
    ],
    expectedBehavior: [
      'No depth → SKIP (not a failure).',
      'Strong buy pressure + rising LTP → EXECUTE.',
    ],
    requiredData: ['Market depth', 'Live snapshot'],
    example: 'Buy qty 60% of book, LTP rising → buy.',
  }),
  entry('Time-Based Buy', 'buy', {
    purpose: 'Wrap any buy strategy with an expiry time.',
    bestFor: 'Trying a setup only until a selected Nepal time.',
    howItWorks: [
      'Delegates to wrapped buy strategy while before expiry.',
      'At expiry → order cancelled (EXPIRE).',
    ],
    expectedBehavior: [
      'Before expiry → wrapped strategy rules apply.',
      'After expiry → EXPIRE / cancelled.',
    ],
    requiredData: ['Wrapped strategy fields', 'Expiry time'],
    example: 'Quality Pullback until 2:30 PM → cancel if not triggered.',
  }),
  entry('Fixed Price Sell', 'sell', {
    purpose: 'Sell at your chosen target price.',
    bestFor: 'Simple target exits.',
    howItWorks: [
      'Monitors LTP until it reaches target sell price.',
      'Places limit sell when condition is met.',
    ],
    expectedBehavior: [
      'LTP below target → TRACK.',
      'LTP at or above target → EXECUTE at target.',
    ],
    requiredData: ['LTP', 'Target sell price', 'Holdings'],
    example: 'Target 220, LTP 218 → wait. LTP 220 → sell at 220.',
  }),
  entry('Capital Protection Sell', 'sell', {
    purpose: 'Intelligent trailing stop-loss with volatility-aware trail and depth-aware confirmation.',
    bestFor: 'Protecting capital on open positions in NEPSE.',
    howItWorks: [
      'Skips scans when last trade is older than 30 minutes (stale data guard).',
      'Widens trailing % on wider intraday high-low range (volatility proxy).',
      'hard_stop = entry × (1 − stop %); trail_stop = highest × (1 − trailing %).',
      'Break-even lifts stop to entry after highest LTP ≥ entry × 1.015.',
      'effective_stop = max(hard, trail, break-even).',
      'New peak → trail ratchets up and resets confirmation scans.',
      'Below stop: strong bid support can defer sell; otherwise 2 scans confirm then sell.',
      'Sell limit clamped to live LTP (not above market).',
    ],
    expectedBehavior: [
      'Stale last trade → SKIP, no state change.',
      'LTP above effective stop → TRACK safe, scans reset.',
      'New high → TRACK new peak, trailing stop raised.',
      'LTP at/below stop → 1st scan confirms, 2nd scan sells (unless bids defend stop).',
      'Strong top-5 bid support at/above stop → TRACK, scans reset.',
    ],
    requiredData: ['Entry/average price', 'LTP', 'High/low/prev close', 'Last traded time', 'Market depth (optional)'],
    example: 'Entry 400, peak 420, 3% trail → stop ≈ 407.4. LTP 408 → safe. LTP 407 twice → sell near LTP.',
  }),
  entry('Profit Ladder Sell', 'sell', {
    purpose: 'Sell partial quantity at profit targets.',
    bestFor: 'Booking profits in steps.',
    howItWorks: [
      'Target 1: sell configured % at +4%.',
      'Target 2: sell configured % at +8%.',
      'Tracks highest price while waiting.',
    ],
    expectedBehavior: [
      'Below targets → TRACK highest price.',
      'Target hit → EXECUTE partial qty at LTP/top buy (clamped).',
    ],
    requiredData: ['Entry price', 'Holdings', 'Target percentages'],
    example: '100 kitta @ 200. LTP 208 → sell 30. LTP 216 → sell 30 more.',
  }),
  entry('Trailing Runner Sell', 'sell', {
    purpose: 'Trail remaining quantity with a trailing stop.',
    bestFor: 'Letting winners run after partial profits.',
    howItWorks: [
      'Tracks highest price after activation.',
      'Trailing stop = highest × (1 − trailing %).',
      'Sells when LTP falls to trail.',
    ],
    expectedBehavior: [
      'New highs → stop ratchets up.',
      'LTP ≤ trail → EXECUTE remaining qty.',
    ],
    requiredData: ['Highest tracked price', 'Trailing %', 'Holdings'],
    example: 'Peak 230, 3% trail → stop 223.1. LTP 223 → sell.',
  }),
  entry('Technical Weakness Sell', 'sell', {
    purpose: 'Exit on combined technical and live price weakness.',
    bestFor: 'Cutting when indicators and price both weaken.',
    howItWorks: [
      'Technical weak: bearish MACD, low RSI/MFI, or down volume.',
      'Price weak: below open/prev close with 3 falling scans.',
      'Both required to trigger.',
    ],
    expectedBehavior: [
      'Only one weak signal → WATCH.',
      'Both weak → EXECUTE sell.',
    ],
    requiredData: ['Nepse Alpha technicals', 'Scan history', 'LTP'],
    example: 'MACD bearish, RSI 32, scans 200→198→196 → sell.',
  }),
  entry('Emergency Exit by Top Buyer', 'sell', {
    purpose: 'Exit quickly using the best available buyer.',
    bestFor: 'Urgent exits when depth exists.',
    howItWorks: [
      'Uses highest top-buy price when depth available.',
      'Optional split across buyer levels.',
      'Falls back to LTP when depth missing.',
    ],
    expectedBehavior: [
      'Emergency confirmed + depth → EXECUTE at top buy (clamped).',
      'No depth → EXECUTE at LTP fallback.',
    ],
    requiredData: ['Holdings', 'Market depth or LTP'],
    example: 'Top buyer 198 × 40 → sell 40 at 198.',
  }),
  entry('Time-Based Exit', 'sell', {
    purpose: 'Exit or cancel by a scheduled Nepal time.',
    bestFor: 'End-of-day or timed exits.',
    howItWorks: [
      'Before expiry → monitors like Capital Protection / emergency rules.',
      'At expiry → sell via top buy or cancel per action.',
    ],
    expectedBehavior: [
      'Before expiry → TRACK / strategy rules.',
      'At expiry with Sell using Top Buy → emergency exit.',
      'At expiry with Cancel → EXPIRE.',
    ],
    requiredData: ['Expiry time', 'Holdings', 'Expiry action'],
    example: 'Exit at 3:00 PM → sell to top buyer or LTP fallback.',
  }),
];

export const STRATEGY_CATALOG_BY_NAME = Object.fromEntries(
  STRATEGY_CATALOG.map((item) => [item.name, item]),
) as Record<StrategyType, StrategyCatalogEntry>;

export const getStrategyCatalogEntry = (name: string, side: 'buy' | 'sell' = 'buy') => {
  const normalized = (STRATEGY_CATALOG_BY_NAME as Record<string, StrategyCatalogEntry | undefined>)[name];
  if (normalized) {
    return normalized;
  }
  return STRATEGY_CATALOG.find((item) => item.side === side);
};
