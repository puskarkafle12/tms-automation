import type { ApiTimestamp } from '../api/time.api';
import { getCachedServerTime } from '../api/time.api';

export const NEPAL_TIME_ZONE = 'Asia/Kathmandu';

export type ApiTimeValue = ApiTimestamp | string | null | undefined;

export const isApiTimestamp = (value: unknown): value is ApiTimestamp =>
  typeof value === 'object'
  && value !== null
  && 'display' in value
  && typeof (value as ApiTimestamp).display === 'string';

export const formatNepalDateTime = (value: ApiTimeValue): string => {
  if (!value) return '';
  if (isApiTimestamp(value)) {
    return value.display.replace(/\s+NPT\b/g, '');
  }
  if (typeof value === 'string') {
    return value.replace(/\s+NPT\b/g, '');
  }
  return '';
};

export const apiTimestampToUtcMs = (value: ApiTimeValue): number | null => {
  if (!value) return null;
  if (isApiTimestamp(value)) {
    const parsed = Date.parse(value.utc);
    return Number.isFinite(parsed) ? parsed : null;
  }
  if (typeof value === 'string') {
    const normalized = value.endsWith('Z') || value.includes('+') ? value : `${value}Z`;
    const parsed = Date.parse(normalized);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
};

export const isoToNepalDateTimeLocal = (value: ApiTimeValue) => {
  if (!value) {
    return '';
  }
  if (isApiTimestamp(value)) {
    const match = value.npt.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/);
    return match ? `${match[1]}T${match[2]}` : '';
  }
  if (typeof value === 'string') {
    const normalized = value.endsWith('Z') || value.includes('+') ? value : `${value}Z`;
    const parsed = Date.parse(normalized);
    if (!Number.isFinite(parsed)) {
      return '';
    }
    const match = value.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/);
    if (match && !value.endsWith('Z') && !value.includes('+')) {
      return `${match[1]}T${match[2]}`;
    }
  }
  return '';
};

export const formatNepalClockFromUtcMs = (utcMs: number) => {
  const instant = new Date(utcMs);
  const time = new Intl.DateTimeFormat('en-US', {
    timeZone: NEPAL_TIME_ZONE,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
  }).format(instant);
  const date = new Intl.DateTimeFormat('en-CA', {
    timeZone: NEPAL_TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(instant);
  const display = `${new Intl.DateTimeFormat('en-US', {
    timeZone: NEPAL_TIME_ZONE,
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
  }).format(instant)}`;
  return { time, date, display };
};

let cachedTodayNpt: string | null = null;

export const setServerTodayNpt = (today: string) => {
  cachedTodayNpt = today;
};

export const todayNepalDate = () => cachedTodayNpt || '';

export const currentNepalDateTimeLocal = () => {
  const npt = getCachedServerTime()?.now?.npt;
  if (!npt) {
    return '';
  }
  return npt.slice(0, 19);
};

export const dateFromNepalDateString = (value: string) => {
  const [year, month, day] = value.split('-').map(Number);
  if (!year || !month || !day) {
    return null;
  }
  return new Date(year, month - 1, day);
};

export const nepalDateStringFromDate = (value: Date | null) => {
  if (!value) {
    return todayNepalDate();
  }
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, '0');
  const day = String(value.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
};

export const offsetNepalDate = (
  baseDateStr: string,
  { days = 0, months = 0 }: { days?: number; months?: number },
) => {
  const date = dateFromNepalDateString(baseDateStr);
  if (!date) {
    return baseDateStr;
  }
  if (months) {
    date.setMonth(date.getMonth() - months);
  }
  if (days) {
    date.setDate(date.getDate() - days);
  }
  return nepalDateStringFromDate(date);
};

export const addNepalDays = (baseDateStr: string, days: number) => {
  const date = dateFromNepalDateString(baseDateStr);
  if (!date) {
    return baseDateStr;
  }
  date.setDate(date.getDate() + days);
  return nepalDateStringFromDate(date);
};
