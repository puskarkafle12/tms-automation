import { MonitorPhase } from '../types/monitoringStatus';

const STORAGE_KEY = 'tms_monitoring_snapshot';

export interface MonitoringSnapshot {
  savedAt: string;
  scheduledActive: boolean;
  scheduledScanning: boolean;
  scheduledPhase: MonitorPhase;
  scheduledStatusMessage: string;
  scheduledStartedAt: string | null;
  grabberActiveCount: number;
  grabberScanningCount: number;
  grabberTotal: number;
}

const isMonitorPhase = (value: unknown): value is MonitorPhase =>
  value === 'stopped'
  || value === 'waiting_hours'
  || value === 'waiting_session'
  || value === 'active'
  || value === 'armed';

const normalizeSnapshot = (raw: unknown): MonitoringSnapshot | null => {
  if (!raw || typeof raw !== 'object') {
    return null;
  }

  const data = raw as Partial<MonitoringSnapshot>;
  const phase = isMonitorPhase(data.scheduledPhase) ? data.scheduledPhase : 'stopped';

  return {
    savedAt: typeof data.savedAt === 'string' ? data.savedAt : new Date().toISOString(),
    scheduledActive: Boolean(data.scheduledActive),
    scheduledScanning: Boolean(data.scheduledScanning),
    scheduledPhase: phase,
    scheduledStatusMessage: typeof data.scheduledStatusMessage === 'string' ? data.scheduledStatusMessage : '',
    scheduledStartedAt: typeof data.scheduledStartedAt === 'string' ? data.scheduledStartedAt : null,
    grabberActiveCount: Math.max(0, Number(data.grabberActiveCount) || 0),
    grabberScanningCount: Math.max(0, Number(data.grabberScanningCount) || 0),
    grabberTotal: Math.max(0, Number(data.grabberTotal) || 0),
  };
};

export const loadMonitoringSnapshot = (): MonitoringSnapshot | null => {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return null;
    }
    return normalizeSnapshot(JSON.parse(raw));
  } catch {
    return null;
  }
};

export const saveMonitoringSnapshot = (snapshot: MonitoringSnapshot): void => {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      ...snapshot,
      savedAt: new Date().toISOString(),
    }));
  } catch {
    // Ignore quota / private-mode errors.
  }
};
