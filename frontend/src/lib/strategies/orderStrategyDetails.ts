import { extractSymbolsFromCompiledPlan, formatOrderQuantityDisplay } from './rulePlanHelpers';
import {
  formatScheduledQuantitySummary,
  formatScheduledTriggerPrice,
  readSchedulePreviewSnapshot,
  type ScheduledOrderLike,
  type StrategyDetailItem,
  type StrategyDetailLayout,
} from './scheduledOrderDisplay';
import {
  apiTimestampToUtcMs,
  NEPAL_TIME_ZONE,
  isApiTimestamp,
} from '../../utils/nepalTime';

type DetailHelpers = {
  formatStrategyType: (strategy: unknown, side: unknown) => string;
  getOrderSide: (order: ScheduledOrderLike) => 'BUY' | 'SELL' | 'UNKNOWN';
  formatCurrency: (value: number | string | null | undefined) => string;
  formatDateTime: (value: unknown) => string;
  formatPercent: (value: number | null | undefined) => string;
  formatLiveScanStatus: (order: ScheduledOrderLike) => string;
  formatScanCount: (value: number | null | undefined) => string;
  now?: number | null;
};

const isRealValue = (value: unknown): boolean => {
  if (value == null) return false;
  if (typeof value === 'string') return value.trim() !== '';
  return true;
};

const pushDetail = (
  items: StrategyDetailItem[],
  label: string,
  value: unknown,
  formatter?: (value: any) => string,
  kind: StrategyDetailItem['kind'] = 'text',
) => {
  if (!isRealValue(value)) return;
  const formatted = formatter ? formatter(value) : String(value);
  if (!isRealValue(formatted)) return;
  items.push({ label, value: formatted, kind });
};

const firstDepthPrice = (rows: unknown): number | null => {
  if (!Array.isArray(rows)) return null;
  for (const row of rows) {
    const price = Number((row as Record<string, unknown>)?.price || 0);
    const quantity = Number((row as Record<string, unknown>)?.quantity || 0);
    if (price > 0 && quantity >= 0) return price;
  }
  return null;
};

const numericValue = (value: unknown): number | null => {
  const numberValue = Number(value);
  return Number.isFinite(numberValue) && numberValue > 0 ? numberValue : null;
};

const stockQuoteCheckCount = (order: Record<string, any>): number | null =>
  numericValue(
    order.tms_scan_count ??
    order.scanning_count ??
    order.strategy_config?.tms_scan_count ??
    order.socket_message_count ??
    order.strategy_config?.last_socket_message_count,
  );

const isLiveSocketSnapshot = (order: Record<string, any>): boolean =>
  Boolean(order.socket_quote && ['connected', 'live'].includes(String(order.socket_status || '').toLowerCase()));

const socketStatusValue = (order: Record<string, any>): string =>
  String(order.socket_status || order.strategy_config?.last_socket_status || '').trim().toLowerCase();

const quoteSourceDisplay = (order: Record<string, any>): string => {
  if (isLiveSocketSnapshot(order)) {
    return 'Live socket';
  }
  if (socketStatusValue(order) === 'paused_market_closed') {
    return 'Stock quote polling (market closed)';
  }
  const source = String(order.strategy_config?.last_tms_quote_source || '').trim().toLowerCase();
  if (source === 'fixed') {
    return 'Fixed stock quote polling';
  }
  return 'Stock quote polling';
};

const socketStatusDisplay = (order: Record<string, any>): string => {
  const status = socketStatusValue(order);
  if (!status) {
    return '';
  }
  if (isLiveSocketSnapshot(order)) {
    return status;
  }
  if (status === 'paused_market_closed') {
    return 'paused - market closed';
  }
  if (['failed', 'closed', 'auth_failed'].includes(status)) {
    return `${status} - using stock quote polling`;
  }
  return status;
};

const formatSocketReceivedAt = (value: unknown): string => {
  if (!isRealValue(value)) return '';
  if (isApiTimestamp(value)) {
    const utcMs = apiTimestampToUtcMs(value.utc);
    if (utcMs != null) {
      return new Intl.DateTimeFormat('en-US', {
        timeZone: NEPAL_TIME_ZONE,
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: true,
      }).format(new Date(utcMs));
    }
    return value.display || '';
  }
  if (typeof value === 'string') {
    const utcMs = apiTimestampToUtcMs(value);
    if (utcMs != null) {
      return new Intl.DateTimeFormat('en-US', {
        timeZone: NEPAL_TIME_ZONE,
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: true,
      }).format(new Date(utcMs));
    }
    return value;
  }
  return String(value);
};

export function buildStrategyDetailLayout(
  order: ScheduledOrderLike & Record<string, any>,
  helpers: DetailHelpers,
): StrategyDetailLayout {
  const side = helpers.getOrderSide(order);
  const strategy = helpers.formatStrategyType(order.strategy_type, side);
  const snapshot = readSchedulePreviewSnapshot(order);
  const headline: StrategyDetailItem[] = [
    { label: 'Stock', value: String(order.script_name || '—') },
    { label: 'Status', value: String(order.status || '—') },
    { label: 'Strategy', value: strategy },
  ];

  const primary: StrategyDetailItem[] = [];
  const secondary: StrategyDetailItem[] = [];
  const isFixedPrice = strategy === 'Fixed Price Buy' || strategy === 'Fixed Price Sell';

  const triggerDisplay = formatScheduledTriggerPrice(order);
  if (triggerDisplay !== '—') {
    primary.push({ label: 'Est. Trigger Price', value: triggerDisplay });
  } else {
    const config = (order.strategy_config || {}) as Record<string, unknown>;
    const baseline = config.schedule_baseline as Record<string, unknown> | undefined;
    const fallbackTrigger =
      numericValue(config.trigger_price) ??
      numericValue(baseline?.trigger_price) ??
      (isFixedPrice ? numericValue(order.requested_price ?? order.price) : null);
    if (fallbackTrigger != null) {
      primary.push({ label: 'Est. Trigger Price', value: helpers.formatCurrency(fallbackTrigger) });
    }
  }
  if (snapshot?.trigger_strategy_text) {
    primary.push({ label: 'Strategy Condition', value: snapshot.trigger_strategy_text });
  }
  if (snapshot?.current_required_display) {
    primary.push({ label: 'Current / Required', value: snapshot.current_required_display });
  }

  const quantitySummary = formatScheduledQuantitySummary(order);
  if (quantitySummary) {
    const qtyLines = [quantitySummary];
    if (snapshot?.quantity_description) {
      qtyLines.push(snapshot.quantity_description);
    }
    primary.push({ label: 'Quantity', value: qtyLines.join(' · ') });
  }

  if (snapshot?.confirmation_display) {
    primary.push({ label: 'Confirmation', value: snapshot.confirmation_display });
  }

  const liveLtp = order.current_price ?? order.last_checked_ltp ?? snapshot?.live_ltp_display;
  pushDetail(primary, 'Live LTP', liveLtp, helpers.formatCurrency);

  if (snapshot?.execution_price_description) {
    primary.push({ label: 'Execution Price Rule', value: snapshot.execution_price_description });
  }
  if (snapshot?.reason) {
    primary.push({ label: 'Why Waiting', value: snapshot.reason, kind: 'muted' });
  }

  pushDetail(secondary, 'Side', side);
  pushDetail(secondary, 'Created At', order.created_at, helpers.formatDateTime);
  pushDetail(secondary, 'Max Allowed Slippage', order.max_allowed_slippage_percent, helpers.formatPercent);

  const config = (order.strategy_config || {}) as Record<string, unknown>;
  const compiledPlan = config.compiled_plan as Record<string, unknown> | undefined;
  const isCustomQuery = strategy === 'Custom Query Buy' || strategy === 'Custom Query Sell';

  if (isCustomQuery) {
    const symbols = extractSymbolsFromCompiledPlan(compiledPlan);
    pushDetail(secondary, 'Plan Symbols', symbols.length ? symbols.join(', ') : order.script_name);
    pushDetail(secondary, 'Execution Mode', config.execution_mode || 'live');
    const baseline = config.schedule_baseline as Record<string, unknown> | undefined;
    if (baseline || order.reference_ltp != null) {
      pushDetail(secondary, 'Reference LTP', order.reference_ltp ?? baseline?.reference_ltp, helpers.formatCurrency);
      pushDetail(
        secondary,
        'Reference Captured At',
        order.reference_ltp_captured_at ?? baseline?.reference_ltp_captured_at,
        helpers.formatDateTime,
      );
    }
    if (typeof config.query_text === 'string' && config.query_text.trim()) {
      secondary.push({ label: 'Strategy Query', value: config.query_text.trim(), kind: 'query' });
    }
  } else if (isFixedPrice) {
    pushDetail(primary, strategy.includes('Buy') ? 'Buy Price' : 'Sell Price', order.price, helpers.formatCurrency);
  } else if (strategy === 'Capital Protection Sell') {
    pushDetail(primary, 'Stop Loss Price', order.stop_loss_price, helpers.formatCurrency);
    pushDetail(secondary, 'Scheduled Price', order.requested_price ?? order.price, helpers.formatCurrency);
    pushDetail(secondary, 'Average Buy Price', order.average_buy_price, helpers.formatCurrency);
  }

  pushDetail(secondary, 'Monitor Phase', order.monitor_phase);
  pushDetail(
    secondary,
    'Monitor Running',
    order.monitoring_active === true ? 'Yes' : order.monitoring_active === false ? 'No' : undefined,
  );
  pushDetail(secondary, 'Live Status', helpers.formatLiveScanStatus(order));
  pushDetail(secondary, 'Stock Quote Checks', stockQuoteCheckCount(order), helpers.formatScanCount);
  if (order.requires_nepse_alpha === false) {
    secondary.push({ label: 'Nepse Alpha', value: 'Not used by this strategy', kind: 'muted' });
  } else {
    pushDetail(secondary, 'Nepse Alpha Scans', order.nepse_alpha_scan_count, helpers.formatScanCount);
  }
  pushDetail(
    secondary,
    'Stock Quote Source',
    quoteSourceDisplay(order),
  );
  pushDetail(secondary, 'Stock Quote Socket', socketStatusDisplay(order));
  pushDetail(
    secondary,
    'Last Socket Update',
    order.socket_last_received_at || order.strategy_config?.last_socket_received_at,
    formatSocketReceivedAt,
  );
  pushDetail(secondary, 'Socket Updates', order.socket_message_count || order.strategy_config?.last_socket_message_count, helpers.formatScanCount);
  pushDetail(primary, 'Top Buy', firstDepthPrice(order.socket_top_buy), helpers.formatCurrency);
  pushDetail(primary, 'Top Sell', firstDepthPrice(order.socket_top_sell), helpers.formatCurrency);

  if (order.last_scan_at) {
    secondary.push({
      label: 'Last Scan',
      value: helpers.formatDateTime(order.last_scan_at),
    });
  }

  if (order.last_monitor_message) {
    secondary.push({ label: 'Last Monitor Log', value: String(order.last_monitor_message), kind: 'muted' });
  }

  if (order.monitor_logs) {
    const recentLogs = order.monitor_logs
      .split('\n')
      .map((line: string) => line.trim())
      .filter(Boolean)
      .slice(-8)
      .join('\n');
    if (recentLogs) {
      secondary.push({ label: 'Recent Monitor Logs', value: recentLogs, kind: 'logs' });
    }
  }

  pushDetail(secondary, 'Failed Reason', order.failed_reason);
  pushDetail(secondary, 'Cancelled Reason', order.cancelled_reason);

  if (!primary.length) {
    pushDetail(primary, 'Quantity', formatOrderQuantityDisplay(order as any));
    pushDetail(primary, 'Price', order.price, helpers.formatCurrency);
  }

  if (snapshot?.captured_at) {
    pushDetail(secondary, 'Preview Captured At', snapshot.captured_at, helpers.formatDateTime);
  }

  return { headline, primary, secondary };
}
