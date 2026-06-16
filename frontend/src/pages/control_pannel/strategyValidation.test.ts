import {
  StrategyFormValues,
  StrategyType,
  nepalDateTimeLocalToIso,
  validateStrategyForm,
} from './strategyValidation';

const futureDate = () => new Date(Date.now() + 60 * 60 * 1000).toISOString();

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
  trailingDropPercent: '0.75',
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
    ['Buy Below Price', 'buy'],
    ['Breakout Buy', 'buy'],
    ['Dip Buy', 'buy'],
    ['Time-Based Buy', 'buy'],
    ['Fixed Price Sell', 'sell'],
    ['Fast Stop Loss', 'sell'],
    ['Stop Limit Sell', 'sell'],
    ['Trailing Stop Loss', 'sell'],
    ['Smart Profit Booking', 'sell'],
    ['Book Profit + Stop Loss', 'sell'],
    ['Partial Profit Booking', 'sell'],
    ['Break-Even Protection', 'sell'],
    ['Time-Based Exit', 'sell'],
    ['Emergency Exit', 'sell'],
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

  test('suggests safe sell quantity when sale would leave odd-lot remainder', () => {
    expect(validateStrategyForm({ ...baseValues('Fixed Price Sell'), qty: '60', availableQty: 67 })).toContain(
      'Suggested safe quantity: 50',
    );
  });

  test('blocks partial sell that cannot avoid odd-lot remainder', () => {
    expect(validateStrategyForm({ ...baseValues('Fixed Price Sell'), qty: '10', availableQty: 12 })).toBe(
      'Partial sell would leave odd-lot shares. Use Sell All or adjust quantity.',
    );
  });

  test('allows sell all when holding itself is odd lot', () => {
    expect(validateStrategyForm({ ...baseValues('Fixed Price Sell'), qty: '67', availableQty: 67 })).toBe('');
  });

  test('converts time-based expiry from Nepal time to UTC ISO', () => {
    expect(nepalDateTimeLocalToIso('2026-06-15T10:30')).toBe('2026-06-15T04:45:00.000Z');
  });

  test('validates Time-Based Exit against current Nepal time', () => {
    jest.useFakeTimers().setSystemTime(new Date('2026-06-15T04:45:00.000Z'));

    expect(validateStrategyForm({ ...baseValues('Time-Based Exit'), expiryTime: '2026-06-15T10:31' })).toBe('');
    expect(validateStrategyForm({ ...baseValues('Time-Based Exit'), expiryTime: '2026-06-15T10:29' })).toBe(
      'Expiry time must be in the future.',
    );
  });

  test('shows required message for Book Profit + Stop Loss', () => {
    expect(
      validateStrategyForm({
        ...baseValues('Book Profit + Stop Loss'),
        bookProfitPrice: '',
        stopLossPrice: '',
      }),
    ).toBe('Book profit and stop-loss prices are required.');
  });

  test('shows required message for Stop Limit Sell', () => {
    expect(
      validateStrategyForm({
        ...baseValues('Stop Limit Sell'),
        stopLossPrice: '',
        stopLimitPrice: '',
      }),
    ).toBe('Stop trigger and limit price are required.');
  });

  test('shows required message for Emergency Exit confirmation', () => {
    expect(validateStrategyForm({ ...baseValues('Emergency Exit'), emergencyConfirmed: false })).toBe(
      'Confirm emergency exit risk before submitting.',
    );
  });
});
