import { buildStrategyDetailLayout } from './orderStrategyDetails';

const helpers = {
  formatStrategyType: (strategy: unknown) => String(strategy || 'Fixed Price Buy'),
  getOrderSide: () => 'BUY' as const,
  formatCurrency: (value: number | string | null | undefined) =>
    value == null ? '—' : `Rs. ${Number(value).toLocaleString('en-NP')}`,
  formatDateTime: (value: unknown) => String(value || '—'),
  formatPercent: (value: number | null | undefined) => (value == null ? '—' : `${value}%`),
  formatLiveScanStatus: () => 'Waiting',
  formatScanCount: (value: number | null | undefined) => String(value ?? 0),
};

describe('orderStrategyDetails', () => {
  test('shows trigger price for fixed price buy orders', () => {
    const layout = buildStrategyDetailLayout(
      {
        script_name: 'CZBIL',
        status: 'pending',
        strategy_type: 'Fixed Price Buy',
        price: 190,
        qty: 10,
        last_checked_ltp: 199,
        trigger_price: null,
      },
      helpers,
    );

    expect(layout.primary).toEqual(
      expect.arrayContaining([
        { label: 'Est. Trigger Price', value: 'Rs. 190.00 (est.)' },
        { label: 'Buy Price', value: 'Rs. 190', kind: 'text' },
      ]),
    );
  });

  test('shows trigger price from stored schedule baseline', () => {
    const layout = buildStrategyDetailLayout(
      {
        script_name: 'CZBIL',
        status: 'pending',
        strategy_type: 'Custom Query Buy',
        price: 190,
        qty: 10,
        strategy_config: {
          schedule_baseline: {
            trigger_price: 187.5,
          },
        },
      },
      helpers,
    );

    expect(layout.primary).toEqual(
      expect.arrayContaining([
        { label: 'Est. Trigger Price', value: 'Rs. 187.50 (est.)' },
      ]),
    );
  });
});
