// jest-dom adds custom jest matchers for asserting on DOM nodes.
// allows you to do things like:
// expect(element).toHaveTextContent(/react/i)
// learn more: https://github.com/testing-library/jest-dom
import '@testing-library/jest-dom';

const mockServerTimePayload = {
  now: {
    utc: '2026-06-20T01:44:49Z',
    npt: '2026-06-20T07:29:49+05:45',
    display: 'Jun 20, 2026, 07:29:49 AM',
    date: '2026-06-20',
    time: '07:29:49 AM',
    timezone: 'Asia/Kathmandu',
  },
  today_npt: '2026-06-20',
  timezone: 'Asia/Kathmandu',
};

jest.mock('./api/time.api', () => ({
  fetchServerTime: async () => mockServerTimePayload,
  getCachedServerTime: () => mockServerTimePayload,
  serverUtcToMs: (timestamp?: { utc?: string } | null) => {
    if (!timestamp?.utc) return null;
    const parsed = Date.parse(timestamp.utc);
    return Number.isFinite(parsed) ? parsed : null;
  },
}));

jest.mock('axios', () => ({
  __esModule: true,
  default: {
    create: jest.fn(() => ({
      get: jest.fn(),
      post: jest.fn(),
      put: jest.fn(),
      delete: jest.fn(),
      interceptors: {
        request: { use: jest.fn() },
        response: { use: jest.fn() },
      },
    })),
    get: jest.fn(async () => ({ data: mockServerTimePayload })),
    post: jest.fn(),
  },
}));
