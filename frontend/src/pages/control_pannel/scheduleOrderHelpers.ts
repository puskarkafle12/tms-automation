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

export const parseLastTradedTime = (value: unknown): number[] | undefined => {
  if (Array.isArray(value) && value.length >= 6) {
    return value.map((part) => Number(part));
  }
  if (typeof value === 'string' && value.trim()) {
    const parts = value.match(/\d+/g);
    if (parts && parts.length >= 6) {
      return parts.slice(0, 6).map(Number);
    }
  }
  return undefined;
};

export const mergeQuoteIntoStockDetail = (stock: any, quote: any) => {
  if (!stock || !quote) {
    return stock;
  }

  const ltp = Number(quote.ltp ?? stock.ltp ?? 0);
  const previousClose = Number(quote.closePrice ?? quote.previousClose ?? stock.previousClose ?? 0);
  const change =
    previousClose > 0 && ltp > 0
      ? ltp - previousClose
      : Number(quote.change ?? stock.change ?? 0);
  const percentChange =
    previousClose > 0 && ltp > 0
      ? Number(((change / previousClose) * 100).toFixed(1))
      : Number(quote.percentChange ?? stock.percentChange ?? 0);
  const lastTradedTime = parseLastTradedTime(quote.lastTradedTime) ?? stock.lastTradedTime;

  return {
    ...stock,
    ltp: ltp > 0 ? ltp : stock.ltp,
    open: Number(quote.openPrice ?? stock.open ?? 0) || stock.open,
    high: Number(quote.dayHigh ?? stock.high ?? 0) || stock.high,
    low: Number(quote.dayLow ?? stock.low ?? 0) || stock.low,
    volume: Number(quote.volume ?? stock.volume ?? 0) || stock.volume,
    previousClose: previousClose > 0 ? previousClose : stock.previousClose,
    change: Number.isFinite(change) ? change : stock.change,
    percentChange: Number.isFinite(percentChange) ? percentChange : stock.percentChange,
    lastTradedVolume:
      Number(quote.lastTradedQty ?? quote.lastTradedVolume ?? stock.lastTradedVolume ?? 0) ||
      stock.lastTradedVolume,
    lastTradedTime,
  };
};
