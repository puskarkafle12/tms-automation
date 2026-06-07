import { useCallback, useState } from 'react';
import { monitoringStore } from './monitoringStore';
import { useMonitoringStore } from './useMonitoringStore';

const getApiUrl = () => localStorage.getItem('apiUrl') || 'http://localhost:8000';

export const useMonitoringActions = () => {
  const { scheduledActive, grabberActiveCount, grabberTotal, grabberCanStart } = useMonitoringStore();
  const [scheduledLoading, setScheduledLoading] = useState<'start' | 'stop' | null>(null);
  const [grabberLoading, setGrabberLoading] = useState<'start' | 'stop' | null>(null);

  const startScheduled = async () => {
    setScheduledLoading('start');
    try {
      const response = await fetch(`${getApiUrl()}/check_orders/`, {
        headers: { accept: 'application/json' },
      });
      if (response.ok) {
        monitoringStore.setScheduledActive(true);
        return { ok: true as const };
      }
      const data = await response.json().catch(() => ({}));
      return { ok: false as const, message: data.message || data.detail || 'Failed to start' };
    } catch {
      return { ok: false as const, message: 'Failed to start scheduled order monitoring' };
    } finally {
      setScheduledLoading(null);
    }
  };

  const stopScheduled = async () => {
    setScheduledLoading('stop');
    try {
      const response = await fetch(`${getApiUrl()}/stop_check_orders/`, {
        headers: { accept: 'application/json' },
      });
      if (response.ok || response.status === 400) {
        monitoringStore.setScheduledActive(false);
        return { ok: true as const };
      }
      const data = await response.json().catch(() => ({}));
      return { ok: false as const, message: data.message || data.detail || 'Failed to stop' };
    } catch {
      return { ok: false as const, message: 'Failed to stop scheduled order monitoring' };
    } finally {
      setScheduledLoading(null);
    }
  };

  const startGrabbers = () => {
    const controls = monitoringStore.getGrabberControls();
    if (!controls.size) {
      return { ok: false as const, message: 'Add a stock grabber first' };
    }

    setGrabberLoading('start');
    const idle = Array.from(controls.values()).find((c) => !c.getIsRunning());
    if (idle) {
      idle.start();
      setGrabberLoading(null);
      return { ok: true as const };
    }
    setGrabberLoading(null);
    return { ok: false as const, message: 'All grabbers are already running' };
  };

  const stopGrabbers = useCallback(async () => {
    setGrabberLoading('stop');
    try {
      const controls = monitoringStore.getGrabberControls();
      const running = Array.from(controls.values()).filter((c) => c.getIsRunning());

      if (running.length > 0) {
        await Promise.all(running.map((c) => Promise.resolve(c.stop())));
      } else {
        const response = await fetch(`${getApiUrl()}/stop_all_stock_grabbers/`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        });
        if (!response.ok) {
          const data = await response.json().catch(() => ({}));
          return { ok: false as const, message: data.detail || data.message || 'Failed to stop grabbers' };
        }
      }

      monitoringStore.clearGrabberRunning();
      return { ok: true as const };
    } catch {
      return { ok: false as const, message: 'Failed to stop stock grabbers' };
    } finally {
      setGrabberLoading(null);
    }
  }, []);

  const grabberIsActive = grabberActiveCount > 0;
  const hasGrabbers = grabberTotal > 0;

  return {
    scheduledActive,
    grabberActiveCount,
    grabberTotal,
    grabberCanStart,
    grabberIsActive,
    hasGrabbers,
    scheduledLoading,
    grabberLoading,
    startScheduled,
    stopScheduled,
    startGrabbers,
    stopGrabbers,
  };
};
