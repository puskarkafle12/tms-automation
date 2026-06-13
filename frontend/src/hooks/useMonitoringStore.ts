import { useSyncExternalStore } from 'react';
import { monitoringStore } from './monitoringStore';

export const useMonitoringStore = () => useSyncExternalStore(
  monitoringStore.subscribe,
  monitoringStore.getSnapshot,
  monitoringStore.getSnapshot,
);
