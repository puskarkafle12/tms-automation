import { fetchJson } from '../utils/api';
import { loadGrabbers } from '../utils/grabberPersistence';
import { monitoringStore } from './monitoringStore';

interface MonitoringStatusResponse {
  scheduled_orders_active: boolean;
  active_grabber_count: number;
}

interface ActiveGrabberResponse {
  grabbers: Array<{ scanner_active?: boolean }>;
}

export async function syncMonitoringStatus(): Promise<void> {
  try {
    monitoringStore.syncActiveFromControls();
  } catch {
    // Local-only sync.
  }

  const statusResult = await fetchJson<MonitoringStatusResponse>('/monitoring-status/', undefined, 8000);
  if (!statusResult.ok) {
    return;
  }

  monitoringStore.setScheduledActive(Boolean(statusResult.data.scheduled_orders_active));

  const backendActive = Number(statusResult.data.active_grabber_count) || 0;
  const localTotal = loadGrabbers().length;

  const activeResult = await fetchJson<ActiveGrabberResponse>('/active_stock_grabbers/', undefined, 8000);
  let remoteActive = backendActive;
  if (activeResult.ok) {
    remoteActive = (activeResult.data.grabbers || []).filter((g) => g.scanner_active !== false).length;
  }

  const controlsActive = monitoringStore.getState().grabberActiveCount;
  const mergedActive = Math.max(remoteActive, controlsActive);
  const total = Math.max(localTotal, mergedActive);

  monitoringStore.setGrabberStats(mergedActive, total);
}
