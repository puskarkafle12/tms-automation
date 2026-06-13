import { GrabberControls } from '../types/monitoring';

type Listener = () => void;
type GrabberControlsGetter = () => Map<string, GrabberControls>;

interface MonitoringStoreState {
  scheduledActive: boolean;
  grabberActiveCount: number;
  grabberTotal: number;
  grabberCanStart: boolean;
  scheduledLoading: 'start' | 'stop' | null;
  grabberLoading: 'start' | 'stop' | null;
  actionMessage: string | null;
}

const state: MonitoringStoreState = {
  scheduledActive: false,
  grabberActiveCount: 0,
  grabberTotal: 0,
  grabberCanStart: false,
  scheduledLoading: null,
  grabberLoading: null,
  actionMessage: null,
};

const runningGrabberIds = new Set<string>();
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
  setScheduledActive: (active: boolean) => {
    if (state.scheduledActive === active) {
      return;
    }
    state.scheduledActive = active;
    notify();
  },
  setGrabberStats: (active: number, total: number) => {
    const canStart = total > 0;
    if (
      state.grabberActiveCount === active
      && state.grabberTotal === total
      && state.grabberCanStart === canStart
    ) {
      return;
    }
    state.grabberActiveCount = active;
    state.grabberTotal = total;
    state.grabberCanStart = canStart;
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
  setGrabberRunning: (id: string, running: boolean) => {
    const alreadyRunning = runningGrabberIds.has(id);
    if (running === alreadyRunning) {
      return;
    }
    if (running) {
      runningGrabberIds.add(id);
    } else {
      runningGrabberIds.delete(id);
    }
    state.grabberActiveCount = runningGrabberIds.size;
    notify();
  },
  clearGrabberRunning: () => {
    runningGrabberIds.clear();
    state.grabberActiveCount = 0;
    notify();
  },
  setGrabberCanStart: (canStart: boolean) => {
    if (state.grabberCanStart === canStart) {
      return;
    }
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
    notify();
  },
  getGrabberControls: () => grabberControlsGetter?.() ?? new Map<string, GrabberControls>(),
  syncActiveFromControls: () => {
    const controls = grabberControlsGetter?.() ?? new Map<string, GrabberControls>();
    let active = 0;
    controls.forEach((control) => {
      if (control.getIsRunning()) {
        active += 1;
      }
    });
    if (active !== state.grabberActiveCount) {
      state.grabberActiveCount = active;
      notify();
    }
    return active;
  },
  hasRunningGrabbers: () => {
    if (state.grabberActiveCount > 0) {
      return true;
    }
    const controls = grabberControlsGetter?.() ?? new Map<string, GrabberControls>();
    return Array.from(controls.values()).some((control) => control.getIsRunning());
  },
};
