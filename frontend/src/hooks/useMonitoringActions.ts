import { useCallback } from 'react';
import { loadGrabbers, makeGrabberKey, StockGrabberInstance } from '../utils/grabberPersistence';
import { monitoringStore } from './monitoringStore';
import { syncMonitoringStatus } from './monitoringSync';
import { useMonitoringStore } from './useMonitoringStore';

const getApiUrl = () => localStorage.getItem('apiUrl') || window.location.origin;

const startGrabberViaApi = async (grabber: StockGrabberInstance): Promise<{ ok: boolean; message?: string }> => {
  try {
    const response = await fetch(`${getApiUrl()}/stock_grabber/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        client_id: grabber.client_id,
        stock_symbol: grabber.stock_symbol,
        order_quantity: grabber.order_quantity ?? 10,
        request_per_sec: grabber.request_per_sec ?? 3,
        max_order_limit: 4,
        resume_scan_count: grabber.scanCount ?? 0,
        resume_stable_rate: grabber.stableRate ?? null,
      }),
    });

    if (response.ok) {
      return { ok: true };
    }

    const data = await response.json().catch(() => ({}));
    return { ok: false, message: data.detail || data.message || 'Failed to start grabber' };
  } catch {
    return { ok: false, message: 'Failed to start stock grabber' };
  }
};

export const useMonitoringActions = () => {
  const {
    scheduledActive,
    grabberActiveCount,
    grabberTotal,
    grabberCanStart,
    scheduledLoading,
    grabberLoading,
    actionMessage,
  } = useMonitoringStore();

  const startScheduled = async () => {
    monitoringStore.setScheduledLoading('start');
    monitoringStore.setActionMessage(null);
    try {
      const response = await fetch(`${getApiUrl()}/check_orders/`, {
        headers: { accept: 'application/json' },
      });
      const data = await response.json().catch(() => ({}));

      if (response.ok || String(data.message || '').includes('already running')) {
        monitoringStore.setScheduledActive(true);
        await syncMonitoringStatus();
        return { ok: true as const };
      }

      const message = data.message || data.detail || 'Failed to start scheduled monitoring';
      monitoringStore.setActionMessage(message);
      return { ok: false as const, message };
    } catch {
      const message = 'Failed to start scheduled order monitoring';
      monitoringStore.setActionMessage(message);
      return { ok: false as const, message };
    } finally {
      monitoringStore.setScheduledLoading(null);
    }
  };

  const stopScheduled = async () => {
    monitoringStore.setScheduledLoading('stop');
    monitoringStore.setActionMessage(null);
    monitoringStore.setScheduledActive(false);
    try {
      const response = await fetch(`${getApiUrl()}/stop_check_orders/`, {
        headers: { accept: 'application/json' },
      });

      if (response.ok) {
        await syncMonitoringStatus();
        return { ok: true as const };
      }

      const data = await response.json().catch(() => ({}));
      const message = data.message || data.detail || 'Failed to stop scheduled monitoring';
      monitoringStore.setActionMessage(message);
      await syncMonitoringStatus();
      return { ok: false as const, message };
    } catch {
      const message = 'Failed to stop scheduled order monitoring';
      monitoringStore.setActionMessage(message);
      return { ok: false as const, message };
    } finally {
      monitoringStore.setScheduledLoading(null);
    }
  };

  const startGrabbers = async () => {
    monitoringStore.setGrabberLoading('start');
    monitoringStore.setActionMessage(null);

    try {
      const controls = monitoringStore.getGrabberControls();
      if (controls.size > 0) {
        const idle = Array.from(controls.values()).find((control) => !control.getIsRunning());
        if (idle) {
          idle.start();
          await syncMonitoringStatus();
          return { ok: true as const };
        }
      }

      const grabbers = loadGrabbers();
      if (!grabbers.length) {
        const message = 'Add a stock grabber on the Stock Grabber tab first';
        monitoringStore.setActionMessage(message);
        return { ok: false as const, message };
      }

      await syncMonitoringStatus();
      const activeResult = await fetch(`${getApiUrl()}/active_stock_grabbers/`);
      const activeKeys = new Set<string>();
      if (activeResult.ok) {
        const payload = await activeResult.json().catch(() => ({ grabbers: [] }));
        (payload.grabbers || []).forEach((grabber: { client_id: string; stock_symbol: string }) => {
          activeKeys.add(makeGrabberKey(grabber.client_id, grabber.stock_symbol));
        });
      }

      const idleGrabber = grabbers.find(
        (grabber) => !activeKeys.has(makeGrabberKey(grabber.client_id, grabber.stock_symbol)),
      );

      if (!idleGrabber) {
        const message = 'All grabbers are already running';
        monitoringStore.setActionMessage(message);
        return { ok: false as const, message };
      }

      const result = await startGrabberViaApi(idleGrabber);
      if (!result.ok) {
        monitoringStore.setActionMessage(result.message || 'Failed to start grabber');
        return { ok: false as const, message: result.message };
      }

      await syncMonitoringStatus();
      return { ok: true as const };
    } finally {
      monitoringStore.setGrabberLoading(null);
    }
  };

  const stopGrabbers = useCallback(async () => {
    monitoringStore.setGrabberLoading('stop');
    monitoringStore.setActionMessage(null);
    monitoringStore.clearGrabberRunning();

    try {
      const controls = monitoringStore.getGrabberControls();
      const running = Array.from(controls.values()).filter((control) => control.getIsRunning());
      if (running.length > 0) {
        await Promise.all(running.map((control) => Promise.resolve(control.stop())));
      }

      const response = await fetch(`${getApiUrl()}/stop_all_stock_grabbers/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        const message = data.detail || data.message || 'Failed to stop grabbers';
        monitoringStore.setActionMessage(message);
        await syncMonitoringStatus();
        return { ok: false as const, message };
      }

      await syncMonitoringStatus();
      return { ok: true as const };
    } catch {
      const message = 'Failed to stop stock grabbers';
      monitoringStore.setActionMessage(message);
      return { ok: false as const, message };
    } finally {
      monitoringStore.setGrabberLoading(null);
    }
  }, []);

  const grabberIsActive = grabberActiveCount > 0;
  const hasGrabbers = grabberTotal > 0;
  const canStartGrabber = !grabberIsActive && grabberCanStart && grabberActiveCount < grabberTotal;
  const canStopGrabber = true;
  const canStartSchedule = !scheduledActive;
  const canStopSchedule = true;

  return {
    scheduledActive,
    grabberActiveCount,
    grabberTotal,
    grabberCanStart,
    grabberIsActive,
    hasGrabbers,
    canStartGrabber,
    canStopGrabber,
    canStartSchedule,
    canStopSchedule,
    scheduledLoading,
    grabberLoading,
    actionMessage,
    startScheduled,
    stopScheduled,
    startGrabbers,
    stopGrabbers,
  };
};
