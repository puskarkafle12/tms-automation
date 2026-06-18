/** Same-origin API URL — nginx (Docker) or CRA proxy (npm start) forwards to the backend. */
export const getDefaultApiUrl = (): string => window.location.origin.replace(/\/$/, '');

export const isLocalAppOrigin = (): boolean => {
  const { hostname } = window.location;
  return hostname === 'localhost' || hostname === '127.0.0.1';
};

/** Reset apiUrl when it points at ngrok or a bare backend port while the UI is local. */
export const shouldResetStoredApiUrl = (stored: string | null | undefined): boolean => {
  const trimmed = stored?.trim();
  if (!trimmed) {
    return true;
  }
  if (!isLocalAppOrigin()) {
    return false;
  }
  if (/ngrok/i.test(trimmed)) {
    return true;
  }
  if (/^https?:\/\/(localhost|127\.0\.0\.1):8000\/?$/i.test(trimmed)) {
    return true;
  }
  return false;
};

export const getApiUrl = (): string => {
  const stored = localStorage.getItem('apiUrl')?.trim();
  if (stored && !shouldResetStoredApiUrl(stored)) {
    return stored.replace(/\/$/, '');
  }
  return getDefaultApiUrl();
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
};
