import { buildScheduleScriptOptions } from './scheduleOrderHelpers';

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
});
