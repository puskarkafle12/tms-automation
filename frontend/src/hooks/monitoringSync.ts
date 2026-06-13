import { fetchJson } from '../utils/api';
import { loadGrabbers } from '../utils/grabberPersistence';
import { monitoringStore } from './monitoringStore';
import { MonitorPhase, RemoteGrabberStatus } from '../types/monitoringStatus';

interface MonitoringStatusResponse {
  scheduled_orders_active: boolean;
  scheduled_scanning?: boolean;
  scheduled_phase?: MonitorPhase | string;
  scheduled_status_message?: string;
  scheduled_started_at?: string | null;
  active_grabber_count: number;
  grabber_scanning_count?: number;
  grabbers?: RemoteGrabberStatus[];
}

export async function syncMonitoringStatus(): Promise<boolean> {
  const statusResult = await fetchJson<MonitoringStatusResponse>('/monitoring-status/', undefined, 8000);
  if (!statusResult.ok) {
    monitoringStore.setStatusLoaded(true);
    return false;
  }

  const data = statusResult.data;
  const phase = (data.scheduled_phase || (data.scheduled_orders_active ? 'armed' : 'stopped')) as MonitorPhase;
  const backendActive = Number(data.active_grabber_count) || 0;
  const backendScanning = Number(data.grabber_scanning_count) || 0;
  const localTotal = loadGrabbers().length;
  const current = monitoringStore.getState();

  let scheduledActive = Boolean(data.scheduled_orders_active);
  let scheduledScanning = Boolean(data.scheduled_scanning);
  let scheduledPhase = phase;
  let scheduledStatusMessage = data.scheduled_status_message || '';
  let scheduledStartedAt = data.scheduled_started_at || null;
  let grabberActiveCount = backendActive;
  let grabberScanningCount = backendScanning;

  if (current.scheduledLoading === 'start') {
    scheduledActive = true;
    if (scheduledPhase === 'stopped') {
      scheduledPhase = 'waiting_hours';
    }
    if (!scheduledStatusMessage) {
      scheduledStatusMessage = current.scheduledStatusMessage || 'Armed — waiting for market';
    }
    scheduledStartedAt = scheduledStartedAt || current.scheduledStartedAt;
  } else if (current.scheduledLoading === 'stop') {
    scheduledActive = false;
    scheduledScanning = false;
    scheduledPhase = 'stopped';
    scheduledStatusMessage = '';
    scheduledStartedAt = null;
  }

  if (current.grabberLoading === 'start') {
    grabberActiveCount = Math.max(backendActive, current.grabberActiveCount);
  } else if (current.grabberLoading === 'stop') {
    grabberActiveCount = 0;
    grabberScanningCount = 0;
  }

  monitoringStore.applyBackendStatus({
    scheduledActive,
    scheduledScanning,
    scheduledPhase,
    scheduledStatusMessage,
    scheduledStartedAt,
    grabberActiveCount,
    grabberScanningCount,
    grabberTotal: localTotal,
    remoteGrabbers: data.grabbers || [],
  });

  return true;
}
