import { GrabberControls } from '../types/monitoring';
import { MonitorPhase, RemoteGrabberStatus } from '../types/monitoringStatus';

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

const notify = () => {
  listeners.forEach((listener) => listener());
};

export const monitoringStore = {
  getState: () => state,
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
  },
  patchGrabberStatus: (patch: { activeCount?: number; scanningCount?: number }) => {
    state.statusLoaded = true;
    if (patch.activeCount !== undefined) state.grabberActiveCount = patch.activeCount;
    if (patch.scanningCount !== undefined) state.grabberScanningCount = patch.scanningCount;
    notify();
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
