export const SCRIPT_SUGGESTION_CACHE_TTL_MS = 20 * 60 * 1000;

const STORAGE_PREFIX = 'tms_script_suggestions:';

export type ScriptSuggestionSide = 'buy' | 'sell';

export interface ScriptSuggestionCacheEntry<T = unknown[]> {
  data: T;
  createdAt: number;
  expiresAt: number;
  cacheKey: string;
  clientId?: string;
  clientIds?: string[];
  orderSide: ScriptSuggestionSide;
}

export const getBuyScripCacheKey = (clientId?: string | null, isGlobal = false) =>
  isGlobal ? 'buy_scrips:all' : `buy_scrips:${clientId || ''}`;

export const getSellScripCacheKey = (clientIdOrClientIds?: string | string[] | null) => {
  if (Array.isArray(clientIdOrClientIds)) {
    return `sell_scrips:combined:${clientIdOrClientIds.filter(Boolean).sort().join(',')}`;
  }
  return `sell_scrips:${clientIdOrClientIds || ''}`;
};

export const isCacheValid = (entry: ScriptSuggestionCacheEntry | null) =>
  Boolean(entry && entry.expiresAt > Date.now());

export const getCachedScripSuggestions = <T = unknown[]>(
  cacheKey: string,
): ScriptSuggestionCacheEntry<T> | null => {
  try {
    const raw = localStorage.getItem(`${STORAGE_PREFIX}${cacheKey}`);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as ScriptSuggestionCacheEntry<T>;
    if (!parsed || parsed.cacheKey !== cacheKey || !Array.isArray(parsed.data)) {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
};

export const setCachedScripSuggestions = <T = unknown[]>(
  cacheKey: string,
  data: T,
  metadata: {
    orderSide: ScriptSuggestionSide;
    clientId?: string;
    clientIds?: string[];
  },
) => {
  const createdAt = Date.now();
  const entry: ScriptSuggestionCacheEntry<T> = {
    data,
    createdAt,
    expiresAt: createdAt + SCRIPT_SUGGESTION_CACHE_TTL_MS,
    cacheKey,
    ...metadata,
  };

  try {
    localStorage.setItem(`${STORAGE_PREFIX}${cacheKey}`, JSON.stringify(entry));
  } catch {
    // Ignore quota / private-mode errors.
  }
  return entry;
};
