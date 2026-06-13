export const formatMonitorDuration = (startedAt: string | null | undefined, now = Date.now()): string => {
  if (!startedAt) {
    return '';
  }

  const startedMs = Date.parse(startedAt);
  if (Number.isNaN(startedMs) || startedMs > now) {
    return '';
  }

  const totalMinutes = Math.floor((now - startedMs) / 60000);
  const days = Math.floor(totalMinutes / (60 * 24));
  const hours = Math.floor((totalMinutes % (60 * 24)) / 60);
  const minutes = totalMinutes % 60;

  if (days > 0) {
    return `${days}d ${hours}h`;
  }
  if (hours > 0) {
    return `${hours}h ${minutes}m`;
  }
  if (minutes > 0) {
    return `${minutes}m`;
  }
  return '<1m';
};
