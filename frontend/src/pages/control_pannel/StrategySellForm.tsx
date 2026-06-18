import React, { useEffect, useMemo, useState } from 'react';
import './StrategySellForm.css';
import {
  BUY_STRATEGIES,
  SELL_STRATEGIES,
} from '../../lib/strategies';
import {
  StrategyFormPrefill,
  StrategyPayload,
  StrategyType,
  nepalDateTimeLocalToIso,
  toPositiveNumber,
  validateStrategyForm,
} from './strategyValidation';
import {
  getBoardLotSize,
  normalizeSellQty,
  ScripLotMetadata,
} from './lotSize';
import { calculateQuantityFromAmount, getOrderEstimate } from '../../utils/orderEstimate';
import { currentNepalDateTimeLocal } from '../../utils/nepalTime';
import StrategyCatalogModal from '../../components/StrategyCatalogModal';
export type { StrategyPayload, StrategyType } from './strategyValidation';

export const STRATEGY_HELP: Record<string, { helper: string; button: string }> = {
  'Fixed Price Buy': { helper: '', button: 'Schedule Buy Order' },
  'Quality Pullback Recovery Buy': { helper: 'Buy quality stocks after pullback recovery with score filter.', button: 'Schedule Quality Recovery Buy' },
  'Confirmed Breakout Buy': { helper: 'Buy when price breaks high with rising scans and volume.', button: 'Schedule Breakout Buy' },
  'Smart Pullback Buy': { helper: 'Buy after a controlled pullback starts recovering.', button: 'Schedule Smart Pullback Buy' },
  'Mean Reversion Bounce Buy': { helper: 'Buy mean-reverting setups after bounce confirmation.', button: 'Schedule Mean Reversion Buy' },
  'Order Book Strength Buy': { helper: 'Buy when top-of-book buy pressure is strong.', button: 'Schedule Order Book Buy' },
  'Time-Based Buy': { helper: 'Wrap a buy strategy with an expiry time.', button: 'Schedule Time-Based Buy' },
  'Fixed Price Sell': { helper: '', button: 'Schedule Sell Order' },
  'Capital Protection Sell': { helper: 'Stop-loss and break-even protection combined.', button: 'Schedule Capital Protection' },
  'Profit Ladder Sell': { helper: 'Sell partial quantity at target levels.', button: 'Schedule Profit Ladder' },
  'Trailing Runner Sell': { helper: 'Trail remaining quantity after profit ladder.', button: 'Schedule Trailing Runner' },
  'Technical Weakness Sell': { helper: 'Exit on technical and live price weakness.', button: 'Schedule Weakness Exit' },
  'Emergency Exit by Top Buyer': { helper: 'Sell quickly using best buyer price.', button: 'Confirm Emergency Exit' },
  'Time-Based Exit': { helper: 'Cancel or exit if strategy does not trigger by selected time.', button: 'Schedule Time Exit' },
};

export { BUY_STRATEGIES, SELL_STRATEGIES };

interface Props {
  scriptName?: string;
  sideControl?: React.ReactNode;
  currentLtp?: number | null;
  availableQty?: number | null;
  averageBuyPrice?: number | null;
  topBuyPrice?: number | null;
  topSellPrice?: number | null;
  side?: 'buy' | 'sell';
  initialQty?: string;
  initialPrice?: string;
  securityDetails?: ScripLotMetadata | null;
  holdingDays?: number;
  isSubmitting?: boolean;
  submitError?: string;
  prefill?: StrategyFormPrefill | null;
  submitButtonLabel?: string;
  onStrategyChange?: (strategy: StrategyType) => void;
  onSubmit: (payload: StrategyPayload) => Promise<void> | void;
}

const StrategySellForm: React.FC<Props> = ({
  scriptName,
  sideControl,
  currentLtp,
  availableQty,
  averageBuyPrice,
  topBuyPrice,
  topSellPrice,
  side = 'sell',
  initialQty = '',
  initialPrice = '',
  securityDetails,
  holdingDays = 400,
  isSubmitting = false,
  submitError,
  prefill = null,
  submitButtonLabel,
  onStrategyChange,
  onSubmit,
}) => {
  const strategies = side === 'buy' ? BUY_STRATEGIES : SELL_STRATEGIES;
  const [strategy, setStrategy] = useState<StrategyType>(side === 'buy' ? 'Fixed Price Buy' : 'Fixed Price Sell');
  const [strategyGuideOpen, setStrategyGuideOpen] = useState(false);
  const [qty, setQty] = useState(initialQty);
  const [price, setPrice] = useState(initialPrice);
  const [quantityMode, setQuantityMode] = useState<'quantity' | 'amount'>('quantity');
  const [investmentAmount, setInvestmentAmount] = useState('');
  const [oddLotAllowed] = useState(false);
  const [stopLossPrice, setStopLossPrice] = useState('');
  const [stopLimitPrice, setStopLimitPrice] = useState('');
  const [bookProfitPrice, setBookProfitPrice] = useState('');
  const [profitTargetPrice, setProfitTargetPrice] = useState('');
  const [trailingDropPercent, setTrailingDropPercent] = useState('3');
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
  const [minBuyScore, setMinBuyScore] = useState('65');
  const [wrappedStrategyType, setWrappedStrategyType] = useState('Quality Pullback Recovery Buy');
  const [requireFreshTrade, setRequireFreshTrade] = useState(false);
  const [requireVolumeIncrease, setRequireVolumeIncrease] = useState(false);
  const [allowMarketDepthFilter, setAllowMarketDepthFilter] = useState(true);
  const [breakEvenTriggerPct, setBreakEvenTriggerPct] = useState('3');
  const [allowSplitEmergencyExit, setAllowSplitEmergencyExit] = useState(false);
  const [localError, setLocalError] = useState('');
  const minNepalExpiryTime = currentNepalDateTimeLocal().slice(0, 16);
  const boardLotSize = useMemo(() => getBoardLotSize(securityDetails), [securityDetails]);

  useEffect(() => {
    if (!prefill) {
      return;
    }
    if (prefill.strategy) {
      setStrategy(prefill.strategy as StrategyType);
    }
    if (prefill.qty != null) setQty(prefill.qty);
    if (prefill.price != null) setPrice(prefill.price);
    if (prefill.stopLossPrice != null) setStopLossPrice(prefill.stopLossPrice);
    if (prefill.stopLimitPrice != null) setStopLimitPrice(prefill.stopLimitPrice);
    if (prefill.bookProfitPrice != null) setBookProfitPrice(prefill.bookProfitPrice);
    if (prefill.profitTargetPrice != null) setProfitTargetPrice(prefill.profitTargetPrice);
    if (prefill.trailingDropPercent != null) setTrailingDropPercent(prefill.trailingDropPercent);
    if (prefill.stableBandPercent != null) setStableBandPercent(prefill.stableBandPercent);
    if (prefill.minimumWaitMinutes != null) setMinimumWaitMinutes(prefill.minimumWaitMinutes);
    if (prefill.consecutiveDropChecks != null) setConsecutiveDropChecks(prefill.consecutiveDropChecks);
    if (prefill.activationPrice != null) setActivationPrice(prefill.activationPrice);
    if (prefill.averagePrice != null) setAveragePrice(prefill.averagePrice);
    if (prefill.maxSlippage != null) setMaxSlippage(prefill.maxSlippage);
    if (prefill.firstTarget != null) setFirstTarget(prefill.firstTarget);
    if (prefill.firstPercent != null) setFirstPercent(prefill.firstPercent);
    if (prefill.secondTarget != null) setSecondTarget(prefill.secondTarget);
    if (prefill.secondPercent != null) setSecondPercent(prefill.secondPercent);
    if (prefill.expiryTime != null) setExpiryTime(prefill.expiryTime);
    if (prefill.expiryAction != null) setExpiryAction(prefill.expiryAction);
    if (prefill.minBuyScore != null) setMinBuyScore(prefill.minBuyScore);
    if (prefill.wrappedStrategyType != null) setWrappedStrategyType(prefill.wrappedStrategyType);
    if (prefill.requireFreshTrade != null) setRequireFreshTrade(prefill.requireFreshTrade);
    if (prefill.requireVolumeIncrease != null) setRequireVolumeIncrease(prefill.requireVolumeIncrease);
    if (prefill.allowMarketDepthFilter != null) setAllowMarketDepthFilter(prefill.allowMarketDepthFilter);
    if (prefill.breakEvenTriggerPct != null) setBreakEvenTriggerPct(prefill.breakEvenTriggerPct);
    if (prefill.allowSplitEmergencyExit != null) setAllowSplitEmergencyExit(prefill.allowSplitEmergencyExit);
    if (prefill.emergencyExecution != null) setEmergencyExecution(prefill.emergencyExecution);
    if (prefill.emergencyConfirmed != null) setEmergencyConfirmed(prefill.emergencyConfirmed);
  }, [prefill]);

  const priceSource = useMemo(() => {
    const userPrice = toPositiveNumber(price);
    if (userPrice) return { price: userPrice, source: 'User price' };
    if (side === 'buy' && topSellPrice) return { price: topSellPrice, source: 'Top Sell' };
    if (side === 'sell' && topBuyPrice) return { price: topBuyPrice, source: 'Top Buy' };
    if (currentLtp) return { price: currentLtp, source: 'LTP fallback' };
    return { price: 0, source: 'Missing price' };
  }, [currentLtp, price, side, topBuyPrice, topSellPrice]);

  const amountPlan = useMemo(() => {
    const lotSizeForAmount = oddLotAllowed ? 1 : boardLotSize;
    const plan = calculateQuantityFromAmount(Number(investmentAmount || 0), priceSource.price, lotSizeForAmount);
    if (side !== 'sell' || !availableQty || plan.quantity <= 0) {
      return plan;
    }
    if (oddLotAllowed) {
      const quantity = Math.min(plan.quantity, availableQty);
      return {
        quantity,
        estimatedAmount: quantity * priceSource.price,
        unusedAmount: Math.max(0, Number(investmentAmount || 0) - quantity * priceSource.price),
      };
    }
    const normalized = normalizeSellQty(plan.quantity, availableQty, boardLotSize);
    const quantity = normalized.qty || 0;
    return {
      quantity,
      estimatedAmount: quantity * priceSource.price,
      unusedAmount: Math.max(0, Number(investmentAmount || 0) - quantity * priceSource.price),
    };
  }, [availableQty, boardLotSize, investmentAmount, oddLotAllowed, priceSource.price, side]);

  const parsedQty = Number.parseInt(qty, 10) || 0;
  const sellPlan = useMemo(() => {
    if (side !== 'sell' || !availableQty || parsedQty <= 0) {
      return null;
    }
    return normalizeSellQty(parsedQty, availableQty, boardLotSize);
  }, [availableQty, boardLotSize, parsedQty, side]);

  const estimatePrice = priceSource.price;
  const orderEstimate = useMemo(
    () => getOrderEstimate({
      side: side === 'buy' ? 'BUY' : 'SELL',
      quantity: parsedQty,
      price: estimatePrice,
      investmentAmount: Number(investmentAmount || 0),
      averageBuyPrice,
      holdingDays,
      lotSize: boardLotSize,
      priceSource: priceSource.source,
    }),
    [
      averageBuyPrice,
      boardLotSize,
      estimatePrice,
      holdingDays,
      investmentAmount,
      parsedQty,
      priceSource.source,
      side,
    ],
  );
  const estimatedAmount = orderEstimate.grossAmount;
  const showSuggestedQty = Boolean(
    side === 'sell'
    && sellPlan?.qty
    && sellPlan.qty !== parsedQty
    && (sellPlan.warning || sellPlan.error),
  );
  const warningText = sellPlan?.error || sellPlan?.warning || '';
  const summaryParts = [
    scriptName?.trim(),
    parsedQty > 0 ? `${parsedQty} kitta` : '',
    strategy,
    side === 'sell' && orderEstimate.netEstimateAvailable
      ? `Net Rs. ${(orderEstimate.netReceivable || 0).toLocaleString('en-NP', { maximumFractionDigits: 2 })}`
      : estimatedAmount > 0
        ? `Est. Rs. ${(side === 'buy' ? orderEstimate.estimatedCost || 0 : estimatedAmount).toLocaleString('en-NP', { maximumFractionDigits: 2 })}`
        : '',
  ].filter(Boolean);

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
      boardLotSize,
      oddLotAllowed,
      investmentAmount,
      minBuyScore,
      wrappedStrategyType,
      requireFreshTrade,
      requireVolumeIncrease,
      allowMarketDepthFilter,
      breakEvenTriggerPct,
      allowSplitEmergencyExit,
    });
  }, [
    availableQty,
    averagePrice,
    boardLotSize,
    bookProfitPrice,
    currentLtp,
    emergencyConfirmed,
    expiryTime,
    firstPercent,
    firstTarget,
    investmentAmount,
    minimumWaitMinutes,
    oddLotAllowed,
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
    minBuyScore,
    wrappedStrategyType,
  ]);

  useEffect(() => {
    if (quantityMode === 'amount') {
      setQty(amountPlan.quantity > 0 ? String(amountPlan.quantity) : '');
    }
  }, [amountPlan.quantity, quantityMode]);

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (validationError) {
      setLocalError(validationError);
      return;
    }
    setLocalError('');
    const parsedQty = Number.parseInt(qty, 10);
    const fallbackPrice = toPositiveNumber(price) || (side === 'buy' ? topSellPrice : topBuyPrice) || currentLtp || 0;
    const payload: StrategyPayload = {
      strategy_type: strategy,
      price: fallbackPrice,
      qty: parsedQty,
      status: strategy === 'Fixed Price Buy' || strategy === 'Fixed Price Sell' ? 'pending' : 'Waiting',
      max_allowed_slippage_percent: Number(maxSlippage) || 1,
      emergency_execution: emergencyExecution || strategy === 'Emergency Exit by Top Buyer',
      odd_lot_allowed: oddLotAllowed,
      strategy_config: {
        min_buy_score: Number(minBuyScore) || 65,
        wrapped_strategy_type: wrappedStrategyType,
        require_fresh_trade: requireFreshTrade,
        require_volume_increase: requireVolumeIncrease,
        allow_market_depth_filter: allowMarketDepthFilter,
        break_even_trigger_pct: Number(breakEvenTriggerPct) || 3,
        trailing_stop_pct: Number(trailingDropPercent) || 3,
        target1_sell_pct: Number(firstPercent) || 30,
        target2_sell_pct: Number(secondPercent) || 30,
        allow_split_emergency_exit: allowSplitEmergencyExit,
      },
    };
    if (strategy === 'Capital Protection Sell' || strategy === 'Time-Based Exit') {
      payload.stop_loss_price = Number(stopLossPrice) || undefined;
      payload.average_buy_price = Number(averagePrice) || averageBuyPrice || undefined;
      payload.trailing_drop_percent = Number(trailingDropPercent) || undefined;
    }
    if (strategy === 'Trailing Runner Sell') {
      payload.trailing_drop_percent = Number(trailingDropPercent);
      if (activationPrice) payload.activation_price = Number(activationPrice);
    }
    if (strategy === 'Profit Ladder Sell') {
      payload.trailing_drop_percent = Number(trailingDropPercent);
      payload.partial_legs = [
        { id: 'first', targetPrice: Number(firstTarget), sellPercent: Number(firstPercent) },
        { id: 'second', targetPrice: Number(secondTarget), sellPercent: Number(secondPercent) },
      ];
    }
    if (strategy === 'Time-Based Exit' || strategy === 'Time-Based Buy') {
      payload.expiry_time = nepalDateTimeLocalToIso(expiryTime);
      payload.expiry_action = expiryAction;
      if (strategy === 'Time-Based Buy') {
        payload.strategy_config = {
          ...payload.strategy_config,
          wrapped_strategy_type: wrappedStrategyType,
        };
      }
    }
    await onSubmit(payload);
  };

  useEffect(() => {
    setLocalError('');
  }, [validationError]);

  const useSuggestedQty = () => {
    if (sellPlan?.qty) {
      setQty(String(sellPlan.qty));
    }
  };

  const useMaxQty = () => {
    if (availableQty && availableQty > 0) {
      setQty(String(availableQty));
    }
  };

  const handleStrategyChange = (nextStrategy: StrategyType) => {
    setStrategy(nextStrategy);
    onStrategyChange?.(nextStrategy);
  };

  return (
    <form className="strategy-sell-form" onSubmit={submit} noValidate>
      <div className="strategy-side-row">
        {sideControl}
        <div className="form-group strategy-field">
          <label htmlFor="strategyType">Strategy</label>
          <div className="strategy-select-wrap">
            <select id="strategyType" className="select" value={strategy} onChange={(e) => handleStrategyChange(e.target.value as StrategyType)}>
              {strategies.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
            <button
              type="button"
              className="strategy-details-icon-btn"
              onClick={() => setStrategyGuideOpen(true)}
              aria-label="Strategy details"
              title="Strategy details"
            >
              <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="1.75" />
                <path d="M12 11v5" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />
                <circle cx="12" cy="8" r="1" fill="currentColor" />
              </svg>
            </button>
          </div>
        </div>
      </div>

      {(localError || submitError) && <p className="strategy-error" role="alert">{localError || submitError}</p>}

      <div className="strategy-grid">
        <div className="form-group strategy-qty-field">
          <div className="strategy-qty-header">
            <label htmlFor={quantityMode === 'amount' ? 'strategyInvestmentAmount' : 'strategyQty'}>
              {quantityMode === 'amount' ? 'Amount' : 'Quantity'}
            </label>
            {(side === 'buy' || side === 'sell') && (
              <div className="strategy-qty-mode" role="radiogroup" aria-label="Quantity or NPR amount">
                <label className={`strategy-qty-mode-option ${quantityMode === 'quantity' ? 'active' : ''}`}>
                  <input
                    type="radio"
                    name="strategyQtyMode"
                    value="quantity"
                    checked={quantityMode === 'quantity'}
                    onChange={() => setQuantityMode('quantity')}
                  />
                  Qty
                </label>
                <label className={`strategy-qty-mode-option ${quantityMode === 'amount' ? 'active' : ''}`}>
                  <input
                    type="radio"
                    name="strategyQtyMode"
                    value="amount"
                    checked={quantityMode === 'amount'}
                    onChange={() => setQuantityMode('amount')}
                  />
                  NPR
                </label>
              </div>
            )}
          </div>
          <div className="strategy-qty-input-row">
            {quantityMode === 'amount' ? (
              <input
                id="strategyInvestmentAmount"
                className="input"
                type="number"
                min="0"
                step="0.01"
                value={investmentAmount}
                onChange={(e) => setInvestmentAmount(e.target.value)}
                placeholder={side === 'buy' ? 'NPR to invest' : 'NPR sell value'}
                aria-label="Amount in NPR"
              />
            ) : (
              <>
                <input
                  id="strategyQty"
                  className="input"
                  type="number"
                  min="1"
                  max={availableQty || undefined}
                  value={qty}
                  onChange={(e) => setQty(e.target.value)}
                  placeholder="Kitta"
                  aria-label="Quantity in kitta"
                />
                {side === 'sell' && availableQty && availableQty > 0 && (
                  <button type="button" className="btn btn-secondary btn-sm strategy-max-btn" onClick={useMaxQty}>
                    Max
                  </button>
                )}
              </>
            )}
          </div>
        </div>
        {(strategy === 'Fixed Price Buy' || strategy === 'Fixed Price Sell' || strategy === 'Smart Pullback Buy' || strategy === 'Confirmed Breakout Buy') && (
          <div className="form-group">
            <label htmlFor="strategyPrice">{side === 'buy' ? 'Buy trigger price' : 'Sell price'}</label>
            <input id="strategyPrice" className="input" type="number" min="0" step="0.1" value={price} onChange={(e) => setPrice(e.target.value)} />
          </div>
        )}
        {(strategy === 'Quality Pullback Recovery Buy' || strategy === 'Mean Reversion Bounce Buy' || strategy === 'Order Book Strength Buy') && (
          <>
            <div className="form-group">
              <label htmlFor="minBuyScore">Min buy score</label>
              <input id="minBuyScore" className="input" type="number" min="0" max="100" value={minBuyScore} onChange={(e) => setMinBuyScore(e.target.value)} />
            </div>
            <label className="strategy-checkbox">
              <input type="checkbox" checked={requireFreshTrade} onChange={(e) => setRequireFreshTrade(e.target.checked)} />
              Require fresh trade data
            </label>
            <label className="strategy-checkbox">
              <input type="checkbox" checked={requireVolumeIncrease} onChange={(e) => setRequireVolumeIncrease(e.target.checked)} />
              Require volume increase
            </label>
            {strategy === 'Order Book Strength Buy' && (
              <label className="strategy-checkbox">
                <input type="checkbox" checked={allowMarketDepthFilter} onChange={(e) => setAllowMarketDepthFilter(e.target.checked)} />
                Allow market depth filter
              </label>
            )}
          </>
        )}
        {(strategy === 'Capital Protection Sell' || strategy === 'Time-Based Exit') && (
          <>
            <div className="form-group">
              <label htmlFor="stopLossPrice">Stop-loss trigger</label>
              <input id="stopLossPrice" className="input" type="number" min="0" step="0.1" value={stopLossPrice} onChange={(e) => setStopLossPrice(e.target.value)} />
            </div>
            <div className="form-group">
              <label htmlFor="averageBuyPrice">Average buy price</label>
              <input id="averageBuyPrice" className="input" type="number" min="0" step="0.1" value={averagePrice} onChange={(e) => setAveragePrice(e.target.value)} />
            </div>
            <div className="form-group">
              <label htmlFor="breakEvenTriggerPct">Break-even trigger %</label>
              <input id="breakEvenTriggerPct" className="input" type="number" min="0" step="0.1" value={breakEvenTriggerPct} onChange={(e) => setBreakEvenTriggerPct(e.target.value)} />
            </div>
          </>
        )}
        {strategy === 'Profit Ladder Sell' && (
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
        {strategy === 'Trailing Runner Sell' && (
          <>
            <div className="form-group">
              <label htmlFor="trailingDropPercent">Trailing stop %</label>
              <input id="trailingDropPercent" className="input" type="number" min="0.1" step="0.05" value={trailingDropPercent} onChange={(e) => setTrailingDropPercent(e.target.value)} />
            </div>
            <div className="form-group">
              <label htmlFor="activationPrice">Activation price</label>
              <input id="activationPrice" className="input" type="number" min="0" step="0.1" value={activationPrice} onChange={(e) => setActivationPrice(e.target.value)} placeholder="Optional" />
            </div>
          </>
        )}
        {strategy === 'Time-Based Buy' && (
          <div className="form-group">
            <label htmlFor="wrappedStrategyType">Wrapped buy strategy</label>
            <select id="wrappedStrategyType" className="select" value={wrappedStrategyType} onChange={(e) => setWrappedStrategyType(e.target.value)}>
              {BUY_STRATEGIES.filter((item) => item !== 'Time-Based Buy').map((item) => (
                <option key={item} value={item}>{item}</option>
              ))}
            </select>
          </div>
        )}
        {(strategy === 'Time-Based Exit' || strategy === 'Time-Based Buy') && (
          <>
            <div className="form-group">
              <label htmlFor="expiryTime">Expiry date/time (Nepal Time)</label>
              <input id="expiryTime" className="input" type="datetime-local" min={minNepalExpiryTime} value={expiryTime} onChange={(e) => setExpiryTime(e.target.value)} />
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
        {(strategy === 'Capital Protection Sell' || strategy === 'Emergency Exit by Top Buyer') && (
          <div className="form-group">
            <label htmlFor="maxSlippage">Max slippage %</label>
            <input id="maxSlippage" className="input" type="number" min="0" step="0.1" value={maxSlippage} onChange={(e) => setMaxSlippage(e.target.value)} />
          </div>
        )}
      </div>

      {summaryParts.length > 0 && (
        <div className="strategy-order-summary">
          <span className={`strategy-summary-side ${side}`}>{side.toUpperCase()}</span>
          <span>{summaryParts.join(' · ')}</span>
        </div>
      )}
      {warningText && <p className="strategy-warning">{warningText}</p>}
      {showSuggestedQty && (
        <button type="button" className="btn btn-secondary btn-sm strategy-suggest-btn" onClick={useSuggestedQty}>
          Use Suggested Quantity
        </button>
      )}

      {(strategy === 'Capital Protection Sell' || strategy === 'Emergency Exit by Top Buyer') && (
        <label className="strategy-checkbox">
          <input type="checkbox" checked={strategy === 'Emergency Exit by Top Buyer' ? emergencyConfirmed : emergencyExecution} onChange={(e) => strategy === 'Emergency Exit by Top Buyer' ? setEmergencyConfirmed(e.target.checked) : setEmergencyExecution(e.target.checked)} />
          {strategy === 'Emergency Exit by Top Buyer' ? 'I confirm emergency exit risk.' : 'Allow emergency execution if slippage is high.'}
        </label>
      )}
      {strategy === 'Emergency Exit by Top Buyer' && (
        <label className="strategy-checkbox">
          <input type="checkbox" checked={allowSplitEmergencyExit} onChange={(e) => setAllowSplitEmergencyExit(e.target.checked)} />
          Allow split emergency exit across buyer levels
        </label>
      )}

      <button type="submit" className="btn btn-primary strategy-submit" disabled={isSubmitting}>
        {isSubmitting ? 'Saving...' : (submitButtonLabel || STRATEGY_HELP[strategy]?.button || 'Schedule Order')}
      </button>

      {strategyGuideOpen && (
        <StrategyCatalogModal
          strategyName={strategy}
          side={side}
          onClose={() => setStrategyGuideOpen(false)}
        />
      )}
    </form>
  );
};

export default StrategySellForm;
