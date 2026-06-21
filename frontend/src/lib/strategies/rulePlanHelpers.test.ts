import {
  buildPreviewKey,
  DEFAULT_RULE_PLANNED_QTY,
  describeSchedulePreviewBlockReason,
  extractPlannedQtyFromCompiledPlan,
  getDisplayQtyForOrder,
  isSchedulePreviewReady,
  planUsesReference,
} from './rulePlanHelpers';

describe('rulePlanHelpers', () => {
  const compiledPlan = {
    rules: [
      {
        symbols: ['CZBIL'],
        order: { mode: 'quantity', value: 100 },
      },
    ],
  };

  test('extractPlannedQtyFromCompiledPlan reads ORDER QUANTITY', () => {
    expect(extractPlannedQtyFromCompiledPlan(compiledPlan, 'CZBIL')).toBe(100);
  });

  test('extractPlannedQtyFromCompiledPlan defaults to 10 when quantity missing', () => {
    expect(
      extractPlannedQtyFromCompiledPlan(
        {
          rules: [{ symbols: ['CZBIL'], order: { mode: 'quantity' } }],
        },
        'CZBIL',
      ),
    ).toBe(DEFAULT_RULE_PLANNED_QTY);
  });

  test('getDisplayQtyForOrder prefers compiled plan qty for custom query orders', () => {
    expect(
      getDisplayQtyForOrder({
        qty: 1,
        script_name: 'CZBIL',
        strategy_type: 'Custom Query Buy',
        strategy_config: { compiled_plan: compiledPlan },
      }),
    ).toBe(100);
  });

  test('getDisplayQtyForOrder uses stored rule_planned_qty when present', () => {
    expect(
      getDisplayQtyForOrder({
        qty: 1,
        script_name: 'CZBIL',
        strategy_type: 'Custom Query Buy',
        strategy_config: { rule_planned_qty: 75 },
      }),
    ).toBe(75);
  });

  test('planUsesReference detects REFERENCE in query text', () => {
    expect(
      planUsesReference(undefined, 'WHEN ltp <= REFERENCE(field=ltp) * 0.90'),
    ).toBe(true);
  });

  test('planUsesReference returns false for literal triggers', () => {
    expect(planUsesReference(undefined, 'WHEN ltp <= 450')).toBe(false);
  });

  test('isSchedulePreviewReady accepts OR trigger display from preview rows', () => {
    const compiledPlan = {
      rules: [{ symbols: ['HIDCL'] }],
    };
    const validation = {
      valid: true,
      preview: [
        {
          symbol: 'HIDCL',
          trigger: {
            estimated_price: 233.7,
            estimated_price_display: 'Rs. 270.60 / Rs. 233.70',
          },
        },
      ],
    };
    expect(isSchedulePreviewReady(validation, compiledPlan)).toBe(true);
  });

  test('isSchedulePreviewReady accepts eligibility trigger from preview rows', () => {
    const compiledPlan = {
      rules: [{ symbols: ['NABIL', 'EBL', 'SCB'] }],
    };
    const validation = {
      valid: true,
      preview: [
        {
          symbol: 'NABIL',
          trigger: { estimated_price: 495, estimated_price_display: 'Rs. 495.00' },
        },
        {
          symbol: 'EBL',
          trigger: { estimated_price_display: 'Rs. 480.00 (est.)' },
        },
        {
          symbol: 'SCB',
          trigger: { estimated_price: null, estimated_price_display: 'Unavailable' },
        },
      ],
      schedule_preview_snapshots_by_symbol: {
        NABIL: { estimated_trigger_price: null, estimated_trigger_price_display: 'Unavailable' },
        EBL: { estimated_trigger_price: 480, estimated_trigger_price_display: 'Rs. 480.00 (est.)' },
      },
    };

    expect(isSchedulePreviewReady(validation, compiledPlan)).toBe(false);
    expect(describeSchedulePreviewBlockReason(validation, compiledPlan)).toContain('SCB');
  });

  test('isSchedulePreviewReady accepts signal-based preview without trigger price', () => {
    const compiledPlan = {
      rules: [{ symbols: ['CZBIL'] }],
    };
    const validation = {
      valid: true,
      preview: [
        {
          symbol: 'CZBIL',
          status: 'OK',
          trigger: {
            kind: 'non_price_condition',
            strategy_text: 'SMA 20 crossed above',
            estimated_price: null,
            estimated_price_display: null,
          },
        },
      ],
      schedule_preview_snapshots_by_symbol: {
        CZBIL: {
          trigger_kind: 'non_price_condition',
          estimated_trigger_price: null,
          estimated_trigger_price_display: 'SMA 20 crossed above',
        },
      },
    };
    expect(isSchedulePreviewReady(validation, compiledPlan)).toBe(true);
  });

  test('buildPreviewKey only includes side-relevant ancillary fields', () => {
    const buyKey = buildPreviewKey({
      queryText: 'RULE "Test" FOR SYMBOL IN ("NABIL") { WHEN ltp > 0 ORDER QUANTITY 1 }',
      side: 'buy',
      strategyType: 'Custom Query',
      holdingsBySymbol: { NABIL: 100 },
      knownBuySymbols: ['NABIL', 'EBL'],
    });
    const buyKeyNoHoldings = buildPreviewKey({
      queryText: 'RULE "Test" FOR SYMBOL IN ("NABIL") { WHEN ltp > 0 ORDER QUANTITY 1 }',
      side: 'buy',
      strategyType: 'Custom Query',
      knownBuySymbols: ['NABIL', 'EBL'],
    });
    expect(buyKey).toBe(buyKeyNoHoldings);
    expect(buyKey).toContain('knownSymbolsCount');

    const sellKey = buildPreviewKey({
      queryText: 'RULE "Test" FOR SYMBOL IN ("NABIL") { WHEN ltp > 0 ORDER QUANTITY 1 }',
      side: 'sell',
      strategyType: 'Custom Query',
      holdingsBySymbol: { NABIL: 100 },
      knownBuySymbols: ['NABIL', 'EBL'],
    });
    const sellKeyNoSymbols = buildPreviewKey({
      queryText: 'RULE "Test" FOR SYMBOL IN ("NABIL") { WHEN ltp > 0 ORDER QUANTITY 1 }',
      side: 'sell',
      strategyType: 'Custom Query',
      holdingsBySymbol: { NABIL: 100 },
    });
    expect(sellKey).toBe(sellKeyNoSymbols);
    expect(sellKey).toContain('holdingsCount');
  });
});
