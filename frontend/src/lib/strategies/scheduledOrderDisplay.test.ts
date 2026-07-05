import {
  formatScheduledQuantitySummary,
  formatScheduledTriggerPrice,
  readSchedulePreviewSnapshot,
} from './scheduledOrderDisplay';

describe('scheduledOrderDisplay', () => {
  test('reads trigger price from db snapshot without recalculating', () => {
    const order = {
      trigger_price: 392.5,
      strategy_config: {
        schedule_preview_snapshot: {
          estimated_trigger_price: 392.5,
          is_exact_trigger_price: false,
          trigger_strategy_text: '52-week range position ≥ 95.00%',
        },
      },
    };
    expect(formatScheduledTriggerPrice(order)).toContain('392.50');
    expect(formatScheduledTriggerPrice(order)).toBe('Rs. 392.50 (est.)');
    expect(formatScheduledTriggerPrice(order)).not.toMatch(/\(est\.\).*\(est\.\)/);
    expect(readSchedulePreviewSnapshot(order)?.trigger_strategy_text).toContain('52-week range position');
  });

  test('uses stored display text without duplicating estimate suffix', () => {
    const order = {
      trigger_price: null,
      strategy_config: {
        schedule_preview_snapshot: {
          estimated_trigger_price_display: 'Rs. 504.49 (est.)',
          is_exact_trigger_price: false,
        },
      },
    };
    expect(formatScheduledTriggerPrice(order)).toBe('Rs. 504.49 (est.)');
  });

  test('falls back to fixed price order price when no trigger is stored', () => {
    const order = {
      strategy_type: 'Fixed Price Buy',
      trigger_price: null,
      price: 190,
      requested_price: 190,
      strategy_config: {},
    };
    expect(formatScheduledTriggerPrice(order)).toBe('Rs. 190.00 (est.)');
  });

  test('shows quantity summary from stored snapshot', () => {
    const order = {
      qty: 54,
      strategy_config: {
        schedule_preview_snapshot: {
          estimated_quantity: 54,
          estimated_quantity_display: '54',
          quantity_description: 'Sell 100% of current holding',
        },
      },
    };
    expect(formatScheduledQuantitySummary(order)).toBe('54');
  });

  test('falls back to stored order qty when snapshot missing display', () => {
    const order = {
      qty: 553,
      strategy_config: {},
    };
    expect(formatScheduledQuantitySummary(order)).toBe('553');
  });
});
