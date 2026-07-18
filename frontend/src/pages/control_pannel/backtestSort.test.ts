import { nextBacktestSortRules } from './backtestSort';

test('first click on win rate sorts descending', () => {
  expect(nextBacktestSortRules([{ field: 'robust_score', direction: 'desc' }], 'win_rate_pct', false))
    .toEqual([{ field: 'win_rate_pct', direction: 'desc' }]);
});

test('second click on active win rate sorts ascending', () => {
  expect(nextBacktestSortRules([{ field: 'win_rate_pct', direction: 'desc' }], 'win_rate_pct', false))
    .toEqual([{ field: 'win_rate_pct', direction: 'asc' }]);
});

test('shift click adds a descending secondary rule', () => {
  expect(nextBacktestSortRules([{ field: 'robust_score', direction: 'desc' }], 'win_rate_pct', true))
    .toEqual([{ field: 'robust_score', direction: 'desc' }, { field: 'win_rate_pct', direction: 'desc' }]);
});
