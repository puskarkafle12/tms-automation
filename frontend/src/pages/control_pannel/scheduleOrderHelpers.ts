import { ScriptOption } from '../../components/ScriptNameAutocomplete';

export const REFRESH_SCHEDULED_ORDERS_KEY = 'tms-refresh-scheduled-orders';
export const SCHEDULED_ORDERS_CHANGED_EVENT = 'tms:scheduled-orders-changed';

export function notifyScheduledOrdersChanged(): void {
  try {
    sessionStorage.setItem(REFRESH_SCHEDULED_ORDERS_KEY, String(Date.now()));
  } catch {
    // Ignore storage errors.
  }
  window.dispatchEvent(new Event(SCHEDULED_ORDERS_CHANGED_EVENT));
}

export function formatApiErrorDetail(detail: unknown, fallback = 'Request failed'): string {
  if (typeof detail === 'string' && detail.trim()) {
    return detail;
  }
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    const record = detail as Record<string, unknown>;
    if (typeof record.message === 'string' && record.message.trim()) {
      return record.message;
    }
    if (typeof record.detail === 'string' && record.detail.trim()) {
      return record.detail;
    }
  }
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (typeof item === 'string') return item;
        if (item && typeof item === 'object' && 'msg' in item) {
          return String((item as { msg?: string }).msg || '');
        }
        return '';
      })
      .filter(Boolean);
    if (messages.length) {
      return messages.join('; ');
    }
  }
  return fallback;
}

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

export type ScheduledBulkDeleteMode = 'selected' | 'all' | 'buy' | 'sell';

export function resolveScheduledOrderIdsForBulkDelete(
  orders: Array<{ order_id: number; order_type?: string; side?: string }>,
  mode: ScheduledBulkDeleteMode,
  selectedIds: Set<number>,
  getSide: (order: { order_type?: string; side?: string }) => string,
): number[] {
  if (mode === 'selected') {
    return orders.filter((order) => selectedIds.has(order.order_id)).map((order) => order.order_id);
  }
  if (mode === 'buy') {
    return orders.filter((order) => getSide(order) === 'BUY').map((order) => order.order_id);
  }
  if (mode === 'sell') {
    return orders.filter((order) => getSide(order) === 'SELL').map((order) => order.order_id);
  }
  return orders.map((order) => order.order_id);
}

export async function deleteScheduledOrdersById(
  apiUrl: string,
  orderIds: number[],
): Promise<{ deletedIds: number[]; failedIds: number[] }> {
  const deletedIds: number[] = [];
  const failedIds: number[] = [];
  await Promise.all(
    orderIds.map(async (orderId) => {
      try {
        const response = await fetch(`${apiUrl}/delete_scheduled_order/?order_id=${orderId}`, {
          method: 'DELETE',
        });
        if (response.ok) {
          deletedIds.push(orderId);
        } else {
          failedIds.push(orderId);
        }
      } catch {
        failedIds.push(orderId);
      }
    }),
  );
  return { deletedIds, failedIds };
}

export async function deleteScheduledBatchById(
  apiUrl: string,
  batchId: string,
): Promise<{ ok: boolean; deletedCount: number; deletedIds: number[]; error?: string }> {
  try {
    const response = await fetch(
      `${apiUrl}/scheduled_orders/batch/${encodeURIComponent(batchId)}`,
      { method: 'DELETE' },
    );
    if (!response.ok) {
      let error = `HTTP ${response.status}`;
      try {
        const body = await response.json() as { detail?: unknown };
        error = formatApiErrorDetail(body.detail, error);
      } catch {
        // keep generic message
      }
      return { ok: false, deletedCount: 0, deletedIds: [], error };
    }
    const body = await response.json() as {
      deleted_count?: number;
      deleted_order_ids?: number[];
    };
    const deletedIds = Array.isArray(body.deleted_order_ids)
      ? body.deleted_order_ids.filter((value): value is number => Number.isFinite(value))
      : [];
    return {
      ok: true,
      deletedCount: Number(body.deleted_count) || deletedIds.length,
      deletedIds,
    };
  } catch (err) {
    return {
      ok: false,
      deletedCount: 0,
      deletedIds: [],
      error: err instanceof Error ? err.message : 'Network error',
    };
  }
}
