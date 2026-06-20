export const UI_SETTINGS_KEY = 'tms_portal_ui_settings';
export const UI_SETTINGS_EVENT = 'tms-ui-settings-changed';

export const MIN_ORDER_LOGS_LIVE_REFRESH_SECONDS = 3;
export const MAX_ORDER_LOGS_LIVE_REFRESH_SECONDS = 120;
export const MIN_ORDER_LOGS_BACKGROUND_REFRESH_MINUTES = 1;
export const MAX_ORDER_LOGS_BACKGROUND_REFRESH_MINUTES = 60;
export const MIN_MARKET_STATUS_POLL_SECONDS = 10;
export const MAX_MARKET_STATUS_POLL_SECONDS = 120;
export const MIN_VALIDATE_DEBOUNCE_MS = 400;
export const MAX_VALIDATE_DEBOUNCE_MS = 3000;

export interface UiPortalSettings {
  orderLogsLiveRefreshSeconds: number;
  orderLogsBackgroundRefreshMinutes: number;
  marketStatusPollSeconds: number;
  customQueryValidateDebounceMs: number;
}

export const DEFAULT_UI_PORTAL_SETTINGS: UiPortalSettings = {
  orderLogsLiveRefreshSeconds: 10,
  orderLogsBackgroundRefreshMinutes: 20,
  marketStatusPollSeconds: 30,
  customQueryValidateDebounceMs: 2000,
};

const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, Math.round(value)));

export function normalizeUiPortalSettings(raw?: Partial<UiPortalSettings> | null): UiPortalSettings {
  const source = raw || {};
  return {
    orderLogsLiveRefreshSeconds: clamp(
      Number(source.orderLogsLiveRefreshSeconds) || DEFAULT_UI_PORTAL_SETTINGS.orderLogsLiveRefreshSeconds,
      MIN_ORDER_LOGS_LIVE_REFRESH_SECONDS,
      MAX_ORDER_LOGS_LIVE_REFRESH_SECONDS,
    ),
    orderLogsBackgroundRefreshMinutes: clamp(
      Number(source.orderLogsBackgroundRefreshMinutes) || DEFAULT_UI_PORTAL_SETTINGS.orderLogsBackgroundRefreshMinutes,
      MIN_ORDER_LOGS_BACKGROUND_REFRESH_MINUTES,
      MAX_ORDER_LOGS_BACKGROUND_REFRESH_MINUTES,
    ),
    marketStatusPollSeconds: clamp(
      Number(source.marketStatusPollSeconds) || DEFAULT_UI_PORTAL_SETTINGS.marketStatusPollSeconds,
      MIN_MARKET_STATUS_POLL_SECONDS,
      MAX_MARKET_STATUS_POLL_SECONDS,
    ),
    customQueryValidateDebounceMs: clamp(
      Number(source.customQueryValidateDebounceMs) || DEFAULT_UI_PORTAL_SETTINGS.customQueryValidateDebounceMs,
      MIN_VALIDATE_DEBOUNCE_MS,
      MAX_VALIDATE_DEBOUNCE_MS,
    ),
  };
}

export function readUiPortalSettings(): UiPortalSettings {
  try {
    const raw = localStorage.getItem(UI_SETTINGS_KEY);
    if (!raw) {
      return { ...DEFAULT_UI_PORTAL_SETTINGS };
    }
    return normalizeUiPortalSettings(JSON.parse(raw));
  } catch {
    return { ...DEFAULT_UI_PORTAL_SETTINGS };
  }
}

export function writeUiPortalSettings(next: Partial<UiPortalSettings>): UiPortalSettings {
  const merged = normalizeUiPortalSettings({ ...readUiPortalSettings(), ...next });
  localStorage.setItem(UI_SETTINGS_KEY, JSON.stringify(merged));
  window.dispatchEvent(new CustomEvent(UI_SETTINGS_EVENT, { detail: merged }));
  return merged;
}

export function resetUiPortalSettings(): UiPortalSettings {
  localStorage.removeItem(UI_SETTINGS_KEY);
  const defaults = { ...DEFAULT_UI_PORTAL_SETTINGS };
  window.dispatchEvent(new CustomEvent(UI_SETTINGS_EVENT, { detail: defaults }));
  return defaults;
}

export function subscribeUiPortalSettings(listener: (settings: UiPortalSettings) => void): () => void {
  const handler = (event: Event) => {
    const detail = (event as CustomEvent<UiPortalSettings>).detail;
    listener(detail || readUiPortalSettings());
  };
  window.addEventListener(UI_SETTINGS_EVENT, handler);
  return () => window.removeEventListener(UI_SETTINGS_EVENT, handler);
}
