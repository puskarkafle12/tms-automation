import { buildNepseAlphaChartUrl, normalizeNepseAlphaSymbol } from './nepseAlpha';

describe('nepseAlpha helpers', () => {
  test('normalizes symbols', () => {
    expect(normalizeNepseAlphaSymbol(' nabil ')).toBe('NABIL');
  });

  test('builds chart url for symbol', () => {
    expect(buildNepseAlphaChartUrl('nabil')).toBe(
      'https://nepsealpha.com/trading/chart?symbol=NABIL',
    );
  });

  test('returns undefined for empty symbol', () => {
    expect(buildNepseAlphaChartUrl('   ')).toBeUndefined();
  });
});
