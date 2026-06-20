import {
  FOREVER_FROM_DATE,
  historyRangeLabel,
  resolveHistoryDateRange,
} from './orderHistoryRange';
import { setServerTodayNpt, todayNepalDate } from './nepalTime';

describe('orderHistoryRange', () => {
  beforeAll(() => {
    setServerTodayNpt('2026-06-20');
  });
  test('forever range ends today, not in the future', () => {
    const today = todayNepalDate();
    const range = resolveHistoryDateRange('forever', '', '');
    expect(range.fromDate).toBe('2010-10-01');
    expect(range.toDate).toBe(today);
    expect(range.toDate <= today).toBe(true);
  });

  test('week range uses last 7 days through today', () => {
    const today = todayNepalDate();
    const range = resolveHistoryDateRange('week', '', '');
    expect(range.toDate).toBe(today);
    expect(range.fromDate < today).toBe(true);
  });

  test('custom range falls back when dates are missing', () => {
    const today = todayNepalDate();
    const range = resolveHistoryDateRange('custom', '', '');
    expect(range.toDate).toBe(today);
    expect(range.fromDate).toBeTruthy();
  });

  test('forever label is human friendly', () => {
    expect(historyRangeLabel('forever', '', '')).toBe('All time');
    expect(historyRangeLabel('week', '', '')).toContain('to');
  });
});
