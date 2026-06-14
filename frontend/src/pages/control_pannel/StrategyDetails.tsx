import React from 'react';
import './StrategyDetails.css';

interface StrategyInfo {
  name: string;
  purpose: string;
  logic: string;
}

const BUY_STRATEGIES: StrategyInfo[] = [
  {
    name: 'Fixed Price Buy',
    purpose: 'Place a normal buy order at your chosen price.',
    logic: 'The system waits until the market price is near your buy price, then places the buy order.',
  },
  {
    name: 'Buy Below Price',
    purpose: 'Buy only if price comes down to your trigger.',
    logic: 'If LTP goes to or below your trigger price, the buy order can execute.',
  },
  {
    name: 'Breakout Buy',
    purpose: 'Buy when price moves upward through your trigger.',
    logic: 'If LTP reaches or crosses your breakout price, the buy order can execute.',
  },
  {
    name: 'Dip Buy',
    purpose: 'Buy after a controlled price dip.',
    logic: 'If price drops to your selected dip price, the system prepares a buy order.',
  },
  {
    name: 'Time-Based Buy',
    purpose: 'Keep a buy rule active only until a selected time.',
    logic: 'The system monitors the rule until expiry. After expiry, it stops monitoring that buy strategy.',
  },
];

const SELL_STRATEGIES: StrategyInfo[] = [
  {
    name: 'Fixed Price Sell',
    purpose: 'Place a normal sell order at your chosen price.',
    logic: 'The system waits until the market price is near your sell price, then places the sell order.',
  },
  {
    name: 'Fast Stop Loss',
    purpose: 'Help limit loss when price falls quickly.',
    logic: 'If LTP falls to or below your stop-loss price, it tries to sell quickly using the best buyer price.',
  },
  {
    name: 'Stop Limit Sell',
    purpose: 'Protect your minimum sell price.',
    logic: 'When stop price is reached, it places a limit sell order. It may not fill if price falls too fast.',
  },
  {
    name: 'Trailing Stop Loss',
    purpose: 'Follow rising price and sell after a pullback.',
    logic: 'The system tracks the highest price. If price drops by your trailing percent, it sells.',
  },
  {
    name: 'Smart Profit Booking',
    purpose: 'Wait after target and avoid selling too early.',
    logic: 'After target is reached, it waits, tracks the highest price, and sells only after a confirmed drop.',
  },
  {
    name: 'Book Profit + Stop Loss',
    purpose: 'Use one profit rule and one protection rule together.',
    logic: 'If stop-loss triggers first, it sells. If profit rule triggers first, it sells. Only one side runs.',
  },
  {
    name: 'Partial Profit Booking',
    purpose: 'Sell in parts instead of all at once.',
    logic: 'It sells some quantity at first target, some at second target, and keeps remaining quantity with trailing protection.',
  },
  {
    name: 'Break-Even Protection',
    purpose: 'Protect the position after it becomes profitable.',
    logic: 'After activation, it protects near your average buy price plus buffer and can trail higher prices.',
  },
  {
    name: 'Time-Based Exit',
    purpose: 'Stop a sell strategy after a selected time.',
    logic: 'If nothing triggers before expiry, it follows your selected expiry action.',
  },
  {
    name: 'Emergency Exit',
    purpose: 'Exit quickly with user confirmation.',
    logic: 'It immediately tries to sell using the best available buyer price, with possible slippage.',
  },
];

const StrategySection: React.FC<{ title: string; tone: 'buy' | 'sell'; strategies: StrategyInfo[] }> = ({
  title,
  tone,
  strategies,
}) => (
  <section className="strategy-details-section">
    <div className="strategy-details-section-header">
      <h3>{title}</h3>
      <span className={`strategy-details-pill ${tone}`}>{tone.toUpperCase()}</span>
    </div>
    <div className="strategy-details-grid">
      {strategies.map((strategy) => (
        <article key={strategy.name} className="strategy-details-card">
          <h4>{strategy.name}</h4>
          <p><strong>Use:</strong> {strategy.purpose}</p>
          <p><strong>Logic:</strong> {strategy.logic}</p>
        </article>
      ))}
    </div>
  </section>
);

const StrategyDetails: React.FC = () => (
  <div className="strategy-details-page">
    <div className="strategy-details-hero panel">
      <div>
        <h2>Strategy Details</h2>
        <p>Short explanation of each buy and sell strategy. These are user-defined rules, not stock recommendations.</p>
      </div>
    </div>

    <StrategySection title="Buy Strategies" tone="buy" strategies={BUY_STRATEGIES} />
    <StrategySection title="Sell Strategies" tone="sell" strategies={SELL_STRATEGIES} />
  </div>
);

export default StrategyDetails;
