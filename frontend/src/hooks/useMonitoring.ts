import { useCallback, useMemo } from 'react';
import { getApiUrl } from '../utils/api';
import { loadGrabbers, makeGrabberKey, StockGrabberInstance } from '../utils/grabberPersistence';
import { monitoringStore } from './monitoringStore';
import { getGrabberDisplay, getScheduleDisplay } from './monitoringSelectors';
import { syncMonitoringStatus } from './monitoringSync';
import { useMonitoringStore } from './useMonitoringStore';

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

export const useMonitoring = () => {
  const state = useMonitoringStore();

  const schedule = useMemo(
    () => getScheduleDisplay({
      active: state.scheduledActive,
      scanning: state.scheduledScanning,
      phase: state.scheduledPhase,
      statusMessage: state.scheduledStatusMessage,
      loading: state.scheduledLoading,
    }),
    [
      state.scheduledActive,
      state.scheduledScanning,
      state.scheduledPhase,
      state.scheduledStatusMessage,
      state.scheduledLoading,
    ],
  );

  const grabber = useMemo(
    () => getGrabberDisplay({
      activeCount: state.grabberActiveCount,
      scanningCount: state.grabberScanningCount,
      total: state.grabberTotal,
      loading: state.grabberLoading,
    }),
    [
      state.grabberActiveCount,
      state.grabberScanningCount,
      state.grabberTotal,
      state.grabberLoading,
    ],
  );

  const startScheduled = useCallback(async () => {
    monitoringStore.setScheduledLoading('start');
    monitoringStore.setActionMessage(null);
    monitoringStore.patchScheduledStatus({
      active: true,
      scanning: false,
      phase: 'waiting_hours',
      statusMessage: 'Armed — waiting for market',
    });
    try {
      const response = await fetch(`${getApiUrl()}/check_orders/`, {
        headers: { accept: 'application/json', 'Cache-Control': 'no-store' },
        cache: 'no-store',
      });
      const data = await response.json().catch(() => ({}));

      if (response.ok || String(data.message || '').includes('already running')) {
        void syncMonitoringStatus();
        return { ok: true as const };
      }

      const message = data.message || data.detail || 'Failed to start scheduled monitoring';
      monitoringStore.patchScheduledStatus({
        active: false,
        scanning: false,
        phase: 'stopped',
        statusMessage: '',
        startedAt: null,
      });
      monitoringStore.setActionMessage(message);
      void syncMonitoringStatus();
      return { ok: false as const, message };
    } catch {
      const message = 'Failed to start scheduled order monitoring';
      monitoringStore.patchScheduledStatus({
        active: false,
        scanning: false,
        phase: 'stopped',
        statusMessage: '',
        startedAt: null,
      });
      monitoringStore.setActionMessage(message);
      return { ok: false as const, message };
    } finally {
      monitoringStore.setScheduledLoading(null);
    }
  }, []);

  const stopScheduled = useCallback(async () => {
    monitoringStore.setScheduledLoading('stop');
    monitoringStore.setActionMessage(null);
    monitoringStore.patchScheduledStatus({
      active: false,
      scanning: false,
      phase: 'stopped',
      statusMessage: '',
      startedAt: null,
    });
    try {
      const response = await fetch(`${getApiUrl()}/stop_check_orders/`, {
        headers: { accept: 'application/json', 'Cache-Control': 'no-store' },
        cache: 'no-store',
      });

      if (response.ok) {
        void syncMonitoringStatus();
        return { ok: true as const };
      }

      const data = await response.json().catch(() => ({}));
      const message = data.message || data.detail || 'Failed to stop scheduled monitoring';
      monitoringStore.setActionMessage(message);
      void syncMonitoringStatus();
      return { ok: false as const, message };
    } catch {
      const message = 'Failed to stop scheduled order monitoring';
      monitoringStore.setActionMessage(message);
      return { ok: false as const, message };
    } finally {
      monitoringStore.setScheduledLoading(null);
    }
  }, []);

  const startGrabbers = useCallback(async () => {
    monitoringStore.setGrabberLoading('start');
    monitoringStore.setActionMessage(null);
    const previousActiveCount = monitoringStore.getState().grabberActiveCount;
    monitoringStore.patchGrabberStatus({
      activeCount: previousActiveCount + 1,
      scanningCount: 0,
    });

    try {
      const controls = monitoringStore.getGrabberControls();
      if (controls.size > 0) {
        const idle = Array.from(controls.values()).find((control) => !control.getIsRunning());
        if (idle) {
          idle.start();
          void syncMonitoringStatus();
          return { ok: true as const };
        }
      }

      const grabbers = loadGrabbers();
      if (!grabbers.length) {
        monitoringStore.patchGrabberStatus({ activeCount: previousActiveCount, scanningCount: 0 });
        const message = 'Add a stock grabber on the Stock Grabber tab first';
        monitoringStore.setActionMessage(message);
        return { ok: false as const, message };
      }

      const activeResult = await fetch(`${getApiUrl()}/active_stock_grabbers/`, {
        headers: { accept: 'application/json', 'Cache-Control': 'no-store' },
        cache: 'no-store',
      });
      const activeKeys = new Set<string>();
      if (activeResult.ok) {
        const payload = await activeResult.json().catch(() => ({ grabbers: [] }));
        (payload.grabbers || []).forEach((item: { client_id: string; stock_symbol: string }) => {
          activeKeys.add(makeGrabberKey(item.client_id, item.stock_symbol));
        });
      }

      const idleGrabber = grabbers.find(
        (item) => !activeKeys.has(makeGrabberKey(item.client_id, item.stock_symbol)),
      );

      if (!idleGrabber) {
        monitoringStore.patchGrabberStatus({ activeCount: previousActiveCount, scanningCount: 0 });
        const message = 'All grabbers are already running';
        monitoringStore.setActionMessage(message);
        return { ok: false as const, message };
      }

      const result = await startGrabberViaApi(idleGrabber);
      if (!result.ok) {
        monitoringStore.patchGrabberStatus({ activeCount: previousActiveCount, scanningCount: 0 });
        monitoringStore.setActionMessage(result.message || 'Failed to start grabber');
        void syncMonitoringStatus();
        return { ok: false as const, message: result.message };
      }

      void syncMonitoringStatus();
      return { ok: true as const };
    } finally {
      monitoringStore.setGrabberLoading(null);
    }
  }, []);

  const stopGrabbers = useCallback(async () => {
    monitoringStore.setGrabberLoading('stop');
    monitoringStore.setActionMessage(null);
    const previousActiveCount = monitoringStore.getState().grabberActiveCount;
    monitoringStore.patchGrabberStatus({ activeCount: 0, scanningCount: 0 });

    try {
      const controls = monitoringStore.getGrabberControls();
      const running = Array.from(controls.values()).filter((control) => control.getIsRunning());
      if (running.length > 0) {
        await Promise.all(running.map((control) => Promise.resolve(control.stop())));
      }

      const response = await fetch(`${getApiUrl()}/stop_all_stock_grabbers/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
        cache: 'no-store',
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        const message = data.detail || data.message || 'Failed to stop grabbers';
        monitoringStore.patchGrabberStatus({
          activeCount: previousActiveCount,
          scanningCount: 0,
        });
        monitoringStore.setActionMessage(message);
        void syncMonitoringStatus();
        return { ok: false as const, message };
      }

      void syncMonitoringStatus();
      return { ok: true as const };
    } catch {
      monitoringStore.patchGrabberStatus({
        activeCount: previousActiveCount,
        scanningCount: 0,
      });
      const message = 'Failed to stop stock grabbers';
      monitoringStore.setActionMessage(message);
      return { ok: false as const, message };
    } finally {
      monitoringStore.setGrabberLoading(null);
    }
  }, []);

  return {
    state,
    schedule,
    grabber,
    startScheduled,
    stopScheduled,
    startGrabbers,
    stopGrabbers,
  };
};
