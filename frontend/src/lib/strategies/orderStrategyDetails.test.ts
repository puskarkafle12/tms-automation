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

  test('shows stock quote polling when socket is failed', () => {
    const layout = buildStrategyDetailLayout(
      {
        script_name: 'CZBIL',
        status: 'pending',
        strategy_type: 'Fixed Price Buy',
        price: 190,
        qty: 10,
        socket_quote: { ltp: 199 },
        socket_status: 'failed',
        socket_last_received_at: '2026-07-05T04:46:52.799114+00:00',
        strategy_config: {
          last_tms_quote_source: 'socket',
        },
      },
      helpers,
    );

    expect(layout.secondary).toEqual(
      expect.arrayContaining([
        { label: 'Stock Quote Source', value: 'Stock quote polling', kind: 'text' },
        { label: 'Stock Quote Socket', value: 'failed - using stock quote polling', kind: 'text' },
      ]),
    );
  });

  test('shows socket paused when market is closed', () => {
    const layout = buildStrategyDetailLayout(
      {
        script_name: 'CZBIL',
        status: 'pending',
        strategy_type: 'Fixed Price Buy',
        price: 190,
        qty: 10,
        socket_status: 'paused_market_closed',
        tms_scan_count: 2591,
        strategy_config: {
          last_socket_status: 'failed',
          last_tms_quote_source: 'socket',
        },
      },
      helpers,
    );

    expect(layout.secondary).toEqual(
      expect.arrayContaining([
        { label: 'Stock Quote Checks', value: '2591', kind: 'text' },
        { label: 'Stock Quote Source', value: 'Stock quote polling (market closed)', kind: 'text' },
        { label: 'Stock Quote Socket', value: 'paused - market closed', kind: 'text' },
      ]),
    );
  });
});
