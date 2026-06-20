import { formatOrderQuantityDisplay } from './rulePlanHelpers';

export interface SchedulePreviewSnapshot {
  estimated_trigger_price?: number | null;
  estimated_trigger_price_display?: string | null;
  is_exact_trigger_price?: boolean;
  trigger_strategy_text?: string | null;
  current_required_display?: string | null;
  quantity_description?: string | null;
  estimated_quantity?: number | null;
  estimated_quantity_display?: string | null;
  confirmation_display?: string | null;
  live_ltp_display?: number | null;
  reference_ltp_display?: number | null;
  execution_price_description?: string | null;
  reason?: string | null;
  captured_at?: string | null;
}

export interface ScheduledOrderLike {
  trigger_price?: number | null;
  strategy_config?: Record<string, unknown> | null;
  current_price?: number | null;
  last_checked_ltp?: number | null;
  qty?: number;
  status?: string;
}

export function readSchedulePreviewSnapshot(
  order: ScheduledOrderLike,
): SchedulePreviewSnapshot | null {
  const config = order.strategy_config || {};
  const snapshot = config.schedule_preview_snapshot;
  if (!snapshot || typeof snapshot !== 'object') {
    return null;
  }
  return snapshot as SchedulePreviewSnapshot;
}

export function formatScheduledTriggerPrice(order: ScheduledOrderLike): string {
  const snapshot = readSchedulePreviewSnapshot(order);
  const price = order.trigger_price ?? snapshot?.estimated_trigger_price;
  if (price == null || Number(price) <= 0) {
    if (snapshot?.estimated_trigger_price_display && snapshot.estimated_trigger_price_display !== '—') {
      return snapshot.estimated_trigger_price_display;
    }
    return '—';
  }
  const formatted = `Rs. ${Number(price).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
  const exact = snapshot?.is_exact_trigger_price;
  if (exact === false || exact == null) {
    return `${formatted} (est.)`;
  }
  return formatted;
}

export function formatScheduledQuantitySummary(order: ScheduledOrderLike): string {
  const snapshot = readSchedulePreviewSnapshot(order);
  if (snapshot?.estimated_quantity_display && snapshot.estimated_quantity_display !== '—') {
    if (snapshot.estimated_quantity_display !== 'Unavailable') {
      return snapshot.estimated_quantity_display.replace(/,/g, '');
    }
  }
  if (snapshot?.estimated_quantity && Number(snapshot.estimated_quantity) > 0) {
    return String(Math.floor(Number(snapshot.estimated_quantity)));
  }
  if (Number(order.qty) > 0) {
    return String(Math.floor(Number(order.qty)));
  }
  return formatOrderQuantityDisplay(order as Parameters<typeof formatOrderQuantityDisplay>[0]);
}

export type StrategyDetailItem = {
  label: string;
  value: string;
  kind?: 'text' | 'query' | 'logs' | 'muted';
};

export type StrategyDetailLayout = {
  headline: StrategyDetailItem[];
  primary: StrategyDetailItem[];
  secondary: StrategyDetailItem[];
};
