import { offsetNepalDate, todayNepalDate } from './nepalTime';

export type HistoryRangePreset = 'week' | 'month' | 'custom' | 'forever';

export const FOREVER_FROM_DATE = '2010-10-01';

export const resolveHistoryDateRange = (
  preset: HistoryRangePreset,
  customFrom: string,
  customTo: string,
) => {
  const today = todayNepalDate();
  if (preset === 'forever') {
    return { fromDate: FOREVER_FROM_DATE, toDate: today };
  }
  if (preset === 'month') {
    return { fromDate: offsetNepalDate(today, { months: 1 }), toDate: today };
  }
  if (preset === 'custom') {
    return {
      fromDate: customFrom || offsetNepalDate(today, { days: 7 }),
      toDate: customTo || today,
    };
  }
  return { fromDate: offsetNepalDate(today, { days: 7 }), toDate: today };
};

export const historyRangeLabel = (
  preset: HistoryRangePreset,
  customFrom: string,
  customTo: string,
) => {
  if (preset === 'forever') {
    return 'All time';
  }
  const { fromDate, toDate } = resolveHistoryDateRange(preset, customFrom, customTo);
  return `${fromDate} to ${toDate}`;
};

export const isDateWithinHistoryRange = (
  value: string | null | undefined,
  fromDate: string,
  toDate: string,
) => {
  if (!value) {
    return false;
  }
  const day = value.slice(0, 10);
  if (!day) {
    return false;
  }
  return day >= fromDate && day <= toDate;
};
