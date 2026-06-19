import { StrategyType } from './index';

export interface StrategyTestScenario {
  situation: string;
  action: string;
  order: string;
}

export const STRATEGY_TEST_SCENARIOS: Record<StrategyType, StrategyTestScenario[]> = {
  'Fixed Price Buy': [
    { situation: 'LTP above target', action: 'TRACK — keeps monitoring', order: 'No order' },
    { situation: 'LTP at or below target', action: 'EXECUTE', order: 'Limit BUY @ target price, full qty' },
  ],
  'Quality Pullback Recovery Buy': [
    { situation: 'Score below minimum', action: 'NO_TRADE', order: 'No order' },
    { situation: 'Falling scans', action: 'NO_TRADE', order: 'No order' },
    { situation: 'Quality + recovery + score OK', action: 'EXECUTE', order: 'Limit BUY @ live LTP, full qty' },
    { situation: 'Good score, setup not ready', action: 'WATCH', order: 'No order' },
  ],
  'Confirmed Breakout Buy': [
    { situation: 'Day change > 6% (chasing)', action: 'NO_TRADE', order: 'No order' },
    { situation: 'Breakout not confirmed', action: 'WATCH', order: 'No order' },
    { situation: 'Breakout + 3 rising scans + volume', action: 'EXECUTE', order: 'Limit BUY @ live LTP, full qty' },
  ],
  'Smart Pullback Buy': [
    { situation: 'LTP at/below trigger price', action: 'EXECUTE', order: 'Limit BUY @ trigger price, full qty' },
    { situation: 'Still falling', action: 'NO_TRADE', order: 'No order' },
    { situation: 'Pullback zone + recovery scans', action: 'EXECUTE', order: 'Limit BUY @ live LTP, full qty' },
  ],
  'Mean Reversion Bounce Buy': [
    { situation: 'No Nepse Alpha data', action: 'SKIP', order: 'No order' },
    { situation: 'Setup without bounce', action: 'WATCH', order: 'No order' },
    { situation: 'Mean reversion + bounce + score', action: 'EXECUTE', order: 'Limit BUY @ live LTP, full qty' },
  ],
  'Order Book Strength Buy': [
    { situation: 'Market depth unavailable', action: 'SKIP', order: 'No order (skipped, not failed)' },
    { situation: 'Buy pressure < 60%', action: 'WATCH', order: 'No order' },
    { situation: 'Buy pressure ≥ 60% + rising LTP', action: 'EXECUTE', order: 'Limit BUY @ live LTP, full qty' },
  ],
  'Time-Based Buy': [
    { situation: 'Before expiry', action: 'Delegates to wrapped buy strategy', order: 'Per wrapped strategy' },
    { situation: 'After expiry', action: 'EXPIRE — strategy cancelled', order: 'No order' },
  ],
  'Fixed Price Sell': [
    { situation: 'LTP below target', action: 'TRACK — keeps monitoring', order: 'No order' },
    { situation: 'LTP at or above target', action: 'EXECUTE', order: 'Limit SELL @ target price, full qty' },
  ],
  'Capital Protection Sell': [
    { situation: 'Last trade > 30 min old', action: 'SKIP — stale data', order: 'No order' },
    { situation: 'LTP above effective stop', action: 'TRACK — safe zone', order: 'No order' },
    { situation: 'New price peak', action: 'TRACK — trail ratcheted up', order: 'No order' },
    { situation: 'Bids defend stop (depth)', action: 'TRACK — depth support', order: 'No order' },
    { situation: 'LTP at/below stop — 1st scan', action: 'TRACK — confirming (1/2)', order: 'No order yet' },
    { situation: 'LTP still at/below stop — 2nd scan', action: 'EXECUTE', order: 'Limit SELL @ min(LTP, stop) clamped, full qty' },
  ],
  'Profit Ladder Sell': [
    { situation: 'Below profit targets', action: 'TRACK — tracks highest price', order: 'No order' },
    { situation: 'Target 1 hit (+4% default)', action: 'EXECUTE partial', order: 'Limit SELL @ LTP/top buy, ~30% qty' },
    { situation: 'Target 2 hit (+8% default)', action: 'EXECUTE partial', order: 'Limit SELL @ LTP/top buy, ~30% qty' },
  ],
  'Trailing Runner Sell': [
    { situation: 'Below activation (if set)', action: 'TRACK — waiting', order: 'No order' },
    { situation: 'New highs', action: 'TRACK — trail ratchets up', order: 'No order' },
    { situation: 'LTP ≤ trailing stop', action: 'EXECUTE', order: 'Limit SELL @ LTP/top buy, remaining qty' },
  ],
  'Technical Weakness Sell': [
    { situation: 'Only technical OR only price weak', action: 'WATCH', order: 'No order' },
    { situation: 'Both technical + price weakness', action: 'EXECUTE', order: 'Limit SELL @ LTP/top buy, full qty' },
  ],
  'Emergency Exit by Top Buyer': [
    { situation: 'Not confirmed', action: 'NO_TRADE', order: 'No order' },
    { situation: 'Depth available', action: 'EXECUTE', order: 'Limit SELL @ top buy price (clamped), full or split qty' },
    { situation: 'No depth', action: 'EXECUTE', order: 'Limit SELL @ LTP fallback, full qty' },
  ],
  'Time-Based Exit': [
    { situation: 'Before expiry', action: 'TRACK — monitoring', order: 'No order' },
    { situation: 'At expiry — cancel action', action: 'EXPIRE', order: 'No order' },
    { situation: 'At expiry — sell via top buy', action: 'EXECUTE', order: 'Emergency exit order @ top buy / LTP' },
  ],
};

export const STRATEGY_ON_EXECUTE: Record<StrategyType, string> = {
  'Fixed Price Buy': 'Sends a limit buy at your target price for the full scheduled quantity.',
  'Quality Pullback Recovery Buy': 'Sends a limit buy at the current LTP when quality, technicals, and recovery align.',
  'Confirmed Breakout Buy': 'Sends a limit buy at the current LTP after breakout confirmation.',
  'Smart Pullback Buy': 'Sends a limit buy at trigger price or current LTP after pullback recovery.',
  'Mean Reversion Bounce Buy': 'Sends a limit buy at the current LTP when mean-reversion bounce confirms.',
  'Order Book Strength Buy': 'Sends a limit buy at the current LTP when order-book pressure is strong.',
  'Time-Based Buy': 'No direct order — wraps another buy strategy until expiry.',
  'Fixed Price Sell': 'Sends a limit sell at your target price for the full quantity.',
  'Capital Protection Sell': 'Sends a limit sell clamped to live LTP; uses stale-data guard, volatility trail, depth support, and 2-scan confirmation.',
  'Profit Ladder Sell': 'Sends partial limit sells at LTP/top buy when each profit step is hit.',
  'Trailing Runner Sell': 'Sends a limit sell for remaining quantity when price hits the trailing stop.',
  'Technical Weakness Sell': 'Sends a limit sell at LTP/top buy when weakness is confirmed.',
  'Emergency Exit by Top Buyer': 'Sends an urgent limit sell to the best buyer price (or LTP if no depth).',
  'Time-Based Exit': 'At expiry either cancels or triggers an emergency-style sell.',
};
