export interface StockGrabberInstance {
  id: string;
  client_id: string;
  stock_symbol: string;
  sessionId?: string | null;
  isRunning?: boolean;
  order_quantity?: number;
  request_per_sec?: number;
  scanCount?: number;
  stableRate?: number | null;
}

export interface ActiveGrabberFromApi {
  session_id: string;
  client_id: string;
  stock_symbol: string;
  scan_count: number;
  scanner_active: boolean;
  request_per_sec: number;
  stable_rate: number | null;
}

const STORAGE_KEY = 'stock_grabber_instances';

export const loadGrabbers = (): StockGrabberInstance[] => {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw) as StockGrabberInstance[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
};

export const saveGrabbers = (grabbers: StockGrabberInstance[]) => {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(grabbers));
  } catch {
    // Ignore quota errors.
  }
};

export const mergeWithActiveGrabbers = (
  local: StockGrabberInstance[],
  active: ActiveGrabberFromApi[],
): StockGrabberInstance[] => {
  const activeSessionIds = new Set(active.map((g) => g.session_id));
  const merged = local.map((grabber) => {
    const match =
      active.find((g) => g.session_id === grabber.sessionId)
      || active.find(
        (g) =>
          g.client_id === grabber.client_id
          && g.stock_symbol.toUpperCase() === grabber.stock_symbol.toUpperCase(),
      );

    if (!match) {
      if (grabber.sessionId && !activeSessionIds.has(grabber.sessionId)) {
        return { ...grabber, isRunning: false, sessionId: null };
      }
      return grabber;
    }

    return {
      ...grabber,
      client_id: match.client_id,
      stock_symbol: match.stock_symbol,
      sessionId: match.session_id,
      isRunning: match.scanner_active,
      request_per_sec: match.request_per_sec,
      scanCount: match.scan_count,
      stableRate: match.stable_rate,
    };
  });

  active.forEach((remote) => {
    const exists = merged.some(
      (g) =>
        g.sessionId === remote.session_id
        || (
          g.client_id === remote.client_id
          && g.stock_symbol.toUpperCase() === remote.stock_symbol.toUpperCase()
        ),
    );
    if (!exists) {
      merged.push({
        id: `restored-${remote.session_id}`,
        client_id: remote.client_id,
        stock_symbol: remote.stock_symbol,
        sessionId: remote.session_id,
        isRunning: remote.scanner_active,
        request_per_sec: remote.request_per_sec,
        scanCount: remote.scan_count,
        stableRate: remote.stable_rate,
      });
    }
  });

  return merged;
};

export const sortGrabbersRunningFirst = (grabbers: StockGrabberInstance[]) =>
  [...grabbers].sort((a, b) => Number(Boolean(b.isRunning)) - Number(Boolean(a.isRunning)));
