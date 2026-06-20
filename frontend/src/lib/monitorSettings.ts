export const MIN_SCAN_INTERVAL_SECONDS = 3;
export const MAX_SCAN_INTERVAL_SECONDS = 300;
export const MIN_MAX_DATA_AGE_SECONDS = 5;
export const MAX_MAX_DATA_AGE_SECONDS = 3600;

export type ExecutionMode = 'live' | 'paper';

export interface MonitorSettings {
  scanIntervalSeconds: number;
  maxDataAgeSeconds: number | null;
  executionMode: ExecutionMode;
}

export const buildDefaultMonitorSettings = (portalIntervalSeconds = 5): MonitorSettings => ({
  scanIntervalSeconds: clampScanInterval(portalIntervalSeconds),
  maxDataAgeSeconds: null,
  executionMode: 'live',
});

export function clampScanInterval(value: number, fallback = 5): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return clampScanInterval(fallback, MIN_SCAN_INTERVAL_SECONDS);
  }
  return Math.max(MIN_SCAN_INTERVAL_SECONDS, Math.min(MAX_SCAN_INTERVAL_SECONDS, Math.round(parsed)));
}

export function clampMaxDataAge(value: number | null | undefined): number | null {
  if (value == null || value <= 0) {
    return null;
  }
  return Math.max(MIN_MAX_DATA_AGE_SECONDS, Math.min(MAX_MAX_DATA_AGE_SECONDS, Math.round(value)));
}

export function monitorSettingsFromConfig(
  config: Record<string, unknown> | undefined,
  portalIntervalSeconds = 5,
): MonitorSettings {
  const scanRaw = Number(config?.scan_interval_seconds);
  const maxAgeRaw = Number(config?.max_data_age_seconds);
  const mode = String(config?.execution_mode || 'live').toLowerCase();
  return {
    scanIntervalSeconds: clampScanInterval(
      Number.isFinite(scanRaw) && scanRaw > 0 ? scanRaw : portalIntervalSeconds,
    ),
    maxDataAgeSeconds: Number.isFinite(maxAgeRaw) && maxAgeRaw > 0
      ? clampMaxDataAge(maxAgeRaw)
      : null,
    executionMode: mode === 'paper' ? 'paper' : 'live',
  };
}

export function monitorSettingsToConfig(settings: MonitorSettings): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    scan_interval_seconds: clampScanInterval(settings.scanIntervalSeconds),
    execution_mode: settings.executionMode,
  };
  const maxAge = clampMaxDataAge(settings.maxDataAgeSeconds);
  if (maxAge != null) {
    payload.max_data_age_seconds = maxAge;
  }
  return payload;
}
