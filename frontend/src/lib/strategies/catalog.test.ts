import { BUY_STRATEGIES, SELL_STRATEGIES } from './index';
import { STRATEGY_CATALOG, STRATEGY_CATALOG_BY_NAME } from './catalog';

describe('strategy catalog', () => {
  test('documents every buy and sell strategy with expected behaviour', () => {
    const documented = new Set(STRATEGY_CATALOG.map((item) => item.name));
    [...BUY_STRATEGIES, ...SELL_STRATEGIES].forEach((name) => {
      expect(documented.has(name)).toBe(true);
      const entry = STRATEGY_CATALOG_BY_NAME[name];
      expect(entry.expectedBehavior.length).toBeGreaterThan(0);
      expect(entry.testScenarios.length).toBeGreaterThan(0);
      expect(entry.onExecute.length).toBeGreaterThan(0);
      expect(entry.example.length).toBeGreaterThan(0);
    });
  });
});
