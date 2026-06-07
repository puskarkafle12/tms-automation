import { GrabberControls } from '../types/monitoring';

type Listener = () => void;
type GrabberControlsGetter = () => Map<string, GrabberControls>;

interface MonitoringStoreState {
  scheduledActive: boolean;
  grabberActiveCount: number;
  grabberTotal: number;
  grabberCanStart: boolean;
}

const state: MonitoringStoreState = {
  scheduledActive: false,
  grabberActiveCount: 0,
  grabberTotal: 0,
  grabberCanStart: false,
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
    state.scheduledActive = active;
    notify();
  },
  setGrabberStats: (active: number, total: number) => {
    state.grabberActiveCount = active;
    state.grabberTotal = total;
    notify();
  },
  setGrabberTotal: (total: number) => {
    state.grabberTotal = total;
    state.grabberCanStart = total > 0;
    notify();
  },
  setGrabberRunning: (id: string, running: boolean) => {
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
    state.grabberCanStart = canStart;
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
