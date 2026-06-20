import {
  StrategyFormValues,
  StrategyType,
  nepalDateTimeLocalToIso,
  validateStrategyForm,
} from './strategyValidation';
import { currentNepalDateTimeLocal } from '../../utils/nepalTime';

const futureDate = () => {
  const current = currentNepalDateTimeLocal();
  if (!current) {
    return '2026-06-20T08:30';
  }
  const [date, time] = current.split('T');
  const [hour, minute] = time.split(':').map((part) => Number.parseInt(part, 10));
  return `${date}T${String(hour + 1).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
};

const baseValues = (strategy: StrategyType, side: 'buy' | 'sell' = 'sell'): StrategyFormValues => ({
  strategy,
  side,
  qty: '10',
  price: '100',
  currentLtp: 100,
  availableQty: side === 'sell' ? 100 : null,
  stopLossPrice: '90',
  stopLimitPrice: '88',
  bookProfitPrice: '120',
  profitTargetPrice: '120',
  trailingDropPercent: '3',
  stableBandPercent: '0.20',
  minimumWaitMinutes: '5',
  averagePrice: '80',
  firstTarget: '115',
  firstPercent: '30',
  secondTarget: '125',
  secondPercent: '30',
  expiryTime: futureDate(),
  emergencyConfirmed: true,
});

describe('validateStrategyForm', () => {
  beforeEach(() => {
    jest.useRealTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  const validCases: Array<[StrategyType, 'buy' | 'sell']> = [
    ['Fixed Price Buy', 'buy'],
    ['Quality Pullback Recovery Buy', 'buy'],
    ['Confirmed Breakout Buy', 'buy'],
    ['Smart Pullback Buy', 'buy'],
    ['Mean Reversion Bounce Buy', 'buy'],
    ['Order Book Strength Buy', 'buy'],
    ['Time-Based Buy', 'buy'],
    ['Fixed Price Sell', 'sell'],
    ['Capital Protection Sell', 'sell'],
    ['Profit Ladder Sell', 'sell'],
    ['Trailing Runner Sell', 'sell'],
    ['Technical Weakness Sell', 'sell'],
    ['Time-Based Exit', 'sell'],
    ['Emergency Exit by Top Buyer', 'sell'],
  ];

  test.each(validCases)('%s accepts complete valid fields', (strategy, side) => {
    expect(validateStrategyForm(baseValues(strategy, side))).toBe('');
  });

  test('requires quantity for every strategy', () => {
    expect(validateStrategyForm({ ...baseValues('Fixed Price Sell'), qty: '' })).toBe(
      'Quantity must be greater than zero.',
    );
  });

  test('blocks odd-lot buy quantity by default', () => {
    expect(validateStrategyForm({ ...baseValues('Fixed Price Buy', 'buy'), qty: '5' })).toBe(
      'Quantity must be a board-lot multiple of 10 kitta.',
    );
  });

  test('allows odd-lot buy when Odd Lot Mode is enabled', () => {
    expect(validateStrategyForm({ ...baseValues('Fixed Price Buy', 'buy'), qty: '5', oddLotAllowed: true })).toBe('');
  });

  test('converts time-based expiry from Nepal time to UTC ISO', () => {
    expect(nepalDateTimeLocalToIso('2026-06-15T10:30')).toBe('2026-06-15T04:45:00.000Z');
  });

  test('validates Time-Based Exit against current Nepal time', () => {
    expect(validateStrategyForm({ ...baseValues('Time-Based Exit'), expiryTime: '2026-06-20T07:31' })).toBe('');
    expect(validateStrategyForm({ ...baseValues('Time-Based Exit'), expiryTime: '2026-06-20T07:28' })).toBe(
      'Expiry time must be in the future.',
    );
  });

  test('shows required message for Capital Protection Sell', () => {
    expect(
      validateStrategyForm({
        ...baseValues('Capital Protection Sell'),
        stopLossPrice: '',
        averagePrice: '',
      }),
    ).toBe('Stop-loss trigger or average buy price is required.');
  });

  test('shows required message for Emergency Exit confirmation', () => {
    expect(validateStrategyForm({ ...baseValues('Emergency Exit by Top Buyer'), emergencyConfirmed: false })).toBe(
      'Confirm emergency exit risk before submitting.',
    );
  });

  test('rule-based strategies require query text but not quantity', () => {
    expect(
      validateStrategyForm({
        ...baseValues('Technical Buy', 'buy'),
        qty: '',
        ruleQueryText: '',
      }),
    ).toBe('Rule plan is required.');
    expect(
      validateStrategyForm({
        ...baseValues('Technical Buy', 'buy'),
        qty: '',
        ruleQueryText: 'STRATEGY_VERSION 1\nSIDE BUY',
      }),
    ).toBe('');
    expect(
      validateStrategyForm({
        ...baseValues('Custom Query Sell', 'sell'),
        qty: '0',
        ruleQueryText: 'STRATEGY_VERSION 1\nSIDE SELL',
      }),
    ).toBe('');
  });
});
