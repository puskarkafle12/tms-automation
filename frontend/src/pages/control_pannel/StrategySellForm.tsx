import React, { useEffect, useMemo, useState } from 'react';
import './StrategySellForm.css';
import {
  StrategyPayload,
  StrategyType,
  toPositiveNumber,
  validateStrategyForm,
} from './strategyValidation';
export type { StrategyPayload, StrategyType } from './strategyValidation';

const STRATEGY_HELP: Record<StrategyType, { helper: string; button: string }> = {
  'Fixed Price': {
    helper: 'Sell at your selected price.',
    button: 'Schedule Sell Order',
  },
  'Fixed Price Buy': {
    helper: 'Buy at your selected price.',
    button: 'Schedule Buy Order',
  },
  'Buy Below Price': {
    helper: 'Buy when price falls to or below your trigger.',
    button: 'Schedule Buy Below',
  },
  'Breakout Buy': {
    helper: 'Buy when price reaches your breakout trigger.',
    button: 'Schedule Breakout Buy',
  },
  'Dip Buy': {
    helper: 'Buy when price dips to your selected trigger.',
    button: 'Schedule Dip Buy',
  },
  'Time-Based Buy': {
    helper: 'Keep the buy strategy active until your selected expiry time.',
    button: 'Schedule Time-Based Buy',
  },
  'Fixed Price Sell': {
    helper: 'Sell at your selected price.',
    button: 'Schedule Sell Order',
  },
  'Fast Stop Loss': {
    helper: 'Sell quickly if price falls below your trigger.',
    button: 'Schedule Stop Loss',
  },
  'Stop Limit Sell': {
    helper: 'Protect minimum sell price, but order may not execute.',
    button: 'Schedule Stop Limit',
  },
  'Trailing Stop Loss': {
    helper: 'Track higher price and sell after a pullback.',
    button: 'Schedule Trailing Stop',
  },
  'Smart Profit Booking': {
    helper: 'Wait at least 5 minutes after target, track highest price, sell on confirmed drop.',
    button: 'Schedule Profit Booking',
  },
  'Book Profit + Stop Loss': {
    helper: 'Profit target and stop-loss in one strategy. Only one side executes.',
    button: 'Schedule Strategy Order',
  },
  'Partial Profit Booking': {
    helper: 'Sell in parts and keep remaining quantity running.',
    button: 'Schedule Partial Profit Strategy',
  },
  'Break-Even Protection': {
    helper: 'After profit starts, protect your original capital.',
    button: 'Schedule Break-Even Protection',
  },
  'Time-Based Exit': {
    helper: 'Cancel or exit if strategy does not trigger by selected time.',
    button: 'Schedule Time Exit',
  },
  'Emergency Exit': {
    helper: 'Sell quickly using best buyer price.',
    button: 'Confirm Emergency Exit',
  },
};

export const BUY_STRATEGIES: StrategyType[] = [
  'Fixed Price Buy',
  'Buy Below Price',
  'Breakout Buy',
  'Dip Buy',
  'Time-Based Buy',
];

export const SELL_STRATEGIES: StrategyType[] = [
  'Fixed Price Sell',
  'Fast Stop Loss',
  'Stop Limit Sell',
  'Trailing Stop Loss',
  'Smart Profit Booking',
  'Book Profit + Stop Loss',
  'Partial Profit Booking',
  'Break-Even Protection',
  'Time-Based Exit',
  'Emergency Exit',
];

export const STRATEGIES = [...BUY_STRATEGIES, ...SELL_STRATEGIES];

interface Props {
  currentLtp?: number | null;
  availableQty?: number | null;
  averageBuyPrice?: number | null;
  topBuyPrice?: number | null;
  side?: 'buy' | 'sell';
  initialQty?: string;
  initialPrice?: string;
  isSubmitting?: boolean;
  submitError?: string;
  onSubmit: (payload: StrategyPayload) => Promise<void> | void;
}

const StrategySellForm: React.FC<Props> = ({
  currentLtp,
  availableQty,
  averageBuyPrice,
  topBuyPrice,
  side = 'sell',
  initialQty = '',
  initialPrice = '',
  isSubmitting = false,
  submitError,
  onSubmit,
}) => {
  const strategies = side === 'buy' ? BUY_STRATEGIES : SELL_STRATEGIES;
  const [strategy, setStrategy] = useState<StrategyType>(side === 'buy' ? 'Fixed Price Buy' : 'Fixed Price Sell');
  const [qty, setQty] = useState(initialQty);
  const [price, setPrice] = useState(initialPrice);
  const [stopLossPrice, setStopLossPrice] = useState('');
  const [stopLimitPrice, setStopLimitPrice] = useState('');
  const [bookProfitPrice, setBookProfitPrice] = useState('');
  const [profitTargetPrice, setProfitTargetPrice] = useState('');
  const [trailingDropPercent, setTrailingDropPercent] = useState('0.75');
  const [stableBandPercent, setStableBandPercent] = useState('0.20');
  const [minimumWaitMinutes, setMinimumWaitMinutes] = useState('5');
  const [consecutiveDropChecks, setConsecutiveDropChecks] = useState('2');
  const [activationPrice, setActivationPrice] = useState('');
  const [averagePrice, setAveragePrice] = useState(averageBuyPrice ? String(averageBuyPrice) : '');
  const [maxSlippage, setMaxSlippage] = useState('1');
  const [emergencyExecution, setEmergencyExecution] = useState(false);
  const [emergencyConfirmed, setEmergencyConfirmed] = useState(false);
  const [firstTarget, setFirstTarget] = useState('');
  const [firstPercent, setFirstPercent] = useState('30');
  const [secondTarget, setSecondTarget] = useState('');
  const [secondPercent, setSecondPercent] = useState('30');
  const [expiryTime, setExpiryTime] = useState('');
  const [expiryAction, setExpiryAction] = useState('Cancel strategy');
  const [localError, setLocalError] = useState('');

  const validationError = useMemo(() => {
    return validateStrategyForm({
      strategy,
      side,
      qty,
      price,
      currentLtp,
      availableQty,
      stopLossPrice,
      stopLimitPrice,
      bookProfitPrice,
      profitTargetPrice,
      trailingDropPercent,
      stableBandPercent,
      minimumWaitMinutes,
      averagePrice,
      firstTarget,
      firstPercent,
      secondTarget,
      secondPercent,
      expiryTime,
      emergencyConfirmed,
    });
  }, [
    availableQty,
    averagePrice,
    bookProfitPrice,
    currentLtp,
    emergencyConfirmed,
    expiryTime,
    firstPercent,
    firstTarget,
    minimumWaitMinutes,
    price,
    profitTargetPrice,
    qty,
    secondPercent,
    secondTarget,
    side,
    stableBandPercent,
    stopLimitPrice,
    stopLossPrice,
    strategy,
    trailingDropPercent,
  ]);

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (validationError) {
      setLocalError(validationError);
      return;
    }
    setLocalError('');
    const parsedQty = Number.parseInt(qty, 10);
    const fallbackPrice = toPositiveNumber(price) || topBuyPrice || currentLtp || 0;
    const payload: StrategyPayload = {
      strategy_type: strategy,
      price: fallbackPrice,
      qty: parsedQty,
      status: strategy === 'Fixed Price' || strategy === 'Fixed Price Buy' || strategy === 'Fixed Price Sell' ? 'pending' : 'Waiting',
      max_allowed_slippage_percent: Number(maxSlippage) || 1,
      emergency_execution: emergencyExecution || strategy === 'Emergency Exit',
    };
    if (strategy === 'Fast Stop Loss' || strategy === 'Stop Limit Sell' || strategy === 'Book Profit + Stop Loss') {
      payload.stop_loss_price = Number(stopLossPrice);
    }
    if (strategy === 'Stop Limit Sell') payload.stop_limit_price = Number(stopLimitPrice);
    if (strategy === 'Trailing Stop Loss') {
      payload.trailing_drop_percent = Number(trailingDropPercent);
      if (activationPrice) payload.activation_price = Number(activationPrice);
    }
    if (strategy === 'Smart Profit Booking') payload.profit_target_price = Number(profitTargetPrice);
    if (strategy === 'Book Profit + Stop Loss') payload.book_profit_price = Number(bookProfitPrice);
    if (strategy === 'Smart Profit Booking' || strategy === 'Book Profit + Stop Loss') {
      payload.trailing_drop_percent = Number(trailingDropPercent);
      payload.stable_band_percent = Number(stableBandPercent);
      payload.minimum_wait_minutes = Math.max(5, Number(minimumWaitMinutes) || 5);
      payload.consecutive_drop_checks = Number(consecutiveDropChecks) || 2;
    }
    if (strategy === 'Partial Profit Booking') {
      payload.trailing_drop_percent = Number(trailingDropPercent);
      payload.partial_legs = [
        { id: 'first', targetPrice: Number(firstTarget), sellPercent: Number(firstPercent) },
        { id: 'second', targetPrice: Number(secondTarget), sellPercent: Number(secondPercent) },
      ];
    }
    if (strategy === 'Break-Even Protection') {
      payload.average_buy_price = Number(averagePrice);
      payload.trailing_drop_percent = Number(trailingDropPercent);
    }
    if (strategy === 'Time-Based Exit' || strategy === 'Time-Based Buy') {
      payload.profit_target_price = Number(profitTargetPrice || bookProfitPrice || price || 0);
      payload.stop_loss_price = Number(stopLossPrice || 0);
      payload.expiry_time = new Date(expiryTime).toISOString();
      payload.expiry_action = expiryAction;
    }
    await onSubmit(payload);
  };

  useEffect(() => {
    setLocalError('');
  }, [validationError]);

  return (
    <form className="strategy-sell-form" onSubmit={submit} noValidate>
      <div className="form-group">
        <label htmlFor="strategyType">Strategy</label>
        <select id="strategyType" className="select" value={strategy} onChange={(e) => setStrategy(e.target.value as StrategyType)}>
          {strategies.map((item) => <option key={item} value={item}>{item}</option>)}
        </select>
        <span className="strategy-helper">{STRATEGY_HELP[strategy].helper}</span>
      </div>

      {(localError || submitError) && <p className="strategy-error" role="alert">{localError || submitError}</p>}

      <div className="strategy-grid">
        <div className="form-group">
          <label htmlFor="strategyQty">Quantity</label>
          <input id="strategyQty" className="input" type="number" min="1" max={availableQty || undefined} value={qty} onChange={(e) => setQty(e.target.value)} />
        </div>
        {(strategy === 'Fixed Price' || strategy === 'Fixed Price Buy' || strategy === 'Fixed Price Sell' || strategy === 'Buy Below Price' || strategy === 'Breakout Buy' || strategy === 'Dip Buy') && (
          <div className="form-group">
            <label htmlFor="strategyPrice">{side === 'buy' ? 'Buy trigger price' : 'Sell price'}</label>
            <input id="strategyPrice" className="input" type="number" min="0" step="0.1" value={price} onChange={(e) => setPrice(e.target.value)} />
          </div>
        )}
        {(strategy === 'Fast Stop Loss' || strategy === 'Stop Limit Sell' || strategy === 'Book Profit + Stop Loss' || strategy === 'Time-Based Exit') && (
          <div className="form-group">
            <label htmlFor="stopLossPrice">Stop-loss trigger</label>
            <input id="stopLossPrice" className="input" type="number" min="0" step="0.1" value={stopLossPrice} onChange={(e) => setStopLossPrice(e.target.value)} />
          </div>
        )}
        {strategy === 'Stop Limit Sell' && (
          <div className="form-group">
            <label htmlFor="stopLimitPrice">Minimum sell price</label>
            <input id="stopLimitPrice" className="input" type="number" min="0" step="0.1" value={stopLimitPrice} onChange={(e) => setStopLimitPrice(e.target.value)} />
          </div>
        )}
        {(strategy === 'Smart Profit Booking' || strategy === 'Time-Based Exit') && (
          <div className="form-group">
            <label htmlFor="profitTargetPrice">Profit target</label>
            <input id="profitTargetPrice" className="input" type="number" min="0" step="0.1" value={profitTargetPrice} onChange={(e) => setProfitTargetPrice(e.target.value)} />
          </div>
        )}
        {strategy === 'Book Profit + Stop Loss' && (
          <div className="form-group">
            <label htmlFor="bookProfitPrice">Book profit trigger</label>
            <input id="bookProfitPrice" className="input" type="number" min="0" step="0.1" value={bookProfitPrice} onChange={(e) => setBookProfitPrice(e.target.value)} />
          </div>
        )}
        {(strategy === 'Trailing Stop Loss' || strategy === 'Smart Profit Booking' || strategy === 'Book Profit + Stop Loss' || strategy === 'Partial Profit Booking' || strategy === 'Break-Even Protection') && (
          <div className="form-group">
            <label htmlFor="trailingDropPercent">Trailing drop %</label>
            <input id="trailingDropPercent" className="input" type="number" min="0.1" step="0.05" value={trailingDropPercent} onChange={(e) => setTrailingDropPercent(e.target.value)} />
          </div>
        )}
        {strategy === 'Trailing Stop Loss' && (
          <div className="form-group">
            <label htmlFor="activationPrice">Activation price</label>
            <input id="activationPrice" className="input" type="number" min="0" step="0.1" value={activationPrice} onChange={(e) => setActivationPrice(e.target.value)} placeholder="Optional" />
          </div>
        )}
        {(strategy === 'Smart Profit Booking' || strategy === 'Book Profit + Stop Loss') && (
          <>
            <div className="form-group">
              <label htmlFor="minimumWaitMinutes">Minimum wait minutes</label>
              <input id="minimumWaitMinutes" className="input" type="number" min="5" value={minimumWaitMinutes} onChange={(e) => setMinimumWaitMinutes(e.target.value)} />
            </div>
            <div className="form-group">
              <label htmlFor="stableBandPercent">Stable band %</label>
              <input id="stableBandPercent" className="input" type="number" min="0" step="0.05" value={stableBandPercent} onChange={(e) => setStableBandPercent(e.target.value)} />
            </div>
            <div className="form-group">
              <label htmlFor="consecutiveDropChecks">Drop checks</label>
              <input id="consecutiveDropChecks" className="input" type="number" min="1" value={consecutiveDropChecks} onChange={(e) => setConsecutiveDropChecks(e.target.value)} />
            </div>
          </>
        )}
        {strategy === 'Partial Profit Booking' && (
          <>
            <div className="form-group">
              <label htmlFor="firstTarget">First target</label>
              <input id="firstTarget" className="input" type="number" min="0" step="0.1" value={firstTarget} onChange={(e) => setFirstTarget(e.target.value)} />
            </div>
            <div className="form-group">
              <label htmlFor="firstPercent">First sell %</label>
              <input id="firstPercent" className="input" type="number" min="1" max="100" value={firstPercent} onChange={(e) => setFirstPercent(e.target.value)} />
            </div>
            <div className="form-group">
              <label htmlFor="secondTarget">Second target</label>
              <input id="secondTarget" className="input" type="number" min="0" step="0.1" value={secondTarget} onChange={(e) => setSecondTarget(e.target.value)} />
            </div>
            <div className="form-group">
              <label htmlFor="secondPercent">Second sell %</label>
              <input id="secondPercent" className="input" type="number" min="0" max="100" value={secondPercent} onChange={(e) => setSecondPercent(e.target.value)} />
            </div>
          </>
        )}
        {strategy === 'Break-Even Protection' && (
          <div className="form-group">
            <label htmlFor="averageBuyPrice">Average buy price</label>
            <input id="averageBuyPrice" className="input" type="number" min="0" step="0.1" value={averagePrice} onChange={(e) => setAveragePrice(e.target.value)} />
          </div>
        )}
        {(strategy === 'Time-Based Exit' || strategy === 'Time-Based Buy') && (
          <>
            <div className="form-group">
              <label htmlFor="expiryTime">Expiry date/time</label>
              <input id="expiryTime" className="input" type="datetime-local" value={expiryTime} onChange={(e) => setExpiryTime(e.target.value)} />
            </div>
            <div className="form-group">
              <label htmlFor="expiryAction">Expiry action</label>
              <select id="expiryAction" className="select" value={expiryAction} onChange={(e) => setExpiryAction(e.target.value)}>
                <option>Cancel strategy</option>
                <option>Sell using Top Buy</option>
                <option>Mark expired only</option>
              </select>
            </div>
          </>
        )}
        {(strategy === 'Fast Stop Loss' || strategy === 'Book Profit + Stop Loss' || strategy === 'Emergency Exit') && (
          <div className="form-group">
            <label htmlFor="maxSlippage">Max slippage %</label>
            <input id="maxSlippage" className="input" type="number" min="0" step="0.1" value={maxSlippage} onChange={(e) => setMaxSlippage(e.target.value)} />
          </div>
        )}
      </div>

      {(strategy === 'Fast Stop Loss' || strategy === 'Emergency Exit') && (
        <label className="strategy-checkbox">
          <input type="checkbox" checked={strategy === 'Emergency Exit' ? emergencyConfirmed : emergencyExecution} onChange={(e) => strategy === 'Emergency Exit' ? setEmergencyConfirmed(e.target.checked) : setEmergencyExecution(e.target.checked)} />
          {strategy === 'Emergency Exit' ? 'I confirm emergency exit risk.' : 'Allow emergency execution if slippage is high.'}
        </label>
      )}

      <button type="submit" className="btn btn-primary strategy-submit" disabled={isSubmitting}>
        {isSubmitting ? 'Scheduling...' : STRATEGY_HELP[strategy].button}
      </button>
    </form>
  );
};

export default StrategySellForm;
