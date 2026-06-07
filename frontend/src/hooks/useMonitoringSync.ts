import { useEffect } from 'react';
import { fetchJson } from '../utils/api';
import { monitoringStore } from './monitoringStore';

interface MonitoringStatusResponse {
  scheduled_orders_active: boolean;
  active_grabber_count: number;
}

export const useMonitoringSync = () => {
  useEffect(() => {
    let active = true;

    const sync = async (): Promise<void> => {
      if (!active) {
        return;
      }

      try {
        monitoringStore.syncActiveFromControls();
      } catch {
        // Local store sync only — never surface to UI.
      }

      const result = await fetchJson<MonitoringStatusResponse>('/monitoring-status/', undefined, 8000);
      if (!active || !result.ok) {
        return;
      }

      const data = result.data;
      monitoringStore.setScheduledActive(Boolean(data.scheduled_orders_active));

      const backendActive = Number(data.active_grabber_count) || 0;
      const { grabberActiveCount, grabberTotal } = monitoringStore.getState();
      if (backendActive > grabberActiveCount) {
        monitoringStore.setGrabberStats(backendActive, Math.max(grabberTotal, backendActive));
      } else if (backendActive === 0 && grabberActiveCount > 0) {
        try {
          monitoringStore.syncActiveFromControls();
        } catch {
          // ignore
        }
      }
    };

    const safeSync = (): void => {
      void sync();
    };

    safeSync();
    const interval = window.setInterval(safeSync, 2000);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, []);
};
