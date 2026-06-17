import React from 'react';
import './StrategyDetails.css';
import { STRATEGY_DISCLAIMER } from '../../lib/strategies';

interface StrategyInfo {
  name: string;
  purpose: string;
  bestFor: string;
  howItWorks: string[];
  requiredData: string[];
  example: string;
  note: string;
}

const BUY_STRATEGIES: StrategyInfo[] = [
  {
    name: 'Fixed Price Buy',
    purpose: 'Place a buy order at the exact price you choose.',
    bestFor: 'Known entry price without extra conditions.',
    howItWorks: ['Monitor LTP until it reaches your target buy price.', 'Place a limit buy when condition is met.', 'Risk guard checks run before order placement.'],
    requiredData: ['Symbol', 'LTP', 'Target buy price'],
    example: 'Target buy Rs. 198. LTP 200 → no buy. LTP 198 → buy if risk guard passes.',
    note: STRATEGY_DISCLAIMER,
  },
  {
    name: 'Quality Pullback Recovery Buy',
    purpose: 'Buy fundamentally decent stocks after a pullback starts recovering.',
    bestFor: 'Default intelligent buy when quality + technical setup align.',
    howItWorks: ['Checks ROE, earnings growth, PE/PBV quality filters.', 'Requires bullish MACD, RSI/MFI in range, and live recovery above open.', 'Buy score must meet your minimum threshold.'],
    requiredData: ['Live snapshot', 'Nepse Alpha fundamentals/technicals', 'Scan history'],
    example: 'Open 200, low 195, scans 197→199→201 with rising volume and score ≥ 65 → buy allowed.',
    note: STRATEGY_DISCLAIMER,
  },
  {
    name: 'Confirmed Breakout Buy',
    purpose: 'Buy when price breaks above the day high with confirmation.',
    bestFor: 'Momentum entries after strength is confirmed.',
    howItWorks: ['LTP must break high/open/prev close.', 'Last 3 scans must rise with volume increase.', 'Rejects overbought RSI or change % above 6%.'],
    requiredData: ['Live snapshot', 'Scan history', 'Optional Nepse Alpha RSI'],
    example: 'High 202, scans 200→201→203 with volume up → buy allowed.',
    note: STRATEGY_DISCLAIMER,
  },
  {
    name: 'Smart Pullback Buy',
    purpose: 'Buy after a controlled pullback from the day high starts recovering.',
    bestFor: 'Pullback entries (replaces Buy Below Price and Dip Buy).',
    howItWorks: ['Pullback 1.5%–4% from day high.', 'Last scans must show recovery, not continued falling.', 'Optional trigger price for simpler limit-style entries.'],
    requiredData: ['Live snapshot', 'Scan history'],
    example: 'High 202, LTP falls to 196 then scans 196→198→199 → buy allowed.',
    note: STRATEGY_DISCLAIMER,
  },
  {
    name: 'Mean Reversion Bounce Buy',
    purpose: 'Buy mean-reverting setups after a bounce confirms.',
    bestFor: 'Stocks with mean-reverting 3M trend and oversold stochastic/%B.',
    howItWorks: ['Requires Nepse Alpha mean-reversion trend and low stochastic/%B.', 'Bounce must show rising LTP and volume.', 'Beta and Sharpe risk filters apply.'],
    requiredData: ['Nepse Alpha script details', 'Live snapshot', 'Scan history'],
    example: '3M trend mean reverting, RSI 46, stochastic 25, scans rising → buy or watch.',
    note: STRATEGY_DISCLAIMER,
  },
  {
    name: 'Order Book Strength Buy',
    purpose: 'Buy when top-of-book buy pressure is strong and price is rising.',
    bestFor: 'Short-term entries when market depth is available.',
    howItWorks: ['Buy pressure from top 5 levels must be ≥ 60%.', 'LTP must be above open and rising.', 'Skipped (not failed) when depth unavailable.'],
    requiredData: ['Market depth (top buy/sell orders)', 'Live snapshot'],
    example: 'Buy qty 40k vs sell 20k, scans 200→201 → buy allowed.',
    note: STRATEGY_DISCLAIMER,
  },
  {
    name: 'Time-Based Buy',
    purpose: 'Wrap any buy strategy with an expiry time.',
    bestFor: 'Trying a setup only until a selected Nepal time.',
    howItWorks: ['Choose wrapped buy strategy + expiry.', 'Cancels if expiry passes before trigger.', 'Delegates to the wrapped strategy while active.'],
    requiredData: ['Wrapped strategy fields', 'Expiry time (Nepal Time)'],
    example: 'Quality Pullback Recovery Buy until 2:30 PM Nepal Time.',
    note: STRATEGY_DISCLAIMER,
  },
];

const SELL_STRATEGIES: StrategyInfo[] = [
  {
    name: 'Fixed Price Sell',
    purpose: 'Sell at your chosen target price.',
    bestFor: 'Simple target exits.',
    howItWorks: ['Monitor LTP until it reaches target sell price.', 'Place limit sell when condition is met.'],
    requiredData: ['Symbol', 'LTP', 'Target sell price', 'Holdings'],
    example: 'Target 220, LTP 218 → no sell. LTP 220 → sell.',
    note: STRATEGY_DISCLAIMER,
  },
  {
    name: 'Capital Protection Sell',
    purpose: 'Stop-loss and break-even protection combined.',
    bestFor: 'Protecting capital (replaces Fast Stop Loss, Stop Limit, Break-Even).',
    howItWorks: ['Initial stop = entry × (1 − stop loss %).', 'After break-even trigger, stop moves to entry.', 'Legacy stop-limit orders still honored.'],
    requiredData: ['Entry/average price', 'Stop loss %', 'Live LTP'],
    example: 'Buy 200, stop 3% → sell at 194. After 206, stop moves to 200.',
    note: STRATEGY_DISCLAIMER,
  },
  {
    name: 'Profit Ladder Sell',
    purpose: 'Sell partial quantity at target levels.',
    bestFor: 'Booking profits in steps (replaces Smart/Partial profit strategies).',
    howItWorks: ['Target 1: sell configured % at +4%.', 'Target 2: sell configured % at +8%.', 'Uses partial_legs or default ladder settings.'],
    requiredData: ['Entry price', 'Holdings', 'Target percentages'],
    example: '100 kitta at 200. LTP 208 → sell 30. LTP 216 → sell 30 more.',
    note: STRATEGY_DISCLAIMER,
  },
  {
    name: 'Trailing Runner Sell',
    purpose: 'Trail remaining quantity after profit ladder.',
    bestFor: 'Letting winners run with a trailing stop.',
    howItWorks: ['Tracks highest price after buy.', 'Trailing stop = highest × (1 − trailing %).', 'Sells remaining qty when LTP hits trail.'],
    requiredData: ['Highest tracked price', 'Remaining quantity', 'Trailing stop %'],
    example: 'Rise to 230, 3% trail → stop 223.10. LTP 223 → sell remaining.',
    note: STRATEGY_DISCLAIMER,
  },
  {
    name: 'Technical Weakness Sell',
    purpose: 'Exit on combined technical and live price weakness.',
    bestFor: 'Cutting when MACD/RSI/volume trend turn weak.',
    howItWorks: ['Technical weak: bearish MACD, low RSI/MFI, or down volume trend.', 'Price weak: below open/prev close with 3 falling scans.', 'Both required to trigger.'],
    requiredData: ['Nepse Alpha technicals', 'Live snapshot', 'Scan history'],
    example: 'MACD bearish, RSI 32, scans 200→198→196 → sell.',
    note: STRATEGY_DISCLAIMER,
  },
  {
    name: 'Emergency Exit by Top Buyer',
    purpose: 'Exit quickly using best available buyer.',
    bestFor: 'Urgent exits when depth is available.',
    howItWorks: ['Sort top buyers by price, sell to highest.', 'Optional split across multiple buyer levels.', 'Falls back to LTP when depth unavailable.'],
    requiredData: ['Holdings', 'Market depth or LTP'],
    example: '100 kitta, top buyer Rs. 198 × 40 → sell 40 at 198.',
    note: STRATEGY_DISCLAIMER,
  },
  {
    name: 'Time-Based Exit',
    purpose: 'Exit or cancel by a scheduled Nepal time.',
    bestFor: 'End-of-day or timed exits.',
    howItWorks: ['At expiry, sell to best buyer or cancel based on action.', 'Uses emergency exit logic when selling.'],
    requiredData: ['Expiry time', 'Holdings'],
    example: 'Exit at 3:00 PM using top buyer or LTP fallback.',
    note: STRATEGY_DISCLAIMER,
  },
];

const StrategyDetails: React.FC = () => (
  <div className="strategy-details-page">
    <header className="strategy-details-header">
      <h2>Strategy Details</h2>
      <p>{STRATEGY_DISCLAIMER}</p>
    </header>

    <section>
      <h3>Buy Strategies</h3>
      <div className="strategy-details-grid">
        {BUY_STRATEGIES.map((strategy) => (
          <article key={strategy.name} className="strategy-details-card">
            <h4>{strategy.name}</h4>
            <p><strong>Best for:</strong> {strategy.bestFor}</p>
            <p>{strategy.purpose}</p>
            <p><strong>How it works</strong></p>
            <ul>{strategy.howItWorks.map((line) => <li key={line}>{line}</li>)}</ul>
            <p><strong>Required data:</strong> {strategy.requiredData.join(', ')}</p>
            <p><strong>Example:</strong> {strategy.example}</p>
            <p className="strategy-details-note">{strategy.note}</p>
          </article>
        ))}
      </div>
    </section>

    <section>
      <h3>Sell Strategies</h3>
      <div className="strategy-details-grid">
        {SELL_STRATEGIES.map((strategy) => (
          <article key={strategy.name} className="strategy-details-card">
            <h4>{strategy.name}</h4>
            <p><strong>Best for:</strong> {strategy.bestFor}</p>
            <p>{strategy.purpose}</p>
            <p><strong>How it works</strong></p>
            <ul>{strategy.howItWorks.map((line) => <li key={line}>{line}</li>)}</ul>
            <p><strong>Required data:</strong> {strategy.requiredData.join(', ')}</p>
            <p><strong>Example:</strong> {strategy.example}</p>
            <p className="strategy-details-note">{strategy.note}</p>
          </article>
        ))}
      </div>
    </section>
  </div>
);

export default StrategyDetails;
