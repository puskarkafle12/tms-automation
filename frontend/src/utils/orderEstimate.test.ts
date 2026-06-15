import {
  brokerCommission,
  calculateNepseProfit,
  calculateQuantityFromAmount,
  getOrderEstimate,
} from './orderEstimate';

describe('orderEstimate', () => {
  test('calculates broker commission tiers with minimum fee', () => {
    expect(brokerCommission(1000)).toBe(10);
    expect(brokerCommission(100000)).toBeCloseTo(330);
    expect(brokerCommission(2500000)).toBeCloseTo(6750);
  });

  test('calculates NEPSE profit using supplied formula', () => {
    const result = calculateNepseProfit(100, 250, 100, 400);

    expect(result.buyAmount).toBe(10000);
    expect(result.sellAmount).toBe(25000);
    expect(result.moneyReceived).toBeCloseTo(24881.25);
    expect(result.grossProfit).toBeCloseTo(14843.75);
    expect(result.tax).toBeCloseTo(742.1875);
    expect(result.finalProfit).toBeCloseTo(14101.5625);
    expect(result.profitPercent).toBe('140.49');
  });

  test('calculates board-lot quantity from amount', () => {
    expect(calculateQuantityFromAmount(25000, 421, 10)).toEqual({
      quantity: 50,
      estimatedAmount: 21050,
      unusedAmount: 3950,
    });
  });

  test('returns sell net receivable when average buy price is available', () => {
    const estimate = getOrderEstimate({
      side: 'SELL',
      quantity: 100,
      price: 250,
      averageBuyPrice: 100,
      holdingDays: 400,
      lotSize: 10,
    });

    expect(estimate.grossAmount).toBe(25000);
    expect(estimate.netEstimateAvailable).toBe(true);
    expect(estimate.netReceivable).toBeCloseTo(24139.0625);
  });

  test('leaves sell net unavailable without average buy price', () => {
    const estimate = getOrderEstimate({
      side: 'SELL',
      quantity: 100,
      price: 250,
      averageBuyPrice: null,
      lotSize: 10,
    });

    expect(estimate.grossAmount).toBe(25000);
    expect(estimate.netEstimateAvailable).toBe(false);
    expect(estimate.netReceivable).toBeUndefined();
  });
});
