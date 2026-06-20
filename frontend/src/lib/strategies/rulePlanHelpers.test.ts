import {
  DEFAULT_RULE_PLANNED_QTY,
  extractPlannedQtyFromCompiledPlan,
  getDisplayQtyForOrder,
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
});
