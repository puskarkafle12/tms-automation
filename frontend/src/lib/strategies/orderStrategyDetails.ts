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

const displayValue = (value: unknown): string => {
  if (value == null || value === '') return 'Awaiting live data';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'number') {
    return Number.isInteger(value) ? value.toLocaleString('en-NP') : value.toLocaleString('en-NP', { maximumFractionDigits: 2 });
  }
  return String(value);
};

const humanField = (value: unknown): string => String(value || 'Condition')
  .replace(/^technical_/, '')
  .replace(/^fundamental_/, '')
  .replace(/_/g, ' ')
  .replace(/\bmacd\b/gi, 'MACD')
  .replace(/\brsi\b/gi, 'RSI')
  .replace(/\bsma\b/gi, 'SMA')
  .replace(/\bema\b/gi, 'EMA')
  .replace(/\bltp\b/gi, 'LTP')
  .replace(/\bobv\b/gi, 'OBV')
  .replace(/\bvwap\b/gi, 'VWAP')
  .replace(/\b\w/g, (letter) => letter.toUpperCase());

const operatorText = (operator: unknown): string => ({
  eq: 'equals', neq: 'does not equal', gt: 'above', gte: 'at least', lt: 'below', lte: 'at most',
}[String(operator || '').toLowerCase()] || String(operator || 'matches'));

const literalNodeValue = (node: any): unknown => {
  if (node && typeof node === 'object' && node.type === 'literal') return node.value;
  if (node && typeof node === 'object' && node.type === 'field') return humanField(node.name);
  return node;
};

const flattenCompiledConditions = (node: any): Array<{ label: string; required: string }> => {
  if (!node || typeof node !== 'object') return [];
  if (node.type === 'group') {
    return (Array.isArray(node.children) ? node.children : []).flatMap(flattenCompiledConditions);
  }
  if (node.type === 'not') {
    return flattenCompiledConditions(node.child).map((item) => ({ ...item, label: `Not: ${item.label}` }));
  }
  if (node.type === 'comparison') {
    const field = node.left?.type === 'field' ? humanField(node.left.name) : 'Calculated value';
    const required = displayValue(literalNodeValue(node.right));
    return [{ label: `${field} ${operatorText(node.operator)} ${required}`, required }];
  }
  if (node.type === 'function') {
    return [{ label: humanField(node.name), required: 'Function must return true' }];
  }
  return [];
};

const describeExitRule = (action: any): { label: string; detail: string } => {
  const condition = action?.when || {};
  const field = String(condition?.left?.name || 'exit condition');
  const operator = String(condition?.operator || 'eq');
  const threshold = literalNodeValue(condition?.right);
  const mode = String(action?.order_mode || 'all_available').replace(/_/g, ' ');
  if (field === 'profit_percent' && operator === 'lte' && Number(threshold) < 0) {
    return { label: 'Protective stop', detail: `Sell ${mode} when estimated net return reaches ${displayValue(threshold)}% or lower.` };
  }
  if (field === 'profit_percent' && operator === 'gte') {
    return { label: 'Profit target', detail: `Sell ${mode} when estimated net return reaches ${displayValue(threshold)}% or higher.` };
  }
  if (field === 'drawdown_from_peak_percent') {
    return { label: 'Trailing protection', detail: `Sell ${mode} after a ${displayValue(threshold)}% move from the highest price reached.` };
  }
  return {
    label: humanField(field),
    detail: `Sell ${mode} when ${humanField(field)} is ${operatorText(operator)} ${displayValue(threshold)}.`,
  };
};

const deduplicateLogs = (value: unknown): string => {
  const unique: string[] = [];
  String(value || '').split('\n').map((line) => line.trim()).filter(Boolean).forEach((line) => {
    if (unique[unique.length - 1] !== line) unique.push(line);
  });
  return unique.slice(-8).join('\n');
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
  pushDetail(secondary, 'Status Checked', order.status_checked_at, helpers.formatDateTime);
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

  if (order.last_monitor_at) {
    secondary.push({
      label: 'Last Monitor Update',
      value: helpers.formatDateTime(order.last_monitor_at),
    });
  }

  if (order.last_scan_at) {
    secondary.push({
      label: 'Last Live Quote Scan',
      value: helpers.formatDateTime(order.last_scan_at),
    });
  }

  if (order.last_monitor_message) {
    secondary.push({ label: 'Last Monitor Log', value: String(order.last_monitor_message), kind: 'muted' });
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

  const rule = Array.isArray((compiledPlan as any)?.rules) ? (compiledPlan as any).rules[0] : undefined;
  const liveStatus = (config.live_condition_status || {}) as Record<string, any>;
  const previewConditions = Array.isArray((snapshot as any)?.conditions) ? (snapshot as any).conditions : [];
  const liveConditions = Array.isArray(liveStatus.conditions) ? liveStatus.conditions : [];
  const compiledConditions = flattenCompiledConditions(rule?.signal || rule?.when);
  const conditionCount = Math.max(liveConditions.length, previewConditions.length, compiledConditions.length);
  const currentRequired = String(snapshot?.current_required_display || '').split('/').map((item) => item.trim());
    const conditions = Array.from({ length: conditionCount }, (_, index) => {
    const live = liveConditions[index] || {};
    const preview = previewConditions[index] || {};
    const compiled = compiledConditions[index] || {};
    const matched = typeof live.matched === 'boolean' ? live.matched : preview.matched;
    const label = String(
      live.label
      || preview.label
      || compiled.label
      || live.expression
      || `Condition ${index + 1}`,
    );
    const isSlope = /slope/i.test(label) || String(live.expression || '').toUpperCase().startsWith('SLOPE');
    const currentRaw = live.actual_value ?? live.current_display ?? preview.current_display ?? preview.current_value ?? (index === 0 && !isSlope ? currentRequired[0] : undefined);
    const requiredRaw = live.expected_value ?? live.required_display ?? preview.required_display ?? preview.required_value ?? compiled.required ?? (index === 0 && !isSlope ? currentRequired[1] : undefined);
    const current = displayValue(currentRaw);
    const required = displayValue(requiredRaw);
    const status = matched === true ? 'satisfied' : matched === false ? 'waiting' : 'unavailable';
    return {
      label,
      status,
      current: current === '—' && isSlope ? 'n/a' : current,
      required: required === '—' && isSlope ? '0' : required,
      explanation: status === 'satisfied'
        ? 'Current market data satisfies this condition.'
        : status === 'waiting'
          ? (isSlope
            ? (currentRaw == null
              ? 'Waiting for enough history to compute the slope (need multiple observations).'
              : `Waiting for slope > ${required}; current slope is ${current}.`)
            : `Waiting for ${required}; current value is ${current}.`)
          : 'A fresh market scan is required to evaluate this condition.',
    } as const;
  });
  const satisfiedCount = conditions.filter((condition) => condition.status === 'satisfied').length;
  const waitingCount = conditions.filter((condition) => condition.status === 'waiting').length;
  const conditionLogic = String(liveStatus.logic || (snapshot as any)?.condition_logic || rule?.when?.logic || 'AND').toUpperCase() === 'OR' ? 'OR' : 'AND';
  const conditionSummary = conditions.length
    ? waitingCount === 0 && satisfiedCount === conditions.length
      ? `All ${conditions.length} conditions are satisfied. Waiting for the configured trigger transition and market availability.`
      : `${satisfiedCount} of ${conditions.length} conditions satisfied${waitingCount ? ` · ${waitingCount} still waiting` : ' · live values pending'}.`
    : 'No condition breakdown is available for this strategy.';

  const lifecycle = ((compiledPlan as any)?.position_lifecycle || (compiledPlan as any)?.backtest || {}) as Record<string, any>;
  const minDays = Number(config.min_holding_days ?? lifecycle.min_holding_days ?? 5);
  const maxDays = Number(config.max_holding_days ?? lifecycle.max_holding_days ?? 90);
  const role = String(config.lifecycle_role || ((compiledPlan as any)?.lifecycle ? 'buy' : side.toLowerCase()));
  const holdingDays = Number(config.linear_holding_sessions ?? 0);
  const fillConfirmed = Boolean(config.fill_confirmed || config.linked_buy_fill_confirmed);
  const submitted = Boolean(config.submitted_at);
  const holdingVerified = Boolean(config.lifecycle_holding_verified);
  const lifecycleEnabled = Boolean(config.linear_position_cycle || (compiledPlan as any)?.lifecycle || (compiledPlan as any)?.position_lifecycle);
  const workflow = lifecycleEnabled ? [
    {
      label: 'Entry signal',
      detail: conditions.length ? conditionSummary : 'Monitor the configured entry rule.',
      state: (submitted || fillConfirmed) ? 'complete' as const : conditions.length && waitingCount === 0 ? 'active' as const : 'pending' as const,
    },
    {
      label: 'BUY fill confirmation',
      detail: fillConfirmed ? 'TMS reports the BUY as fully traded.' : submitted ? 'BUY submitted; waiting for the complete TMS fill.' : 'Begins only after the entry signal fires.',
      state: fillConfirmed ? 'complete' as const : submitted ? 'active' as const : 'pending' as const,
    },
    {
      label: 'Settlement and minimum hold',
      detail: role === 'sell' && holdingVerified
        ? `Sellable holding verified · ${holdingDays}/${minDays} required trading sessions.`
        : `Wait for sellable DP holdings and at least ${minDays} trading sessions after the filled BUY.`,
      state: holdingVerified && holdingDays >= minDays ? 'complete' as const : fillConfirmed ? 'active' as const : 'pending' as const,
    },
    {
      label: 'Exit monitoring',
      detail: `Monitor stop, target, and strategy exits; force an exit by ${maxDays} trading sessions.`,
      state: Boolean(config.lifecycle_active) ? 'active' as const : 'pending' as const,
    },
  ] : [];

  const exitRules = (Array.isArray((compiledPlan as any)?.position_exit)
    ? (compiledPlan as any).position_exit
    : []).map(describeExitRule);
  if (lifecycleEnabled) {
    exitRules.push({ label: 'Maximum holding exit', detail: `Close the position after ${maxDays} trading sessions if no earlier exit condition matches.` });
  }

  const position = (config.live_position_metrics || {}) as Record<string, any>;
  const positionMetrics: StrategyDetailItem[] = [];
  pushDetail(positionMetrics, 'Bought price', position.entry_price ?? order.average_buy_price, helpers.formatCurrency);
  pushDetail(positionMetrics, 'Current LTP', position.ltp ?? order.current_price ?? order.last_checked_ltp, helpers.formatCurrency);
  pushDetail(positionMetrics, 'Gross price return', position.gross_profit_percent, helpers.formatPercent);
  pushDetail(positionMetrics, 'Estimated buy charges', position.estimated_buy_charges, helpers.formatCurrency);
  pushDetail(positionMetrics, 'Estimated sell commission', position.estimated_sell_broker_commission, helpers.formatCurrency);
  pushDetail(positionMetrics, 'Estimated SEBON fee', position.estimated_sell_sebon_fee, helpers.formatCurrency);
  pushDetail(positionMetrics, 'DP charge', position.estimated_dp_charge, helpers.formatCurrency);
  pushDetail(positionMetrics, 'Estimated CGT', position.estimated_capital_gains_tax, helpers.formatCurrency);
  pushDetail(positionMetrics, 'Estimated net profit', position.estimated_net_profit, helpers.formatCurrency);
  pushDetail(positionMetrics, 'profit_percent used by rules', position.profit_percent, helpers.formatPercent);

  const fixedReferences: StrategyDetailItem[] = [];
  const referenceRows = Array.isArray(config.field_reference_rows) ? config.field_reference_rows : [];
  referenceRows.forEach((reference: any) => {
    const raw = reference.numeric_value ?? reference.text_value ?? reference.boolean_value;
    pushDetail(
      fixedReferences,
      `${humanField(reference.field_key)} · fixed reference`,
      raw,
      reference.numeric_value != null && /price|ltp/.test(String(reference.field_key || '').toLowerCase())
        ? helpers.formatCurrency
        : displayValue,
    );
  });
  if (!fixedReferences.length && order.reference_ltp != null) {
    pushDetail(fixedReferences, 'LTP · fixed reference', order.reference_ltp, helpers.formatCurrency);
  }

  return {
    headline,
    primary,
    secondary,
    conditions,
    conditionLogic,
    conditionSummary,
    workflow,
    exitRules,
    positionMetrics,
    fixedReferences,
    rawQuery: typeof config.query_text === 'string' ? config.query_text.trim() : undefined,
    recentLogs: deduplicateLogs(order.monitor_logs),
  };
}
