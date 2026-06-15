import React from 'react';
import './StrategyDetails.css';

interface StrategyInfo {
  name: string;
  purpose: string;
  bestFor: string;
  howItWorks: string[];
  example: string;
  note: string;
}

const BUY_STRATEGIES: StrategyInfo[] = [
  {
    name: 'Fixed Price Buy',
    purpose: 'Place a buy order at the exact price you choose.',
    bestFor: 'You already know the price where you want to buy and do not need extra conditions.',
    howItWorks: [
      'You choose script, quantity, and buy price.',
      'The monitor watches the live market price and available sellers.',
      'When the order can be placed at your selected price, it sends a normal buy order.',
      'If the price never reaches your condition, the strategy stays pending until you cancel or stop monitoring.',
    ],
    example: 'You want to buy NABIL only at Rs. 500. If sellers become available around Rs. 500, the system places the buy order for your selected quantity.',
    note: 'Use this like a simple limit-style buy rule.',
  },
  {
    name: 'Buy Below Price',
    purpose: 'Buy only after price falls to your trigger price or lower.',
    bestFor: 'Waiting for a pullback instead of buying immediately.',
    howItWorks: [
      'You enter a trigger price below the current market price.',
      'The system keeps checking LTP and market depth.',
      'When LTP is equal to or below your trigger, it prepares the buy order.',
      'The order uses your selected quantity and price rules from the ticket.',
    ],
    example: 'LTP is Rs. 540 and you set Buy Below Price at Rs. 520. If LTP reaches Rs. 520 or lower, the system can place the buy order.',
    note: 'Useful when you want a better entry after a dip.',
  },
  {
    name: 'Breakout Buy',
    purpose: 'Buy when price moves up through your breakout level.',
    bestFor: 'Entering only after strength appears in the market.',
    howItWorks: [
      'You set a breakout trigger above or near the current price.',
      'The monitor watches whether LTP reaches or crosses that trigger.',
      'After the trigger is reached, it places the buy order using the configured quantity.',
      'If price never reaches the breakout level, no buy order is sent.',
    ],
    example: 'LTP is Rs. 480 and resistance is near Rs. 500. You set breakout at Rs. 501. If LTP reaches Rs. 501, the strategy can buy.',
    note: 'Breakout buys can be fast-moving, so use a price you are comfortable with.',
  },
  {
    name: 'Dip Buy',
    purpose: 'Buy after the stock drops to your planned dip price.',
    bestFor: 'Buying a stock you like only when it becomes cheaper.',
    howItWorks: [
      'You set a dip price where you are willing to enter.',
      'The system waits while the price is above that dip price.',
      'When price drops to the dip level, the buy condition becomes active.',
      'It then sends the buy order using the selected quantity and price.',
    ],
    example: 'You like a stock at Rs. 300 but want it near Rs. 285. Set Dip Buy at Rs. 285. If LTP drops to Rs. 285, the system can place the buy.',
    note: 'Similar to Buy Below Price, but framed for planned dip entries.',
  },
  {
    name: 'Time-Based Buy',
    purpose: 'Keep a buy strategy active only until a selected Nepal time.',
    bestFor: 'Trying a buy setup for a limited window, then stopping automatically.',
    howItWorks: [
      'You choose the trigger, quantity, and expiry date/time in Nepal Time.',
      'The system monitors until either the buy condition triggers or the expiry time arrives.',
      'If the condition triggers before expiry, it places the buy order.',
      'If expiry arrives first, monitoring for that strategy stops.',
    ],
    example: 'You want to buy HIDCL at Rs. 210 only before 2:30 PM Nepal Time. If it reaches Rs. 210 before 2:30 PM, the order can place. If not, the strategy expires.',
    note: 'The expiry field is interpreted as Nepal Time.',
  },
];

const SELL_STRATEGIES: StrategyInfo[] = [
  {
    name: 'Fixed Price Sell',
    purpose: 'Place a sell order at the exact price you choose.',
    bestFor: 'You know the target price where you want to exit.',
    howItWorks: [
      'You choose script, quantity, and sell price.',
      'The monitor watches live LTP and buyers.',
      'When the market can support your selected sell price, it sends a normal sell order.',
      'If price does not reach your level, the strategy remains pending.',
    ],
    example: 'You own 100 kitta at average Rs. 450 and want to sell at Rs. 500. Set Fixed Price Sell at Rs. 500.',
    note: 'Use this for a simple target exit.',
  },
  {
    name: 'Fast Stop Loss',
    purpose: 'Exit quickly if price falls to your stop-loss trigger.',
    bestFor: 'Limiting loss or protecting capital during a fast drop.',
    howItWorks: [
      'You set a stop-loss trigger below current LTP.',
      'The system watches for LTP to fall to or below that trigger.',
      'Once triggered, it uses the best available buyer price to exit quickly.',
      'Because it prioritizes speed, final execution price can be lower than your trigger.',
    ],
    example: 'You bought at Rs. 500 and want to cut risk at Rs. 475. If LTP falls to Rs. 475, Fast Stop Loss tries to sell quickly.',
    note: 'This can have slippage in a fast market.',
  },
  {
    name: 'Stop Limit Sell',
    purpose: 'Trigger a sell only after price falls, but protect the minimum sell price.',
    bestFor: 'You want stop-loss protection but do not want to sell below a limit.',
    howItWorks: [
      'You set a stop trigger and a minimum sell price.',
      'When LTP reaches the stop trigger, the system places a limit sell order.',
      'The order will not sell below your minimum limit.',
      'If the market drops too quickly below your limit, the order may not fill.',
    ],
    example: 'LTP is Rs. 500. You set stop trigger Rs. 480 and minimum sell price Rs. 475. If LTP reaches Rs. 480, it places sell at Rs. 475 or better.',
    note: 'Safer on price, less certain on execution.',
  },
  {
    name: 'Trailing Stop Loss',
    purpose: 'Let profit run, then sell after price pulls back by your chosen percent.',
    bestFor: 'Riding an uptrend without manually moving your stop-loss.',
    howItWorks: [
      'The system tracks the highest price seen after the strategy starts.',
      'Your trailing percent creates a moving stop below that high price.',
      'If price keeps rising, the stop also moves up.',
      'If price falls by the trailing percent from the high, it triggers a sell.',
    ],
    example: 'Price rises from Rs. 500 to Rs. 550 and trailing drop is 2%. The stop becomes around Rs. 539. If price falls to that level, it sells.',
    note: 'A tighter percent exits earlier; a wider percent gives the stock more room.',
  },
  {
    name: 'Smart Profit Booking',
    purpose: 'Avoid selling immediately at target; wait and sell after momentum weakens.',
    bestFor: 'Booking profit while giving the stock a chance to move higher.',
    howItWorks: [
      'You set a profit target price.',
      'After target is reached, the system waits for the minimum wait time.',
      'It tracks the highest price after target and checks for a confirmed drop.',
      'When the drop condition is confirmed, it sells to book profit.',
    ],
    example: 'Target is Rs. 600. Price reaches Rs. 600, then climbs to Rs. 625. If it later drops by your trailing rule, the strategy sells near the pullback instead of selling at Rs. 600.',
    note: 'Useful when a stock may continue rising after your first target.',
  },
  {
    name: 'Book Profit + Stop Loss',
    purpose: 'Use profit-taking and loss protection together.',
    bestFor: 'Managing both upside target and downside risk in one strategy.',
    howItWorks: [
      'You set a book-profit trigger above LTP and a stop-loss trigger below LTP.',
      'The system watches both conditions at the same time.',
      'If profit target triggers first, it exits for profit.',
      'If stop-loss triggers first, it exits for protection. Only one side executes.',
    ],
    example: 'LTP is Rs. 500. Book profit is Rs. 560 and stop-loss is Rs. 475. If Rs. 560 comes first, it sells for profit. If Rs. 475 comes first, it sells for protection.',
    note: 'Good when you want a planned target and a safety exit.',
  },
  {
    name: 'Partial Profit Booking',
    purpose: 'Sell in multiple parts instead of exiting all at once.',
    bestFor: 'Locking some profit while keeping part of the position open.',
    howItWorks: [
      'You set first and second target prices with sell percentages.',
      'When the first target hits, it sells the first portion.',
      'When the second target hits, it sells the second portion.',
      'Any remaining quantity can continue with trailing protection depending on setup.',
    ],
    example: 'You hold 100 kitta. Sell 30% at Rs. 550 and another 30% at Rs. 600. The remaining 40 kitta stays available for further upside or protection.',
    note: 'Useful when you do not want to exit the full position too early.',
  },
  {
    name: 'Break-Even Protection',
    purpose: 'Protect your capital after the trade starts moving in profit.',
    bestFor: 'Letting a profitable trade continue while reducing the chance of loss.',
    howItWorks: [
      'You provide your average buy price.',
      'After price moves in your favor, the strategy protects around your break-even level.',
      'If price reverses back near the protected level, it sells.',
      'If price keeps rising, it can continue tracking higher protection levels.',
    ],
    example: 'Average buy is Rs. 400. Price rises to Rs. 440. The strategy can protect near Rs. 400 or better, so a reversal does not turn the trade into a loss.',
    note: 'Best after a position has already moved into profit.',
  },
  {
    name: 'Time-Based Exit',
    purpose: 'Stop or exit a sell strategy after a selected Nepal time.',
    bestFor: 'Avoiding strategies that stay active longer than intended.',
    howItWorks: [
      'You choose an expiry date/time in Nepal Time.',
      'The system monitors the sell rule until that time.',
      'If the rule triggers before expiry, it executes normally.',
      'If expiry arrives first, it follows your selected expiry action.',
    ],
    example: 'You want to sell at Rs. 700 only before 2:45 PM Nepal Time. If price does not reach Rs. 700 by then, the strategy can cancel or follow your selected expiry action.',
    note: 'Expiry is based on Nepal Time.',
  },
  {
    name: 'Emergency Exit',
    purpose: 'Exit immediately using the best available buyer price.',
    bestFor: 'Situations where getting out quickly matters more than exact price.',
    howItWorks: [
      'You confirm emergency execution risk.',
      'The system checks current buyers in market depth.',
      'It attempts to place the sell order against the best available buyer price.',
      'Execution may happen with slippage depending on liquidity.',
    ],
    example: 'You hold a stock and news changes your risk. Emergency Exit tries to sell quickly at the current best buyer price instead of waiting for a target.',
    note: 'Use carefully. This prioritizes speed over price control.',
  },
];

const StrategyToggle: React.FC<{ strategy: StrategyInfo; tone: 'buy' | 'sell'; open?: boolean }> = ({
  strategy,
  tone,
  open = false,
}) => (
  <details className={`strategy-toggle ${tone}`} open={open}>
    <summary>
      <span className="strategy-toggle-chevron" aria-hidden="true">›</span>
      <span className="strategy-toggle-main">
        <strong>{strategy.name}</strong>
        <span>{strategy.purpose}</span>
      </span>
      <span className={`strategy-details-pill ${tone}`}>{tone.toUpperCase()}</span>
    </summary>
    <div className="strategy-toggle-body">
      <div className="strategy-detail-block">
        <h4>Best For</h4>
        <p>{strategy.bestFor}</p>
      </div>
      <div className="strategy-detail-block">
        <h4>How It Works</h4>
        <ol>
          {strategy.howItWorks.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
      </div>
      <div className="strategy-example">
        <h4>Example</h4>
        <p>{strategy.example}</p>
      </div>
      <p className="strategy-note">{strategy.note}</p>
    </div>
  </details>
);

const StrategySection: React.FC<{ title: string; tone: 'buy' | 'sell'; strategies: StrategyInfo[] }> = ({
  title,
  tone,
  strategies,
}) => (
  <section className="strategy-details-section panel">
    <div className="strategy-details-section-header">
      <div>
        <h3>{title}</h3>
        <p>Click a strategy to expand the details.</p>
      </div>
      <span className={`strategy-details-pill ${tone}`}>{tone.toUpperCase()}</span>
    </div>
    <div className="strategy-toggle-list">
      {strategies.map((strategy, index) => (
        <StrategyToggle key={strategy.name} strategy={strategy} tone={tone} open={index === 0} />
      ))}
    </div>
  </section>
);

const StrategyDetails: React.FC = () => (
  <div className="strategy-details-page">
    <div className="strategy-details-hero panel">
      <div>
        <h2>Strategy Details</h2>
        <p>
          Learn what each buy and sell strategy does before scheduling it. These are automation rules,
          not stock recommendations.
        </p>
      </div>
    </div>

    <StrategySection title="Buy Strategies" tone="buy" strategies={BUY_STRATEGIES} />
    <StrategySection title="Sell Strategies" tone="sell" strategies={SELL_STRATEGIES} />
  </div>
);

export default StrategyDetails;
