import { useEffect } from 'react';
import { syncMonitoringStatus } from './monitoringSync';

export const useMonitoringSync = () => {
  useEffect(() => {
    let active = true;

    const safeSync = (): void => {
      if (!active) {
        return;
      }
      void syncMonitoringStatus();
    };

    safeSync();
    const interval = window.setInterval(safeSync, 5000);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, []);
};
