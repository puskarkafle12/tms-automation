export const getApiUrl = (): string => {
  const stored = localStorage.getItem('apiUrl')?.trim();
  if (stored) {
    return stored.replace(/\/$/, '');
  }
  return 'http://localhost:8000';
};

const buildUrl = (path: string): string => {
  if (path.startsWith('http://') || path.startsWith('https://')) {
    return path;
  }
  const normalized = path.startsWith('/') ? path : `/${path}`;
  return `${getApiUrl()}${normalized}`;
};

export type FetchJsonResult<T> =
  | { ok: true; data: T; status: number }
  | { ok: false; error: string; status?: number };

export async function fetchJson<T>(
  path: string,
  init?: RequestInit,
  timeoutMs = 10000,
): Promise<FetchJsonResult<T>> {
  try {
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);

    const response = await Promise.resolve().then(() =>
      fetch(buildUrl(path), {
        ...init,
        signal: controller.signal,
        cache: 'no-store',
      }),
    );

    window.clearTimeout(timeoutId);

    if (!response.ok) {
      return { ok: false, error: `HTTP ${response.status}`, status: response.status };
    }

    const data = (await response.json()) as T;
    return { ok: true, data, status: response.status };
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Network error';
    return { ok: false, error: message };
  }
}
