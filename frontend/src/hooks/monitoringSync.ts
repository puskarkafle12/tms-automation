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

  monitoringStore.applyBackendStatus({
    scheduledActive: Boolean(data.scheduled_orders_active),
    scheduledScanning: Boolean(data.scheduled_scanning),
    scheduledPhase: phase,
    scheduledStatusMessage: data.scheduled_status_message || '',
    scheduledStartedAt: data.scheduled_started_at || null,
    grabberActiveCount: backendActive,
    grabberScanningCount: backendScanning,
    grabberTotal: localTotal,
    remoteGrabbers: data.grabbers || [],
  });

  return true;
}
