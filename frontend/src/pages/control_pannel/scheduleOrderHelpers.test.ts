import { buildScheduleScriptOptions, mergeQuoteIntoStockDetail, mergeUniqueStockDetails } from './scheduleOrderHelpers';

describe('buildScheduleScriptOptions', () => {
  const stockDetails = [
    { symbol: 'AAA', ltp: 100, percentChange: 1 },
    { symbol: 'BBB', ltp: 200, percentChange: -1 },
    { symbol: 'CCC', ltp: 300, percentChange: 0 },
  ];

  const holdings = [
    { scrip: 'BBB', currentBalance: 10, ltp: 200 },
    { scrip: 'CCC', currentBalance: 0, ltp: 300 },
    { scrip: 'DDD', currentBalance: 5, ltp: 400 },
  ];

  test('BUY search shows all listed scrips for the selected client', () => {
    expect(buildScheduleScriptOptions('buy', stockDetails, holdings).map((option) => option.symbol)).toEqual([
      'AAA',
      'BBB',
      'CCC',
    ]);
  });

  test('SELL search shows only owned scrips with positive holding quantity', () => {
    expect(buildScheduleScriptOptions('sell', stockDetails, holdings).map((option) => option.symbol)).toEqual([
      'BBB',
      'DDD',
    ]);
  });

  test('BUY cache merge keeps old unique scrips and adds new API scrips', () => {
    expect(
      mergeUniqueStockDetails(
        [
          { symbol: 'AAA', ltp: 100 },
          { symbol: 'BBB', ltp: 200 },
        ],
        [
          { symbol: 'BBB', ltp: 210 },
          { symbol: 'CCC', ltp: 300 },
        ],
      ).map((stock) => `${stock.symbol}:${stock.ltp}`),
    ).toEqual(['AAA:100', 'BBB:210', 'CCC:300']);
  });
});

describe('mergeQuoteIntoStockDetail', () => {
  test('updates snapshot fields from live quote payload', () => {
    const merged = mergeQuoteIntoStockDetail(
      {
        symbol: 'CZBIL',
        ltp: 195,
        open: 195,
        high: 198,
        low: 190,
        volume: 80000,
        previousClose: 200,
        change: -5,
        percentChange: -2.5,
        lastTradedVolume: 10,
        lastTradedTime: [2026, 6, 16, 14, 50, 0],
      },
      {
        ltp: 200,
        openPrice: 200,
        dayHigh: 202,
        dayLow: 195,
        volume: 82902,
        closePrice: 200,
        lastTradedQty: 100,
        lastTradedTime: '2026-06-16 14:59:56',
      },
    );

    expect(merged.ltp).toBe(200);
    expect(merged.open).toBe(200);
    expect(merged.high).toBe(202);
    expect(merged.low).toBe(195);
    expect(merged.volume).toBe(82902);
    expect(merged.change).toBe(0);
    expect(merged.percentChange).toBe(0);
    expect(merged.lastTradedTime).toEqual([2026, 6, 16, 14, 59, 56]);
  });
});
