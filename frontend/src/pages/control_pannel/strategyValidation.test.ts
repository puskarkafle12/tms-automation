import { StrategyFormValues, StrategyType, validateStrategyForm } from './strategyValidation';

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
