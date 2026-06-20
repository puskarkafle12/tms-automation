import { fetchJson } from '../utils/api';
import { nepalDateTimeLocalToIso } from '../pages/control_pannel/strategyValidation';

export type ScreenerDropExpirationAction =
  | 'CANCEL'
  | 'BUY_AT_PROTECTED_LTP'
  | 'BUY_AT_TOP_SELL';

export type ScreenerDropMarketClosedPolicy =
  | 'CANCEL_IF_MARKET_CLOSED'
  | 'EXECUTE_AT_NEXT_VALID_MARKET_QUOTE'
  | 'KEEP_PENDING_UNTIL_SECONDARY_EXPIRY';

export interface ScreenerDropPreviewRow {
  symbol: string;
  reference_ltp: number;
  reference_ltp_captured_at?: string;
  drop_percent: number;
  trigger_price: number;
  qty?: number;
  expiry_time?: string;
  expiration_action?: string;
  max_allowed_slippage_percent?: number;
}

export interface ScreenerDropPreviewResponse {
  ready: boolean;
  fixed_symbols: string[];
  rows: ScreenerDropPreviewRow[];
  errors: Array<{ symbol?: string; message: string }>;
  baseline_warning?: string;
  expiration_notice?: string;
}

export interface ScreenerDropCommitResponse {
  ready: boolean;
  scheduled: Array<{
    order_id: number;
    symbol: string;
    reference_ltp?: number;
    trigger_price?: number;
    qty?: number;
    expiry_time?: string;
  }>;
  failed: Array<{ symbol: string; message: string }>;
}

export interface ScreenerDropScheduleInput {
  clientId: string;
  queryText: string;
  symbols: string[];
  dropPercent: number;
  expiryTimeLocal: string;
  expirationAction: ScreenerDropExpirationAction;
  maxSlippagePercent?: number;
  marketClosedPolicy?: ScreenerDropMarketClosedPolicy;
  topSellFallback?: 'CANCEL' | 'FALLBACK_TO_PROTECTED_LTP';
  strategyType?: string;
  defaultQty?: number;
  perSymbolQty?: Record<string, number>;
  oddLotAllowed?: boolean;
  securityDetailsBySymbol?: Record<string, Record<string, unknown>>;
}

const buildExpirationPayload = (input: ScreenerDropScheduleInput) => ({
  expires_at: nepalDateTimeLocalToIso(input.expiryTimeLocal),
  expiration_action: input.expirationAction,
  expiration_max_slippage_pct: input.maxSlippagePercent ?? 1,
  market_closed_policy: input.marketClosedPolicy ?? 'CANCEL_IF_MARKET_CLOSED',
  top_sell_fallback: input.topSellFallback ?? 'CANCEL',
});

const buildRequestBody = (input: ScreenerDropScheduleInput) => ({
  client_id: input.clientId,
  query_text: input.queryText,
  symbols: input.symbols,
  drop_percent: input.dropPercent,
  expiry_time: nepalDateTimeLocalToIso(input.expiryTimeLocal),
  expiry_action: input.expirationAction,
  expiration: buildExpirationPayload(input),
  max_allowed_slippage_percent: input.maxSlippagePercent ?? 1,
  strategy_type: input.strategyType ?? 'Custom Query Buy',
  default_qty: input.defaultQty,
  per_symbol_qty: input.perSymbolQty,
  odd_lot_allowed: input.oddLotAllowed ?? false,
  security_details_by_symbol: input.securityDetailsBySymbol,
});

export async function previewScreenerDropBatch(input: ScreenerDropScheduleInput) {
  return fetchJson<ScreenerDropPreviewResponse>(
    '/api/strategy-plans/screener-drop/preview',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(buildRequestBody(input)),
    },
    120000,
  );
}

export async function commitScreenerDropBatch(input: ScreenerDropScheduleInput) {
  return fetchJson<ScreenerDropCommitResponse>(
    '/api/strategy-plans/screener-drop/commit',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(buildRequestBody(input)),
    },
    120000,
  );
}

export const mapExpiryActionLabel = (label: string): ScreenerDropExpirationAction => {
  const normalized = label.trim().toLowerCase();
  if (normalized.includes('protected')) {
    return 'BUY_AT_PROTECTED_LTP';
  }
  if (normalized.includes('top sell')) {
    return 'BUY_AT_TOP_SELL';
  }
  return 'CANCEL';
};
