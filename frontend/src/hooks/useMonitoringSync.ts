import { useEffect } from 'react';
import { monitoringStore } from './monitoringStore';

const getApiUrl = () => localStorage.getItem('apiUrl') || 'http://localhost:8000';

export const useMonitoringSync = () => {
  useEffect(() => {
    const sync = async () => {
      monitoringStore.syncActiveFromControls();

      try {
        const response = await fetch(`${getApiUrl()}/monitoring-status/`);
        if (!response.ok) {
          return;
        }
        const data = await response.json();
        monitoringStore.setScheduledActive(Boolean(data.scheduled_orders_active));

        const backendActive = Number(data.active_grabber_count) || 0;
        const { grabberActiveCount, grabberTotal } = monitoringStore.getState();
        if (backendActive > grabberActiveCount) {
          monitoringStore.setGrabberStats(backendActive, Math.max(grabberTotal, backendActive));
        } else if (backendActive === 0 && grabberActiveCount > 0) {
          monitoringStore.syncActiveFromControls();
        }
      } catch {
        // Backend may be offline; local control sync still runs above.
      }
    };

    sync();
    const interval = setInterval(sync, 2000);
    return () => clearInterval(interval);
  }, []);
};
