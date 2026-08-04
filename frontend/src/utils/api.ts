/** Same-origin API URL — nginx (Docker) or CRA proxy (npm start) forwards to the backend. */
export const getDefaultApiUrl = (): string => window.location.origin.replace(/\/$/, '');

export const isLocalAppOrigin = (): boolean => {
  const { hostname } = window.location;
  return hostname === 'localhost' || hostname === '127.0.0.1';
};

/** Reset apiUrl when it points at a tunnel or a bare backend port while the UI is local. */
export const shouldResetStoredApiUrl = (stored: string | null | undefined): boolean => {
  const trimmed = stored?.trim();
  if (!trimmed) {
    return true;
  }
  if (!isLocalAppOrigin()) {
    return false;
  }
  if (/(ngrok|zrok|shares\.zrok\.io)/i.test(trimmed)) {
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

export const buildWebSocketUrl = (path: string, params?: Record<string, string | number | boolean | null | undefined>): string => {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  const baseUrl = new URL(getApiUrl());
  baseUrl.pathname = normalizedPath;
  baseUrl.search = '';
  baseUrl.hash = '';
  baseUrl.protocol = baseUrl.protocol === 'https:' ? 'wss:' : 'ws:';
  if (params) {
    Object.entries(params).forEach(([key, value]) => {
      if (value === null || value === undefined || value === '') {
        return;
      }
      baseUrl.searchParams.set(key, String(value));
    });
  }
  const token = localStorage.getItem('accessToken');
  if (token) baseUrl.searchParams.set('token', token);
  return baseUrl.toString();
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
  | { ok: false; error: string; status?: number; cancelled?: boolean };

export async function fetchJson<T>(
  path: string,
  init?: RequestInit,
  timeoutMs = 10000,
): Promise<FetchJsonResult<T>> {
  const externalSignal = init?.signal;
  let timedOut = false;
  const timeoutController = new AbortController();
  const onExternalAbort = () => timeoutController.abort();

  if (externalSignal) {
    if (externalSignal.aborted) {
      timeoutController.abort();
    } else {
      externalSignal.addEventListener('abort', onExternalAbort);
    }
  }

  const timeoutId = window.setTimeout(() => {
    timedOut = true;
    timeoutController.abort();
  }, timeoutMs);

  const { signal: _ignored, ...restInit } = init || {};

  try {
    const response = await Promise.resolve().then(() =>
      fetch(buildUrl(path), {
        ...restInit,
        signal: timeoutController.signal,
        cache: 'no-store',
      }),
    );

    window.clearTimeout(timeoutId);

    if (!response.ok) {
      let errorMessage = `HTTP ${response.status}`;
      try {
        const body = await response.json() as { detail?: unknown; message?: string; errors?: Array<{ message?: string }> };
        if (typeof body.detail === 'string') {
          errorMessage = body.detail;
        } else if (Array.isArray(body.detail)) {
          errorMessage = body.detail.map((item) => (typeof item === 'object' && item && 'msg' in item ? String((item as { msg?: string }).msg) : String(item))).join('; ');
        } else if (body.detail && typeof body.detail === 'object' && !Array.isArray(body.detail)) {
          const detailObj = body.detail as {
            message?: string;
            generated_query?: string;
            errors?: Array<{ message?: string }>;
          };
          if (detailObj.message) {
            errorMessage = detailObj.message;
          } else if (detailObj.errors?.[0]?.message) {
            errorMessage = detailObj.errors[0].message;
          }
        } else if (body.errors?.[0]?.message) {
          errorMessage = body.errors[0].message;
        } else if (body.message) {
          errorMessage = body.message;
        }
      } catch {
        // keep generic HTTP status message
      }
      return { ok: false, error: errorMessage, status: response.status };
    }

    const data = (await response.json()) as T;
    return { ok: true, data, status: response.status };
  } catch (err) {
    window.clearTimeout(timeoutId);
    if (err instanceof Error && err.name === 'AbortError') {
      if (externalSignal?.aborted && !timedOut) {
        return { ok: false, error: '', cancelled: true };
      }
      const seconds = Math.round(timeoutMs / 1000);
      return {
        ok: false,
        error: `Request timed out after ${seconds}s. The server may still be processing — check Order Logs.`,
        status: 408,
      };
    }
    const message = err instanceof Error ? err.message : 'Network error';
    if (/aborted|abort/i.test(message)) {
      if (externalSignal?.aborted && !timedOut) {
        return { ok: false, error: '', cancelled: true };
      }
      const seconds = Math.round(timeoutMs / 1000);
      return {
        ok: false,
        error: `Request timed out after ${seconds}s. The server may still be processing — check Order Logs.`,
        status: 408,
      };
    }
    return { ok: false, error: message };
  } finally {
    externalSignal?.removeEventListener('abort', onExternalAbort);
  }
};
