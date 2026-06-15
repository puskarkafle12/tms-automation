import {
  calculateBoardLotQuantityFromAmount,
  getBoardLotSize,
  normalizeSellQty,
} from './lotSize';

describe('lot size helpers', () => {
  test('uses face value defaults when metadata has no explicit board lot', () => {
    expect(getBoardLotSize({ faceValue: 100 })).toBe(10);
    expect(getBoardLotSize({ faceValue: 10 })).toBe(100);
    expect(getBoardLotSize({ faceValue: 1000 })).toBe(1);
  });

  test('calculates NPR amount quantity by board lot', () => {
    expect(calculateBoardLotQuantityFromAmount(25000, 421, 10)).toEqual({
      quantity: 50,
      estimatedAmount: 21050,
      unusedAmount: 3950,
    });
  });

  test('suggests safe quantity when sell would leave odd-lot remainder', () => {
    const result = normalizeSellQty(60, 67, 10);
    expect(result.qty).toBe(50);
    expect(result.warning).toContain('Suggested safe quantity: 50');
  });

  test('blocks partial sell when no safe board-lot quantity remains', () => {
    const result = normalizeSellQty(10, 12, 10);
    expect(result.qty).toBe(0);
    expect(result.error).toContain('Use Sell All');
  });

  test('allows sell all even when holding is not board-lot multiple', () => {
    const result = normalizeSellQty(67, 67, 10);
    expect(result.qty).toBe(67);
    expect(result.isSellAll).toBe(true);
    expect(result.warning).toContain('Sell All may include odd-lot quantity');
  });
});
