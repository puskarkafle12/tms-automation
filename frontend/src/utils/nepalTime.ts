export const NEPAL_TIME_ZONE = 'Asia/Kathmandu';

const nepalDateTimeParts = (date = new Date()) => {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: NEPAL_TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).formatToParts(date);

  const get = (type: string) => parts.find((part) => part.type === type)?.value || '';
  return {
    year: get('year'),
    month: get('month'),
    day: get('day'),
    hour: get('hour'),
    minute: get('minute'),
    second: get('second'),
  };
};

export const todayNepalDate = () => {
  const parts = nepalDateTimeParts();
  return `${parts.year}-${parts.month}-${parts.day}`;
};

export const currentNepalDateTimeLocal = () => {
  const parts = nepalDateTimeParts();
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second}`;
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

export const formatNepalDateTime = (value: string | null | undefined) => {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat('en-NP', {
    timeZone: NEPAL_TIME_ZONE,
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
  }).format(date);
};
