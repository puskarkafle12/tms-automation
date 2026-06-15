import { ScriptOption } from '../../components/ScriptNameAutocomplete';

export interface HoldingForOptions {
  scrip?: string;
  symbolName?: string;
  currentBalance?: number;
  ltp?: number;
  percentChange?: string;
}

export const buildScheduleScriptOptions = (
  orderType: 'buy' | 'sell',
  stockDetails: any[],
  sellHoldings: HoldingForOptions[],
): ScriptOption[] => {
  if (orderType === 'sell') {
    const bySymbol = new Map<string, ScriptOption>();
    sellHoldings.forEach((holding) => {
      const symbol = (holding.scrip || holding.symbolName || '').trim().toUpperCase();
      if (!symbol || Number(holding.currentBalance || 0) <= 0) {
        return;
      }
      bySymbol.set(symbol, {
        symbol,
        ltp: holding.ltp,
        percentChange: holding.percentChange ? Number(holding.percentChange) : undefined,
      });
    });
    return Array.from(bySymbol.values()).sort((a, b) => a.symbol.localeCompare(b.symbol));
  }

  return stockDetails.map((stock) => ({
    symbol: stock.symbol,
    ltp: stock.ltp,
    percentChange: stock.percentChange,
  }));
};

export const mergeUniqueStockDetails = (existing: any[] = [], incoming: any[] = []) => {
  const bySymbol = new Map<string, any>();
  [...existing, ...incoming].forEach((stock) => {
    const symbol = String(stock?.symbol || stock?.scrip || stock?.symbolName || '').trim().toUpperCase();
    if (!symbol) {
      return;
    }
    bySymbol.set(symbol, {
      ...bySymbol.get(symbol),
      ...stock,
      symbol,
    });
  });
  return Array.from(bySymbol.values()).sort((a, b) => String(a.symbol).localeCompare(String(b.symbol)));
};
