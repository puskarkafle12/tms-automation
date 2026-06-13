import { GrabberControls } from '../types/monitoring';
import { MonitorPhase, RemoteGrabberStatus } from '../types/monitoringStatus';
import { loadGrabbers } from '../utils/grabberPersistence';
import { loadMonitoringSnapshot, saveMonitoringSnapshot } from '../utils/monitoringPersistence';

type Listener = () => void;
type GrabberControlsGetter = () => Map<string, GrabberControls>;

interface MonitoringStoreState {
  statusLoaded: boolean;
  scheduledActive: boolean;
  scheduledScanning: boolean;
  scheduledPhase: MonitorPhase;
  scheduledStatusMessage: string;
  scheduledStartedAt: string | null;
  grabberActiveCount: number;
  grabberScanningCount: number;
  grabberTotal: number;
  grabberCanStart: boolean;
  remoteGrabbers: RemoteGrabberStatus[];
  scheduledLoading: 'start' | 'stop' | null;
  grabberLoading: 'start' | 'stop' | null;
  actionMessage: string | null;
}

const state: MonitoringStoreState = {
  statusLoaded: true,
  scheduledActive: false,
  scheduledScanning: false,
  scheduledPhase: 'stopped',
  scheduledStatusMessage: '',
  scheduledStartedAt: null,
  grabberActiveCount: 0,
  grabberScanningCount: 0,
  grabberTotal: 0,
  grabberCanStart: false,
  remoteGrabbers: [],
  scheduledLoading: null,
  grabberLoading: null,
  actionMessage: null,
};

let grabberControlsGetter: GrabberControlsGetter | null = null;

const listeners = new Set<Listener>();

let snapshotCache: MonitoringStoreState | null = null;

const cloneState = (): MonitoringStoreState => ({
  ...state,
  remoteGrabbers: [...state.remoteGrabbers],
});

const notify = () => {
  snapshotCache = cloneState();
  listeners.forEach((listener) => listener());
};

const persistSnapshot = () => {
  saveMonitoringSnapshot({
    savedAt: new Date().toISOString(),
    scheduledActive: state.scheduledActive,
    scheduledScanning: state.scheduledScanning,
    scheduledPhase: state.scheduledPhase,
    scheduledStatusMessage: state.scheduledStatusMessage,
    scheduledStartedAt: state.scheduledStartedAt,
    grabberActiveCount: state.grabberActiveCount,
    grabberScanningCount: state.grabberScanningCount,
    grabberTotal: state.grabberTotal,
  });
};

const hydrateFromCache = () => {
  const cached = loadMonitoringSnapshot();
  const grabberTotal = Math.max(loadGrabbers().length, cached?.grabberTotal ?? 0);

  if (cached) {
    state.scheduledActive = cached.scheduledActive;
    state.scheduledScanning = cached.scheduledScanning;
    state.scheduledPhase = cached.scheduledPhase;
    state.scheduledStatusMessage = cached.scheduledStatusMessage;
    state.scheduledStartedAt = cached.scheduledStartedAt;
    state.grabberActiveCount = cached.grabberActiveCount;
    state.grabberScanningCount = cached.grabberScanningCount;
  }

  state.grabberTotal = grabberTotal;
  state.grabberCanStart = grabberTotal > 0;
  state.statusLoaded = true;
  snapshotCache = cloneState();
};

hydrateFromCache();

export const monitoringStore = {
  getState: () => state,
  getSnapshot: () => snapshotCache ?? cloneState(),
  subscribe: (listener: Listener) => {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  },
  applyBackendStatus: (payload: {
    scheduledActive: boolean;
    scheduledScanning: boolean;
    scheduledPhase: MonitorPhase;
    scheduledStatusMessage: string;
    scheduledStartedAt: string | null;
    grabberActiveCount: number;
    grabberScanningCount: number;
    grabberTotal: number;
    remoteGrabbers: RemoteGrabberStatus[];
  }) => {
    state.statusLoaded = true;
    state.scheduledActive = payload.scheduledActive;
    state.scheduledScanning = payload.scheduledScanning;
    state.scheduledPhase = payload.scheduledPhase;
    state.scheduledStatusMessage = payload.scheduledStatusMessage;
    state.scheduledStartedAt = payload.scheduledStartedAt;
    state.grabberActiveCount = payload.grabberActiveCount;
    state.grabberScanningCount = payload.grabberScanningCount;
    state.grabberTotal = payload.grabberTotal;
    state.grabberCanStart = payload.grabberTotal > 0;
    state.remoteGrabbers = payload.remoteGrabbers;
    notify();
    persistSnapshot();
  },
  patchScheduledStatus: (patch: {
    active?: boolean;
    scanning?: boolean;
    phase?: MonitorPhase;
    statusMessage?: string;
    startedAt?: string | null;
  }) => {
    state.statusLoaded = true;
    if (patch.active !== undefined) state.scheduledActive = patch.active;
    if (patch.scanning !== undefined) state.scheduledScanning = patch.scanning;
    if (patch.phase !== undefined) state.scheduledPhase = patch.phase;
    if (patch.statusMessage !== undefined) state.scheduledStatusMessage = patch.statusMessage;
    if (patch.startedAt !== undefined) state.scheduledStartedAt = patch.startedAt;
    if (patch.active && !state.scheduledStartedAt) {
      state.scheduledStartedAt = new Date().toISOString();
    }
    notify();
    persistSnapshot();
  },
  patchGrabberStatus: (patch: { activeCount?: number; scanningCount?: number }) => {
    state.statusLoaded = true;
    if (patch.activeCount !== undefined) state.grabberActiveCount = patch.activeCount;
    if (patch.scanningCount !== undefined) state.grabberScanningCount = patch.scanningCount;
    notify();
    persistSnapshot();
  },
  setStatusLoaded: (loaded: boolean) => {
    if (state.statusLoaded === loaded) {
      return;
    }
    state.statusLoaded = loaded;
    notify();
  },
  setGrabberTotal: (total: number) => {
    const canStart = total > 0;
    if (state.grabberTotal === total && state.grabberCanStart === canStart) {
      return;
    }
    state.grabberTotal = total;
    state.grabberCanStart = canStart;
    notify();
    persistSnapshot();
  },
  setScheduledLoading: (loading: 'start' | 'stop' | null) => {
    if (state.scheduledLoading === loading) {
      return;
    }
    state.scheduledLoading = loading;
    notify();
  },
  setGrabberLoading: (loading: 'start' | 'stop' | null) => {
    if (state.grabberLoading === loading) {
      return;
    }
    state.grabberLoading = loading;
    notify();
  },
  setActionMessage: (message: string | null) => {
    if (state.actionMessage === message) {
      return;
    }
    state.actionMessage = message;
    notify();
  },
  setGrabberControlsGetter: (getter: GrabberControlsGetter | null) => {
    grabberControlsGetter = getter;
  },
  getGrabberControls: () => grabberControlsGetter?.() ?? new Map<string, GrabberControls>(),
};
