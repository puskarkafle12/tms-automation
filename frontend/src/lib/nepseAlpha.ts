export const NEPSE_ALPHA_CHART_URL = 'https://nepsealpha.com/trading/chart';

export const normalizeNepseAlphaSymbol = (symbol: string) => symbol.trim().toUpperCase();

export const buildNepseAlphaChartUrl = (symbol: string): string | undefined => {
  const normalized = normalizeNepseAlphaSymbol(symbol);
  if (!normalized) {
    return undefined;
  }
  return `${NEPSE_ALPHA_CHART_URL}?symbol=${encodeURIComponent(normalized)}`;
};
