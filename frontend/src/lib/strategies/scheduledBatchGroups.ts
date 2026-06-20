export interface ScheduledBatchOrderLike {
  order_id: number;
  created_at?: unknown;
  strategy_config?: Record<string, unknown> | null;
}

export interface ScheduledBatchGroup<T extends ScheduledBatchOrderLike = ScheduledBatchOrderLike> {
  batchId: string;
  label: string;
  orders: T[];
  createdAt?: string;
  symbolCount: number;
}

export function readScheduleBatchId(order: { strategy_config?: Record<string, unknown> | null }): string | null {
  const batchId = order.strategy_config?.schedule_batch_id;
  return typeof batchId === 'string' && batchId.trim() ? batchId.trim() : null;
}

export function readScheduleBatchLabel(order: { strategy_config?: Record<string, unknown> | null }): string {
  const label = order.strategy_config?.schedule_batch_label;
  return typeof label === 'string' && label.trim() ? label.trim() : 'Custom Query Batch';
}

export function groupScheduledOrdersByBatch<T extends ScheduledBatchOrderLike>(
  orders: T[],
): { batches: ScheduledBatchGroup<T>[]; standalone: T[] } {
  const byBatch = new Map<string, T[]>();
  const standalone: T[] = [];

  orders.forEach((order) => {
    const batchId = readScheduleBatchId(order);
    if (!batchId) {
      standalone.push(order);
      return;
    }
    const existing = byBatch.get(batchId) || [];
    existing.push(order);
    byBatch.set(batchId, existing);
  });

  const batches = Array.from(byBatch.entries()).map(([batchId, batchOrders]) => {
    const sortedOrders = [...batchOrders].sort((left, right) => right.order_id - left.order_id);
    const createdAt = sortedOrders.reduce((latest, order) => {
      const value = String(order.created_at || '');
      return value > latest ? value : latest;
    }, '');
    const configuredCount = Number(sortedOrders[0]?.strategy_config?.schedule_batch_symbol_count);
    return {
      batchId,
      label: readScheduleBatchLabel(sortedOrders[0]),
      orders: sortedOrders,
      createdAt: createdAt || undefined,
      symbolCount: Number.isFinite(configuredCount) && configuredCount > 0
        ? configuredCount
        : sortedOrders.length,
    };
  });

  batches.sort((left, right) => {
    const leftMaxId = Math.max(...left.orders.map((order) => order.order_id));
    const rightMaxId = Math.max(...right.orders.map((order) => order.order_id));
    return rightMaxId - leftMaxId;
  });

  standalone.sort((left, right) => right.order_id - left.order_id);

  return { batches, standalone };
}
