import { normalizeSellQty } from './lotSize';
import { currentNepalDateTimeLocal } from '../../utils/nepalTime';

export type StrategyType =
  | 'Fixed Price'
  | 'Fixed Price Buy'
  | 'Buy Below Price'
  | 'Breakout Buy'
  | 'Dip Buy'
  | 'Time-Based Buy'
  | 'Fixed Price Sell'
  | 'Fast Stop Loss'
  | 'Stop Limit Sell'
  | 'Trailing Stop Loss'
  | 'Smart Profit Booking'
  | 'Book Profit + Stop Loss'
  | 'Partial Profit Booking'
  | 'Break-Even Protection'
  | 'Time-Based Exit'
  | 'Emergency Exit';

export interface StrategyPayload {
  strategy_type: StrategyType;
  price: number;
  qty: number;
  status: string;
  stop_loss_price?: number;
  stop_limit_price?: number;
  book_profit_price?: number;
  profit_target_price?: number;
  trailing_drop_percent?: number;
  stable_band_percent?: number;
  minimum_wait_minutes?: number;
  consecutive_drop_checks?: number;
  activation_price?: number;
  average_buy_price?: number;
  protected_price?: number;
  partial_legs?: Array<{ id: string; targetPrice: number; sellPercent: number }>;
  expiry_time?: string;
  expiry_action?: string;
  max_allowed_slippage_percent?: number;
  emergency_execution?: boolean;
  odd_lot_allowed?: boolean;
}

export interface StrategyFormValues {
  strategy: StrategyType;
  side: 'buy' | 'sell';
  qty: string;
  price: string;
  currentLtp?: number | null;
  availableQty?: number | null;
  stopLossPrice: string;
  stopLimitPrice: string;
  bookProfitPrice: string;
  profitTargetPrice: string;
  trailingDropPercent: string;
  stableBandPercent: string;
  minimumWaitMinutes: string;
  averagePrice: string;
  firstTarget: string;
  firstPercent: string;
  secondTarget: string;
  secondPercent: string;
  expiryTime: string;
  emergencyConfirmed: boolean;
  boardLotSize?: number;
  oddLotAllowed?: boolean;
  investmentAmount?: string;
}

export const toPositiveNumber = (value: string) => {
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
};

const NEPAL_OFFSET_MINUTES = 5 * 60 + 45;

export const parseNepalDateTimeLocalToUtcMs = (value: string) => {
  const trimmed = value.trim();
  if (!trimmed) {
    return Number.NaN;
  }

  const localMatch = trimmed.match(
    /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/,
  );
  if (!localMatch) {
    return new Date(trimmed).getTime();
  }

  const [, year, month, day, hour, minute, second = '0'] = localMatch;
  return Date.UTC(
    Number(year),
    Number(month) - 1,
    Number(day),
    Number(hour),
    Number(minute) - NEPAL_OFFSET_MINUTES,
    Number(second),
  );
};

export const nepalDateTimeLocalToIso = (value: string) => {
  const timestamp = parseNepalDateTimeLocalToUtcMs(value);
  return Number.isFinite(timestamp) ? new Date(timestamp).toISOString() : '';
};

export const validateStrategyForm = (values: StrategyFormValues): string => {
  const parsedQty = Number.parseInt(values.qty, 10);
  const ltp = Number(values.currentLtp || 0);
  const lotSize = Math.max(1, Number(values.boardLotSize || 10));

  if (!parsedQty || parsedQty <= 0) {
    if (values.side === 'buy' && values.investmentAmount) {
      return `Amount is not enough to buy minimum board lot of ${lotSize} kitta.`;
    }
    return 'Quantity must be greater than zero.';
  }
  if (values.availableQty && parsedQty > values.availableQty) {
    return `Quantity cannot exceed available holding (${values.availableQty}).`;
  }
  if (!values.oddLotAllowed && values.side === 'buy' && parsedQty % lotSize !== 0) {
    return `Quantity must be a board-lot multiple of ${lotSize} kitta.`;
  }
  if (!values.oddLotAllowed && values.side === 'buy' && parsedQty < lotSize) {
    return `Amount is not enough to buy minimum board lot of ${lotSize} kitta.`;
  }
  if (!values.oddLotAllowed && values.side === 'sell' && values.availableQty) {
    const normalized = normalizeSellQty(parsedQty, values.availableQty, lotSize);
    if (!normalized.isSellAll && normalized.error) {
      return normalized.error;
    }
    if (!normalized.isSellAll && normalized.qty !== parsedQty) {
      return normalized.warning || `Use suggested board-lot quantity ${normalized.qty}.`;
    }
  }
  if (
    (values.strategy === 'Fixed Price' ||
      values.strategy === 'Fixed Price Buy' ||
      values.strategy === 'Fixed Price Sell') &&
    !toPositiveNumber(values.price)
  ) {
    return values.side === 'buy' ? 'Buy price is required.' : 'Sell price is required.';
  }
  if (
    (values.strategy === 'Buy Below Price' ||
      values.strategy === 'Dip Buy' ||
      values.strategy === 'Breakout Buy') &&
    !toPositiveNumber(values.price)
  ) {
    return 'Trigger price is required.';
  }
  if (values.strategy === 'Fast Stop Loss') {
    const stop = toPositiveNumber(values.stopLossPrice);
    if (!stop) return 'Stop-loss trigger price is required.';
    if (ltp > 0 && stop >= ltp) return 'Stop-loss price must be below current LTP.';
  }
  if (values.strategy === 'Stop Limit Sell') {
    const stop = toPositiveNumber(values.stopLossPrice);
    const limit = toPositiveNumber(values.stopLimitPrice);
    if (!stop || !limit) return 'Stop trigger and limit price are required.';
    if (ltp > 0 && stop >= ltp) return 'Stop trigger must be below current LTP.';
    if (limit > stop) return 'Limit price must be at or below stop trigger.';
  }
  if (values.strategy === 'Trailing Stop Loss' && !toPositiveNumber(values.trailingDropPercent)) {
    return 'Trailing drop percent must be greater than zero.';
  }
  if (values.strategy === 'Smart Profit Booking') {
    const target = toPositiveNumber(values.profitTargetPrice);
    if (!target) return 'Profit target price is required.';
    if (ltp > 0 && target <= ltp) return 'Profit target must be above current LTP.';
    if (Number(values.minimumWaitMinutes) < 5) return 'Minimum wait must be at least 5 minutes.';
  }
  if (values.strategy === 'Book Profit + Stop Loss') {
    const target = toPositiveNumber(values.bookProfitPrice);
    const stop = toPositiveNumber(values.stopLossPrice);
    if (!target || !stop) return 'Book profit and stop-loss prices are required.';
    if (ltp > 0 && target <= ltp) return 'Book profit price must be above current LTP.';
    if (ltp > 0 && stop >= ltp) return 'Stop-loss price must be below current LTP.';
  }
  if (values.strategy === 'Partial Profit Booking') {
    const target1 = toPositiveNumber(values.firstTarget);
    const target2 = toPositiveNumber(values.secondTarget);
    const percent1 = Number(values.firstPercent);
    const percent2 = Number(values.secondPercent);
    if (!target1 || !target2) return 'Both target prices are required.';
    if (ltp > 0 && target1 <= ltp) return 'First target must be above current LTP.';
    if (target2 <= target1) return 'Second target must be above first target.';
    if (percent1 <= 0 || percent2 < 0 || percent1 + percent2 > 100) {
      return 'Sell percentages must be valid and total 100% or less.';
    }
  }
  if (values.strategy === 'Break-Even Protection' && !toPositiveNumber(values.averagePrice)) {
    return 'Average buy price is required.';
  }
  if (values.strategy === 'Time-Based Exit' || values.strategy === 'Time-Based Buy') {
    if (!values.expiryTime) return 'Expiry date/time is required.';
    const selectedNepalTime = parseNepalDateTimeLocalToUtcMs(values.expiryTime);
    const currentNepalTime = parseNepalDateTimeLocalToUtcMs(currentNepalDateTimeLocal());
    if (selectedNepalTime <= currentNepalTime) {
      return 'Expiry time must be in the future.';
    }
  }
  if (values.strategy === 'Emergency Exit' && !values.emergencyConfirmed) {
    return 'Confirm emergency exit risk before submitting.';
  }
  return '';
};
