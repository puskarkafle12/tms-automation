import { shouldResetStoredApiUrl } from './api';

describe('api url helpers', () => {
  test('resets missing, ngrok, and localhost:8000 URLs on local app', () => {
    expect(shouldResetStoredApiUrl(null)).toBe(true);
    expect(shouldResetStoredApiUrl('')).toBe(true);
    expect(shouldResetStoredApiUrl('https://foo.ngrok-free.dev')).toBe(true);
    expect(shouldResetStoredApiUrl('http://localhost:8000')).toBe(true);
    expect(shouldResetStoredApiUrl('http://127.0.0.1:8000/')).toBe(true);
  });

  test('keeps matching local frontend origin', () => {
    expect(shouldResetStoredApiUrl('http://localhost:3000')).toBe(false);
    expect(shouldResetStoredApiUrl('http://127.0.0.1:3000/')).toBe(false);
  });

  test('keeps same-origin ngrok url when app is served from ngrok', () => {
    const original = window.location;
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: {
        ...original,
        hostname: 'untrained-pleading-unmarked.ngrok-free.dev',
        origin: 'https://untrained-pleading-unmarked.ngrok-free.dev',
      },
    });
    try {
      expect(shouldResetStoredApiUrl('https://untrained-pleading-unmarked.ngrok-free.dev')).toBe(false);
    } finally {
      Object.defineProperty(window, 'location', { configurable: true, value: original });
    }
  });
});
