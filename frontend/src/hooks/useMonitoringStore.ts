import { useEffect, useState } from 'react';
import { monitoringStore } from './monitoringStore';

export const useMonitoringStore = () => {
  const [snapshot, setSnapshot] = useState(monitoringStore.getState());

  useEffect(() => {
    return monitoringStore.subscribe(() => setSnapshot(monitoringStore.getState()));
  }, []);

  return snapshot;
};
