import { useEffect, useState } from 'react';
import { syncMonitoringStatus } from './monitoringSync';
import { readUiPortalSettings, subscribeUiPortalSettings } from '../lib/uiPortalSettings';

export const useMonitoringSync = (enabled = true) => {
  const [pollSeconds, setPollSeconds] = useState(() => readUiPortalSettings().marketStatusPollSeconds);

  useEffect(() => subscribeUiPortalSettings((settings) => {
    setPollSeconds(settings.marketStatusPollSeconds);
  }), []);

  useEffect(() => {
    if (!enabled) return undefined;
    let active = true;

    const safeSync = (): void => {
      if (!active) {
        return;
      }
      void syncMonitoringStatus();
    };

    safeSync();
    const interval = window.setInterval(safeSync, Math.max(1, pollSeconds) * 1000);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, [enabled, pollSeconds]);
};
