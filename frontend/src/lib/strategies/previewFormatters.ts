export interface PreviewWarning {
  code: string;
  message: string;
  severity?: 'warning' | 'error' | 'info';
}

export interface ConditionPreview {
  strategy_text: string;
  matched?: boolean;
  current_display?: string;
  target_display?: string;
  connector?: string;
}

export interface TriggerPreview {
  kind?: string;
  strategy_text: string;
  estimated_price?: number | null;
  estimated_price_display?: string | null;
  estimated_price_available?: boolean;
  is_exact_price?: boolean;
  current_display?: string | null;
  target_display?: string | null;
  conditions?: ConditionPreview[];
  logic?: string | null;
}

export interface QuantityPreview {
  mode: string;
  configured_value?: number | null;
  current_holding?: number | null;
  estimated_quantity?: number | null;
  estimated_quantity_display?: string | null;
  is_final?: boolean;
  description: string;
  note?: string | null;
  warnings?: PreviewWarning[];
}

export interface ConfirmationPreview {
  mode: string;
  matched_scans?: number;
  required_scans?: number;
  display: string;
}

export interface ExecutionPricePreview {
  mode: string;
  description: string;
  estimated_price_display?: string | null;
}

export interface PreviewRow {
  symbol?: string;
  rule?: string;
  matched?: boolean;
  status?: string;
  status_label?: string;
  blocker?: string;
  reference_ltp?: number;
  trigger_ltp?: number;
  preview_ltp?: number;
  message?: string;
  reason?: string;
  strategy?: string;
  trigger?: TriggerPreview;
  quantity?: QuantityPreview;
  confirmation?: ConfirmationPreview;
  execution_price?: ExecutionPricePreview;
  execution_policy?: { display?: string };
  warnings?: PreviewWarning[];
}

const ESTIMATE_SUFFIX_PATTERN = /\s*\(est\.\)\s*$/i;

export function formatEstimatePriceDisplay(
  display: string,
  options?: { isExact?: boolean },
): string {
  const trimmed = String(display || '').trim();
  if (!trimmed || trimmed === '—') {
    return trimmed || '—';
  }
  const hasEstimateSuffix = ESTIMATE_SUFFIX_PATTERN.test(trimmed);
  if (options?.isExact) {
    return hasEstimateSuffix ? trimmed.replace(ESTIMATE_SUFFIX_PATTERN, '') : trimmed;
  }
  if (hasEstimateSuffix) {
    return trimmed;
  }
  return `${trimmed} (est.)`;
}

export function formatNumericEstimatePrice(
  price: number,
  options?: { isExact?: boolean },
): string {
  const formatted = `Rs. ${Number(price).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
  return formatEstimatePriceDisplay(formatted, options);
}

export function formatPriceBoundary(row: PreviewRow): string {
  const trigger = row.trigger;
  if (!trigger) {
    return row.trigger_ltp != null ? `Rs. ${Number(row.trigger_ltp).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—';
  }
  if (trigger.estimated_price_display && trigger.estimated_price_display !== '—') {
    return formatEstimatePriceDisplay(trigger.estimated_price_display, {
      isExact: trigger.is_exact_price,
    });
  }
  if (trigger.estimated_price_available === false && trigger.kind === 'derived_price_boundary') {
    return 'Unavailable';
  }
  return '—';
}

export function formatCurrentRequired(row: PreviewRow): string {
  const trigger = row.trigger;
  if (!trigger) {
    return '—';
  }
  if (trigger.conditions && trigger.conditions.length > 1) {
    return trigger.conditions
      .map((item, index) => {
        const prefix = index > 0 && item.connector ? `${item.connector} ` : '';
        const current = item.current_display || '—';
        const target = item.target_display || '—';
        const status = item.matched == null ? '' : item.matched ? ' ✓' : ' ✗';
        return `${prefix}${current} / ${target}${status}`;
      })
      .join('\n');
  }
  if (trigger.current_display && trigger.target_display) {
    return `${trigger.current_display} / ${trigger.target_display}`;
  }
  return '—';
}

export function formatQuantityCell(row: PreviewRow): string {
  const quantity = row.quantity;
  if (!quantity) {
    return '—';
  }
  const lines = [
    quantity.estimated_quantity_display || (quantity.estimated_quantity != null ? String(quantity.estimated_quantity) : '—'),
    quantity.description,
  ];
  if (quantity.note) {
    lines.push(quantity.note);
  }
  if (quantity.current_holding != null && quantity.current_holding > 0) {
    lines.push(`Current holding: ${quantity.current_holding.toLocaleString()}`);
  }
  return lines.filter(Boolean).join('\n');
}

export function formatPreviewWarnings(row: PreviewRow): string[] {
  const warnings = [...(row.warnings || []), ...(row.quantity?.warnings || [])];
  return warnings.map((item) => item.message).filter(Boolean);
}
