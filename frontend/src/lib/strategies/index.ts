export type StrategyType =
  | 'Fixed Price Buy'
  | 'Quality Pullback Recovery Buy'
  | 'Confirmed Breakout Buy'
  | 'Smart Pullback Buy'
  | 'Mean Reversion Bounce Buy'
  | 'Order Book Strength Buy'
  | 'Time-Based Buy'
  | 'Technical Buy'
  | 'Custom Query'
  | 'Custom Query Buy'
  | 'Fixed Price Sell'
  | 'Capital Protection Sell'
  | 'Profit Ladder Sell'
  | 'Trailing Runner Sell'
  | 'Technical Weakness Sell'
  | 'Emergency Exit by Top Buyer'
  | 'Time-Based Exit'
  | 'Technical Sell'
  | 'Custom Query Sell';

export const STRATEGY_ALIASES: Record<string, StrategyType> = {
  'Fixed Price': 'Fixed Price Buy',
  'Buy Below Price': 'Smart Pullback Buy',
  'Dip Buy': 'Smart Pullback Buy',
  'Breakout Buy': 'Confirmed Breakout Buy',
  'Fast Stop Loss': 'Capital Protection Sell',
  'Stop Limit Sell': 'Capital Protection Sell',
  'Break-Even Protection': 'Capital Protection Sell',
  'Smart Profit Booking': 'Profit Ladder Sell',
  'Book Profit + Stop Loss': 'Profit Ladder Sell',
  'Partial Profit Booking': 'Profit Ladder Sell',
  'Trailing Stop Loss': 'Trailing Runner Sell',
  'Emergency Exit': 'Emergency Exit by Top Buyer',
};

export const BUY_STRATEGIES: StrategyType[] = [
  'Fixed Price Buy',
  'Quality Pullback Recovery Buy',
  'Confirmed Breakout Buy',
  'Smart Pullback Buy',
  'Mean Reversion Bounce Buy',
  'Order Book Strength Buy',
  'Time-Based Buy',
  'Technical Buy',
  'Custom Query',
];

export const SELL_STRATEGIES: StrategyType[] = [
  'Fixed Price Sell',
  'Capital Protection Sell',
  'Profit Ladder Sell',
  'Trailing Runner Sell',
  'Technical Weakness Sell',
  'Emergency Exit by Top Buyer',
  'Time-Based Exit',
  'Technical Sell',
  'Custom Query',
];

export const DEFAULT_SMART_STRATEGY = {
  buy: 'Quality Pullback Recovery Buy' as StrategyType,
  sell: 'Capital Protection Sell' as StrategyType,
  strategy_config: {
    min_buy_score: 65,
    stop_loss_pct: 3,
    break_even_trigger_pct: 3,
    target1_pct: 4,
    target1_sell_pct: 30,
    target2_pct: 8,
    target2_sell_pct: 30,
    trailing_stop_pct: 3,
    order_timeout_minutes: 3,
    max_capital_per_stock_pct: 10,
  },
};

export const formatStrategyLabel = (value: string, side = 'buy') => {
  const normalized = value.trim();
  if (normalized === 'Fixed Price') {
    return side === 'sell' ? 'Fixed Price Sell' : 'Fixed Price Buy';
  }
  return STRATEGY_ALIASES[normalized] || normalized;
};

export const STRATEGY_DISCLAIMER =
  'These are automation rules, not stock recommendations. Trading involves risk.';
