import { groupScheduledOrdersByBatch } from './scheduledBatchGroups';

describe('scheduledBatchGroups', () => {
  test('groups orders with the same schedule_batch_id', () => {
    const result = groupScheduledOrdersByBatch([
      {
        order_id: 2,
        strategy_config: {
          schedule_batch_id: 'batch-1',
          schedule_batch_label: 'Buy Blue Chips',
          schedule_batch_symbol_count: 3,
        },
      },
      {
        order_id: 1,
        strategy_config: {
          schedule_batch_id: 'batch-1',
          schedule_batch_label: 'Buy Blue Chips',
          schedule_batch_symbol_count: 3,
        },
      },
      {
        order_id: 9,
        strategy_config: {},
      },
    ]);

    expect(result.batches).toHaveLength(1);
    expect(result.batches[0].batchId).toBe('batch-1');
    expect(result.batches[0].label).toBe('Buy Blue Chips');
    expect(result.batches[0].orders.map((order) => order.order_id)).toEqual([2, 1]);
    expect(result.batches[0].symbolCount).toBe(3);
    expect(result.standalone).toHaveLength(1);
    expect(result.standalone[0].order_id).toBe(9);
  });
});
