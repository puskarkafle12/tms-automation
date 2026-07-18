import React, { useCallback, useEffect, useMemo, useState } from 'react';
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
import { fetchJson } from '../../utils/api';
import StrategyCatalogModal from '../../components/StrategyCatalogModal';
import CustomQueryEditor from '../../components/CustomQueryEditor';
import TechnicalRuleBuilder from '../../components/TechnicalRuleBuilder';
import ErrorMessage from '../../components/ErrorMessage';
import { extractPlannedQtyFromCompiledPlan, DEFAULT_RULE_PLANNED_QTY, extractPlanSide, customQueryStrategyForSide, isCustomQueryStrategy, findBlockingValidationIssue, isQueryValidationReady, isSchedulePreflightReady, isSchedulePreviewReady, describeSchedulePreviewBlockReason, isSchedulePreflightKeyCurrent, type PlanValidationSnapshot } from '../../lib/strategies/rulePlanHelpers';
export type { StrategyPayload, StrategyType } from './strategyValidation';

export const STRATEGY_HELP: Record<string, { helper: string; button: string }> = {
  'Fixed Price Buy': { helper: '', button: 'Schedule Buy Order' },
  'Quality Pullback Recovery Buy': { helper: 'Buy quality stocks after pullback recovery with score filter.', button: 'Schedule Quality Recovery Buy' },
  'Confirmed Breakout Buy': { helper: 'Buy when price breaks high with rising scans and volume.', button: 'Schedule Breakout Buy' },
  'Smart Pullback Buy': { helper: 'Buy after a controlled pullback starts recovering.', button: 'Schedule Smart Pullback Buy' },
  'Mean Reversion Bounce Buy': { helper: 'Buy mean-reverting setups after bounce confirmation.', button: 'Schedule Mean Reversion Buy' },
  'Order Book Strength Buy': { helper: 'Buy when top-of-book buy pressure is strong.', button: 'Schedule Order Book Buy' },
  'Time-Based Buy': { helper: 'Wrap a buy strategy with an expiry time.', button: 'Schedule Time-Based Buy' },
  'Technical Buy': { helper: 'Build multi-stock technical buy rules with confirmations and execution controls.', button: 'Schedule Technical Buy Order' },
  'Custom Query': { helper: '', button: 'Schedule Custom Query Order' },
  'Custom Query Buy': { helper: 'Write a Strategy Query Language buy plan for one or many stocks.', button: 'Schedule Custom Query Buy Order' },
  'Fixed Price Sell': { helper: '', button: 'Schedule Sell Order' },
  'Capital Protection Sell': { helper: 'Stop-loss and break-even protection combined.', button: 'Schedule Capital Protection' },
  'Profit Ladder Sell': { helper: 'Sell partial quantity at target levels.', button: 'Schedule Profit Ladder' },
  'Trailing Runner Sell': { helper: 'Trail remaining quantity after profit ladder.', button: 'Schedule Trailing Runner' },
  'Technical Weakness Sell': { helper: 'Exit on technical and live price weakness.', button: 'Schedule Weakness Exit' },
  'Emergency Exit by Top Buyer': { helper: 'Sell quickly using best buyer price.', button: 'Confirm Emergency Exit' },
  'Time-Based Exit': { helper: 'Cancel or exit if strategy does not trigger by selected time.', button: 'Schedule Time Exit' },
  'Technical Sell': { helper: 'Build multi-stock technical sell rules with confirmations and execution controls.', button: 'Schedule Technical Sell Order' },
  'Custom Query Sell': { helper: 'Write a Strategy Query Language sell plan for one or many stocks.', button: 'Schedule Custom Query Sell Order' },
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
  submitProgress?: string;
  submitError?: string;
  submitStatus?: 'idle' | 'success' | 'error';
  submitStatusMessage?: string;
  prefill?: StrategyFormPrefill | null;
  submitButtonLabel?: string;
  clientId?: string;
  holdingsBySymbol?: Record<string, number>;
  knownBuySymbols?: string[];
  scriptListLoading?: boolean;
  holdingsLoading?: boolean;
  initialStrategy?: StrategyType;
  strategyTypeLocked?: boolean;
  draftKey?: string;
  aiPortalTargetId?: string;
  onCustomQuerySideChange?: (side: 'buy' | 'sell') => void;
  onCustomQueryTextChange?: (queryText: string) => void;
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
  submitProgress = '',
  submitError,
  submitStatus = 'idle',
  submitStatusMessage = '',
  prefill = null,
  submitButtonLabel,
  clientId,
  holdingsBySymbol,
  knownBuySymbols,
  scriptListLoading = false,
  holdingsLoading = false,
  initialStrategy,
  strategyTypeLocked = false,
  draftKey,
  aiPortalTargetId,
  onCustomQuerySideChange,
  onCustomQueryTextChange,
  onStrategyChange,
  onSubmit,
}) => {
  const strategies = side === 'buy' ? BUY_STRATEGIES : SELL_STRATEGIES;
  const defaultStrategy = initialStrategy || (side === 'buy' ? 'Fixed Price Buy' : 'Fixed Price Sell');
  const [strategy, setStrategy] = useState<StrategyType>(defaultStrategy);
  const isRuleBuilder = strategy === 'Technical Buy' || strategy === 'Technical Sell';
  const isCustomQuery = isCustomQueryStrategy(strategy);
  const isRuleBased = isRuleBuilder || isCustomQuery;
  const [ruleQueryText, setRuleQueryText] = useState(() => {
    if (prefill?.ruleQueryText != null) return prefill.ruleQueryText;
    if (!draftKey) return '';
    try {
      const draft = JSON.parse(localStorage.getItem(`tms-strategy-form-draft-v1:${draftKey}`) || '{}') as { ruleQueryText?: unknown };
      return draft.ruleQueryText == null ? '' : String(draft.ruleQueryText);
    } catch {
      return '';
    }
  });
  const [compiledPlan, setCompiledPlan] = useState<Record<string, unknown> | undefined>(undefined);
  const [planValidationError, setPlanValidationError] = useState('');
  const [queryValidating, setQueryValidating] = useState(false);
  const [queryValidation, setQueryValidation] = useState<PlanValidationSnapshot | null>(null);
  const [schedulePreflight, setSchedulePreflight] = useState<{
    ready?: boolean;
    status?: string;
    message?: string;
    errors?: Array<{ code?: string; message?: string }>;
    warnings?: Array<{ code?: string; message?: string }>;
  } | null>(null);
  const [schedulePreflightKey, setSchedulePreflightKey] = useState('');
  const [readyBannerQueryKey, setReadyBannerQueryKey] = useState('');
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
  const priceTouchedRef = React.useRef(false);
  const [queryPlanSide, setQueryPlanSide] = useState<'buy' | 'sell' | null>(null);

  useEffect(() => {
    if (initialStrategy && initialStrategy !== strategy) {
      setStrategy(initialStrategy);
    }
  }, [initialStrategy, strategy]);

  useEffect(() => {
    if (!draftKey) {
      return;
    }
    try {
      const raw = localStorage.getItem(`tms-strategy-form-draft-v1:${draftKey}`);
      if (!raw) {
        return;
      }
      const draft = JSON.parse(raw) as Partial<{
        strategy: StrategyType;
        ruleQueryText: string;
        qty: string;
        price: string;
        quantityMode: 'quantity' | 'amount';
        investmentAmount: string;
        stopLossPrice: string;
        stopLimitPrice: string;
        bookProfitPrice: string;
        profitTargetPrice: string;
        trailingDropPercent: string;
        stableBandPercent: string;
        minimumWaitMinutes: string;
        consecutiveDropChecks: string;
        activationPrice: string;
        averagePrice: string;
        maxSlippage: string;
        expiryTime: string;
        expiryAction: string;
        minBuyScore: string;
        wrappedStrategyType: string;
      }>;
      if (draft.strategy) setStrategy(draft.strategy);
      if (draft.ruleQueryText != null) setRuleQueryText(String(draft.ruleQueryText));
      if (draft.qty != null) setQty(String(draft.qty));
      if (draft.price != null) setPrice(String(draft.price));
      if (draft.quantityMode === 'quantity' || draft.quantityMode === 'amount') setQuantityMode(draft.quantityMode);
      if (draft.investmentAmount != null) setInvestmentAmount(String(draft.investmentAmount));
      if (draft.stopLossPrice != null) setStopLossPrice(String(draft.stopLossPrice));
      if (draft.stopLimitPrice != null) setStopLimitPrice(String(draft.stopLimitPrice));
      if (draft.bookProfitPrice != null) setBookProfitPrice(String(draft.bookProfitPrice));
      if (draft.profitTargetPrice != null) setProfitTargetPrice(String(draft.profitTargetPrice));
      if (draft.trailingDropPercent != null) setTrailingDropPercent(String(draft.trailingDropPercent));
      if (draft.stableBandPercent != null) setStableBandPercent(String(draft.stableBandPercent));
      if (draft.minimumWaitMinutes != null) setMinimumWaitMinutes(String(draft.minimumWaitMinutes));
      if (draft.consecutiveDropChecks != null) setConsecutiveDropChecks(String(draft.consecutiveDropChecks));
      if (draft.activationPrice != null) setActivationPrice(String(draft.activationPrice));
      if (draft.averagePrice != null) setAveragePrice(String(draft.averagePrice));
      if (draft.maxSlippage != null) setMaxSlippage(String(draft.maxSlippage));
      if (draft.expiryTime != null) setExpiryTime(String(draft.expiryTime));
      if (draft.expiryAction != null) setExpiryAction(String(draft.expiryAction));
      if (draft.minBuyScore != null) setMinBuyScore(String(draft.minBuyScore));
      if (draft.wrappedStrategyType != null) setWrappedStrategyType(String(draft.wrappedStrategyType));
    } catch {
      localStorage.removeItem(`tms-strategy-form-draft-v1:${draftKey}`);
    }
  }, [draftKey]);

  useEffect(() => {
    if (!draftKey) {
      return;
    }
    localStorage.setItem(`tms-strategy-form-draft-v1:${draftKey}`, JSON.stringify({
      strategy,
      ruleQueryText,
      qty,
      price,
      quantityMode,
      investmentAmount,
      stopLossPrice,
      stopLimitPrice,
      bookProfitPrice,
      profitTargetPrice,
      trailingDropPercent,
      stableBandPercent,
      minimumWaitMinutes,
      consecutiveDropChecks,
      activationPrice,
      averagePrice,
      maxSlippage,
      expiryTime,
      expiryAction,
      minBuyScore,
      wrappedStrategyType,
    }));
  }, [
    activationPrice,
    averagePrice,
    bookProfitPrice,
    consecutiveDropChecks,
    draftKey,
    expiryAction,
    expiryTime,
    investmentAmount,
    maxSlippage,
    minBuyScore,
    minimumWaitMinutes,
    price,
    profitTargetPrice,
    qty,
    quantityMode,
    ruleQueryText,
    stableBandPercent,
    stopLimitPrice,
    stopLossPrice,
    strategy,
    trailingDropPercent,
    wrappedStrategyType,
  ]);

  const resolveValidationMessage = useCallback((validation: PlanValidationSnapshot | null) => {
    if (!validation) {
      return '';
    }
    const blocking = findBlockingValidationIssue(validation);
    if (blocking?.message) {
      return blocking.message;
    }
    if (validation.valid === false && validation.errors?.length) {
      return validation.errors[0].message || 'Rule plan is invalid.';
    }
    return '';
  }, []);

  useEffect(() => {
    priceTouchedRef.current = false;
  }, [scriptName]);

  useEffect(() => {
    if (currentLtp && currentLtp > 0 && !priceTouchedRef.current) {
      setPrice(String(Math.round(currentLtp)));
    }
  }, [currentLtp, scriptName]);

  useEffect(() => {
    if (initialPrice && !priceTouchedRef.current) {
      setPrice(initialPrice);
    }
  }, [initialPrice, scriptName]);

  useEffect(() => {
    if (!prefill) {
      return;
    }
    if (prefill.strategy) {
      setStrategy(prefill.strategy);
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
    if (prefill.ruleQueryText != null) setRuleQueryText(String(prefill.ruleQueryText));
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
      ruleQueryText,
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
    ruleQueryText,
    trailingDropPercent,
    minBuyScore,
    wrappedStrategyType,
  ]);

  const customQueryPreflightParams = useMemo(() => ({
    queryText: ruleQueryText,
    side: (queryPlanSide || side) as 'buy' | 'sell',
    strategyType: 'Custom Query',
    clientId,
    formSymbol: scriptName,
  }), [clientId, queryPlanSide, ruleQueryText, scriptName, side]);

  const customQueryScheduleReady = useMemo(() => {
    if (!isCustomQuery || !ruleQueryText.trim() || !compiledPlan || !queryValidation) {
      return false;
    }
    if (!isSchedulePreflightKeyCurrent(schedulePreflightKey, customQueryPreflightParams)) {
      return false;
    }
    return isQueryValidationReady(queryValidation, compiledPlan)
      && isSchedulePreflightReady(schedulePreflight)
      && isSchedulePreviewReady(queryValidation, compiledPlan);
  }, [
    compiledPlan,
    customQueryPreflightParams,
    isCustomQuery,
    queryValidation,
    ruleQueryText,
    schedulePreflight,
    schedulePreflightKey,
  ]);

  const customQueryScheduleBlockReason = useMemo((): string | null => {
    if (!isCustomQuery) {
      return null;
    }
    if (!ruleQueryText.trim()) {
      return 'Enter a strategy query.';
    }
    if (customQueryScheduleReady) {
      return null;
    }
    if (!isSchedulePreflightKeyCurrent(schedulePreflightKey, customQueryPreflightParams)) {
      return 'Wait for strategy validation to finish.';
    }
    if (!queryValidation || !compiledPlan) {
      return 'Wait for strategy validation to finish.';
    }
    if (!isQueryValidationReady(queryValidation, compiledPlan)) {
      const validationMessage = resolveValidationMessage(queryValidation) || planValidationError;
      return validationMessage || 'Strategy query is not ready to schedule.';
    }
    if (!isSchedulePreflightReady(schedulePreflight)) {
      return schedulePreflight?.errors?.[0]?.message
        || schedulePreflight?.message
        || 'Schedule preflight is still running or failed.';
    }
    if (!isSchedulePreviewReady(queryValidation, compiledPlan)) {
      return describeSchedulePreviewBlockReason(queryValidation, compiledPlan)
        || 'Est. trigger prices are still loading. Wait for preview to finish for all symbols.';
    }
    return null;
  }, [
    compiledPlan,
    customQueryPreflightParams,
    customQueryScheduleReady,
    isCustomQuery,
    planValidationError,
    queryValidation,
    resolveValidationMessage,
    ruleQueryText,
    schedulePreflight,
    schedulePreflightKey,
  ]);

  const scheduleBlockReason = useMemo(() => {
    if (!clientId) {
      return 'Select a logged-in client before scheduling.';
    }
    if (queryValidating && !customQueryScheduleReady) {
      return 'Validation in progress…';
    }
    if (validationError) {
      return validationError;
    }
    if (planValidationError) {
      return planValidationError;
    }

    if (isCustomQuery) {
      return customQueryScheduleBlockReason || '';
    }

    if (isRuleBased) {
      if (!compiledPlan) {
        return 'Rule plan must be valid before scheduling.';
      }
      return '';
    }

    if (!scriptName?.trim()) {
      return 'Select a script before scheduling.';
    }
    if (side === 'sell') {
      if (holdingsLoading) {
        return 'Verifying DP holdings…';
      }
      if (!availableQty || availableQty <= 0) {
        return submitError || `${scriptName} is not available in DP holdings.`;
      }
    }
    return '';
  }, [
    availableQty,
    clientId,
    compiledPlan,
    customQueryScheduleBlockReason,
    customQueryScheduleReady,
    holdingsLoading,
    isCustomQuery,
    isRuleBased,
    planValidationError,
    queryValidating,
    scriptName,
    side,
    submitError,
    validationError,
  ]);

  const scheduleButtonReady = !scheduleBlockReason && !isSubmitting;

  useEffect(() => {
    if (!isRuleBased || isCustomQuery || !ruleQueryText.trim()) {
      if (!isCustomQuery) {
        setCompiledPlan(undefined);
        setPlanValidationError('');
      }
      return undefined;
    }
    const timer = window.setTimeout(async () => {
      const result = await fetchJson<{
        valid: boolean;
        compiled_plan?: Record<string, unknown>;
        errors?: Array<{ message?: string }>;
      }>('/api/strategy-plans/validate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query_text: ruleQueryText,
          strategy_type: strategy,
          side,
          form_symbol: scriptName,
          client_id: clientId,
        }),
      });
      if (!result.ok) {
        setPlanValidationError(result.error);
        setCompiledPlan(undefined);
        return;
      }
      if (!result.data.valid) {
        setPlanValidationError(result.data.errors?.[0]?.message || 'Rule plan is invalid.');
        setCompiledPlan(undefined);
        return;
      }
      setPlanValidationError('');
      setCompiledPlan(result.data.compiled_plan);
    }, 400);
    return () => window.clearTimeout(timer);
  }, [clientId, isRuleBased, ruleQueryText, scriptName, side, strategy]);

  useEffect(() => {
    if (quantityMode === 'amount') {
      setQty(amountPlan.quantity > 0 ? String(amountPlan.quantity) : '');
    }
  }, [amountPlan.quantity, quantityMode]);

  const trimmedRuleQueryText = ruleQueryText.trim();

  useEffect(() => {
    if (customQueryScheduleReady && trimmedRuleQueryText) {
      setReadyBannerQueryKey(trimmedRuleQueryText);
    }
  }, [customQueryScheduleReady, trimmedRuleQueryText]);

  useEffect(() => {
    if (!readyBannerQueryKey || !trimmedRuleQueryText) {
      return;
    }
    if (trimmedRuleQueryText !== readyBannerQueryKey) {
      setReadyBannerQueryKey('');
      onCustomQueryTextChange?.(ruleQueryText);
    }
  }, [onCustomQueryTextChange, readyBannerQueryKey, ruleQueryText, trimmedRuleQueryText]);

  const showCustomQueryReadyBanner = isCustomQuery
    && Boolean(readyBannerQueryKey)
    && readyBannerQueryKey === trimmedRuleQueryText;

  const handleCustomPlanChange = useCallback((payload: {
    queryText: string;
    compiledPlan?: Record<string, unknown>;
    validation: { valid?: boolean; errors?: Array<{ code?: string; message?: string }>; warnings?: Array<{ code?: string; message?: string }> } | null;
    schedulePreflight?: {
      ready?: boolean;
      status?: string;
      message?: string;
      errors?: Array<{ code?: string; message?: string }>;
      warnings?: Array<{ code?: string; message?: string }>;
    } | null;
    schedulePreflightKey?: string;
  }) => {
    setRuleQueryText(payload.queryText);
    setLocalError('');
    setCompiledPlan(payload.compiledPlan);
    setQueryValidation(payload.validation);
    setSchedulePreflight(payload.schedulePreflight ?? null);
    setSchedulePreflightKey(payload.schedulePreflightKey || '');
    const detectedSide = extractPlanSide(payload.compiledPlan);
    if (detectedSide) {
      setQueryPlanSide(detectedSide);
      onCustomQuerySideChange?.(detectedSide);
    }
    const preflightError = payload.schedulePreflight?.ready === false
      ? (payload.schedulePreflight.errors?.[0]?.message
        || payload.schedulePreflight.message
        || 'Schedule preflight failed.')
      : '';
    const message = resolveValidationMessage(payload.validation) || preflightError;
    setPlanValidationError(message);
  }, [onCustomQuerySideChange, resolveValidationMessage]);

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (scheduleBlockReason) {
      setLocalError(scheduleBlockReason);
      return;
    }
    let activeCompiledPlan = compiledPlan;
    const resolvedCustomSide = extractPlanSide(activeCompiledPlan) || queryPlanSide || side;
    if (isCustomQuery) {
      if (!customQueryScheduleReady) {
        setLocalError(customQueryScheduleBlockReason || 'Strategy is not ready to schedule yet.');
        return;
      }
      activeCompiledPlan = compiledPlan;
    } else if (isRuleBuilder && !activeCompiledPlan && ruleQueryText.trim()) {
      const result = await fetchJson<{
        valid: boolean;
        compiled_plan?: Record<string, unknown>;
        errors?: Array<{ message?: string }>;
      }>('/api/strategy-plans/validate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query_text: ruleQueryText,
          strategy_type: strategy,
          side,
          form_symbol: scriptName,
          client_id: clientId,
        }),
      });
      if (!result.ok) {
        setLocalError(result.error);
        return;
      }
      if (!result.data.valid || !result.data.compiled_plan) {
        setLocalError(result.data.errors?.[0]?.message || 'Rule plan must be valid before scheduling.');
        return;
      }
      activeCompiledPlan = result.data.compiled_plan;
      setCompiledPlan(activeCompiledPlan);
      setPlanValidationError('');
    }
    if (isRuleBased && !activeCompiledPlan) {
      setLocalError('Rule plan must be valid before scheduling.');
      return;
    }
    setLocalError('');
    const fallbackPrice = isCustomQuery
      ? 0
      : (toPositiveNumber(price) || (side === 'buy' ? topSellPrice : topBuyPrice) || currentLtp || 0);
    if (isRuleBuilder && fallbackPrice <= 0) {
      setLocalError('Reference price is required. It is prefilled from LTP — adjust if needed.');
      return;
    }
    const plannedRuleQty = isRuleBased
      ? (extractPlannedQtyFromCompiledPlan(activeCompiledPlan, scriptName)
        ?? (parsedQty > 0 ? parsedQty : DEFAULT_RULE_PLANNED_QTY))
      : parsedQty;
    const payload: StrategyPayload = {
      strategy_type: isCustomQuery ? customQueryStrategyForSide(extractPlanSide(activeCompiledPlan) || queryPlanSide || side) : strategy,
      price: fallbackPrice,
      qty: plannedRuleQty,
      status: isRuleBased || strategy === 'Fixed Price Buy' || strategy === 'Fixed Price Sell' ? (isRuleBased ? 'Waiting' : 'pending') : 'Waiting',
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
        query_text: isRuleBased ? ruleQueryText : undefined,
        compiled_plan: isRuleBased ? activeCompiledPlan : undefined,
        rule_planned_qty: isRuleBased ? plannedRuleQty : undefined,
        execution_mode: isRuleBased ? 'live' : undefined,
        schedule_preflight_ready: isCustomQuery ? Boolean(schedulePreflight?.ready) : undefined,
        schedule_preflight_key: isCustomQuery ? schedulePreflightKey : undefined,
        schedule_preview_snapshots_by_symbol: isCustomQuery
          ? (queryValidation?.schedule_preview_snapshots_by_symbol || undefined)
          : undefined,
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
    const nextIsCustomQuery = isCustomQueryStrategy(nextStrategy);
    setStrategy(nextIsCustomQuery ? 'Custom Query' : nextStrategy);
    if (nextIsCustomQuery) {
      priceTouchedRef.current = true;
      setPrice('');
      setQueryPlanSide(null);
    } else if (isCustomQuery && currentLtp && currentLtp > 0) {
      priceTouchedRef.current = false;
      setPrice(String(Math.round(currentLtp)));
    }
    onStrategyChange?.(nextStrategy);
  };

  return (
    <form className="strategy-sell-form" onSubmit={submit} noValidate>
      <div className="strategy-side-row">
        {sideControl}
        <div className="form-group strategy-field">
          <label htmlFor="strategyType">Strategy</label>
          <div className="strategy-select-wrap">
            <select
              id="strategyType"
              className="select"
              value={strategy}
              disabled={strategyTypeLocked}
              onChange={(e) => handleStrategyChange(e.target.value as StrategyType)}
            >
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

      {isRuleBuilder && (
        <TechnicalRuleBuilder
          side={side}
          formSymbol={scriptName}
          onQueryChange={setRuleQueryText}
        />
      )}

      {isRuleBuilder && (
        <div className="form-group">
          <label htmlFor="strategyReferencePrice">
            {side === 'buy' ? 'Reference buy price (from LTP)' : 'Reference sell price (from LTP)'}
          </label>
          <input
            id="strategyReferencePrice"
            className="input"
            type="number"
            min="0"
            step="1"
            value={price}
            onChange={(e) => {
              priceTouchedRef.current = true;
              setPrice(e.target.value);
            }}
          />
        </div>
      )}

      {planValidationError ? <p className="strategy-error" role="alert">{planValidationError}</p> : null}

      {isCustomQuery && (
        <>
          {queryPlanSide ? (
            <div className={`strategy-query-side-ok ${queryPlanSide}`} role="status" aria-live="polite">
              <span className="strategy-query-side-ok-check">OK</span>
              <strong>{queryPlanSide.toUpperCase()}</strong>
            </div>
          ) : null}
          <CustomQueryEditor
            side={queryPlanSide || side}
            strategyType="Custom Query"
            formSymbol={scriptName}
            clientId={clientId}
            holdingsBySymbol={holdingsBySymbol}
            initialQuery={ruleQueryText}
            aiPortalTargetId={aiPortalTargetId}
            onPlanChange={handleCustomPlanChange}
            onValidatingChange={setQueryValidating}
          />
        </>
      )}

      <div className="strategy-grid">
        {!isRuleBased && (
        <>
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
            <input
              id="strategyPrice"
              className="input"
              type="number"
              min="0"
              step="1"
              value={price}
              onChange={(e) => {
                priceTouchedRef.current = true;
                setPrice(e.target.value);
              }}
            />
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
        </>
        )}
      </div>

      {isRuleBased && !isCustomQuery && (
        <p className="strategy-warning">
          Order size and stock targets come from the rule plan above. The selected form symbol is only used for warnings when it is not included in the query.
        </p>
      )}

      {summaryParts.length > 0 && !isCustomQuery && (
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

      <button
        type="submit"
        className={`btn btn-primary strategy-submit${scheduleButtonReady ? ' strategy-submit-ready' : ''}`}
        disabled={isSubmitting}
        title={scheduleBlockReason || undefined}
      >
        {isSubmitting
          ? 'Scheduling…'
          : (submitButtonLabel || STRATEGY_HELP[strategy]?.button || 'Schedule Order')}
      </button>

      {isSubmitting && submitProgress ? (
        <p className="strategy-submit-progress" aria-live="polite">{submitProgress}</p>
      ) : null}
      {!isSubmitting && scheduleBlockReason ? (
        <p className="strategy-submit-progress strategy-submit-progress-muted" aria-live="polite">
          {scheduleBlockReason}
        </p>
      ) : null}
      {showCustomQueryReadyBanner ? (
        <p className="strategy-submit-progress strategy-submit-progress-ready" aria-live="polite">
          Ready to schedule this custom query.
        </p>
      ) : null}

      {(submitStatus === 'success' || submitStatus === 'error') && submitStatusMessage ? (
        <div className="strategy-submit-status">
          <ErrorMessage
            message={submitStatusMessage}
            variant={submitStatus === 'success' ? 'success' : 'error'}
            persistent={submitStatus === 'error' || (isCustomQuery && submitStatus === 'success')}
          />
        </div>
      ) : null}

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
