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

  test('shows live condition states, net position costs, and fixed references', () => {
    const layout = buildStrategyDetailLayout(
      {
        script_name: 'MLBBL',
        status: 'pending',
        strategy_type: 'Custom Query Buy',
        qty: 10,
        strategy_config: {
          lifecycle_active: true,
          min_holding_days: 5,
          max_holding_days: 90,
          live_condition_status: {
            logic: 'AND',
            matched: false,
            conditions: [
              { label: 'SMA 20 trend', matched: true, current_display: 'above', required_display: 'above' },
              { label: 'MACD', matched: false, current_display: 'Bearish', required_display: 'Bullish' },
            ],
          },
          live_position_metrics: {
            entry_price: 1000,
            ltp: 1100,
            gross_profit_percent: 10,
            estimated_buy_charges: 350,
            estimated_total_sell_charges: 600,
            estimated_net_profit: 9050,
            profit_percent: 9.02,
          },
          field_reference_rows: [{ field_key: 'ltp', numeric_value: 1149 }],
        },
      },
      helpers,
    );

    expect(layout.conditionLogic).toBe('AND');
    expect(layout.conditions?.map((item) => item.status)).toEqual(['satisfied', 'waiting']);
    expect(layout.positionMetrics).toEqual(expect.arrayContaining([
      expect.objectContaining({ label: 'Estimated net profit', value: 'Rs. 9,050' }),
      expect.objectContaining({ label: 'profit_percent used by rules', value: '9.02%' }),
    ]));
    expect(layout.fixedReferences).toEqual([
      expect.objectContaining({ label: 'LTP · fixed reference', value: 'Rs. 1,149' }),
    ]);
  });
});
