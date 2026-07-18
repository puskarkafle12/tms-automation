export type BacktestSortRule = { field: string; direction: 'asc' | 'desc' };

/** First click ranks high-to-low; repeated clicks toggle the primary rule. */
export const nextBacktestSortRules = <T extends BacktestSortRule>(
  current: T[], field: string, additive: boolean, maximum = 8,
): T[] => {
  const index = current.findIndex((item) => item.field === field);
  if (!additive) {
    const direction = index === 0 && current.length === 1 && current[0].direction === 'desc' ? 'asc' : 'desc';
    return [{ field, direction } as T];
  }
  if (index >= 0) {
    return current.map((item, itemIndex) => itemIndex === index
      ? { ...item, direction: item.direction === 'desc' ? 'asc' : 'desc' } as T
      : item);
  }
  return current.length >= maximum ? current : [...current, { field, direction: 'desc' } as T];
};
