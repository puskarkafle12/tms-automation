import { MonitorPhase } from '../types/monitoringStatus';

export interface ScheduleDisplay {
  navLabel: string;
  badgeLabel: string;
  badgeClass: 'active' | 'waiting' | 'idle';
  description: string;
  canStart: boolean;
  canStop: boolean;
}

export interface GrabberDisplay {
  navLabel: string;
  badgeLabel: string;
  badgeClass: 'active' | 'waiting' | 'ready' | 'idle';
  description: string;
  canStart: boolean;
  canStop: boolean;
}

const SCHEDULE_PHASE_LABELS: Record<string, string> = {
  stopped: 'Stopped',
  waiting_hours: 'Waiting',
  waiting_session: 'Waiting',
  active: 'Scanning',
  armed: 'Armed',
};

export const isScheduleAutoWaiting = (phase: MonitorPhase | string): boolean =>
  phase === 'waiting_hours' || phase === 'waiting_session';

export const getScheduleNavLabel = (active: boolean, phase: MonitorPhase | string): string => {
  if (phase === 'active') {
    return 'scanning';
  }
  if (isScheduleAutoWaiting(phase)) {
    return 'waiting';
  }
  if (active || phase === 'armed') {
    return 'armed';
  }
  return 'stopped';
};

export const getScheduleDisplay = (input: {
  active: boolean;
  scanning: boolean;
  phase: MonitorPhase | string;
  statusMessage: string;
  loading: 'start' | 'stop' | null;
}): ScheduleDisplay => {
  const navLabel = getScheduleNavLabel(input.active, input.phase);
  const autoWaiting = isScheduleAutoWaiting(input.phase);
  const showAsLive = input.active || autoWaiting || input.phase === 'armed';
  const badgeLabel = showAsLive
    ? (SCHEDULE_PHASE_LABELS[input.phase] || 'Waiting')
    : 'Stopped';
  const badgeClass: ScheduleDisplay['badgeClass'] = input.scanning
    ? 'active'
    : showAsLive
      ? (input.phase === 'active' ? 'active' : 'waiting')
      : 'idle';

  const defaultDescription = autoWaiting
    ? (input.phase === 'waiting_session'
      ? 'Log in to a TMS account — the monitor starts automatically during market hours.'
      : 'Waiting for Nepal market to open — the monitor will start automatically.')
    : 'Starts automatically when market opens and a TMS account is logged in.';

  return {
    navLabel,
    badgeLabel,
    badgeClass,
    description: input.statusMessage || (input.active
      ? 'Runs automatically during Nepal market hours.'
      : defaultDescription),
    canStart: false,
    canStop: false,
  };
};

export const getGrabberNavLabel = (activeCount: number, scanningCount: number): string => {
  if (activeCount <= 0) {
    return 'idle';
  }
  if (scanningCount > 0) {
    return 'scanning';
  }
  return 'waiting';
};

export const getGrabberDisplay = (input: {
  activeCount: number;
  scanningCount: number;
  total: number;
  loading: 'start' | 'stop' | null;
}): GrabberDisplay => {
  const hasGrabbers = input.total > 0;
  const isActive = input.activeCount > 0;
  const navLabel = getGrabberNavLabel(input.activeCount, input.scanningCount);
  const badgeLabel = input.scanningCount > 0
    ? 'Scanning'
    : isActive
      ? 'Waiting'
      : hasGrabbers
        ? 'Ready'
        : 'Idle';
  const badgeClass: GrabberDisplay['badgeClass'] = input.scanningCount > 0
    ? 'active'
    : isActive
      ? 'waiting'
      : hasGrabbers
        ? 'ready'
        : 'idle';

  const waitingCount = Math.max(0, input.activeCount - input.scanningCount);

  return {
    navLabel,
    badgeLabel,
    badgeClass,
    description: input.scanningCount > 0
      ? `Scanning ${input.scanningCount} of ${input.activeCount} grabber${input.activeCount !== 1 ? 's' : ''} at 3% high price.`
      : isActive
        ? `${input.activeCount} grabber${input.activeCount !== 1 ? 's' : ''} armed${waitingCount > 0 ? ' — waiting for market to open' : ''}.`
        : hasGrabbers
          ? `${input.total} grabber${input.total !== 1 ? 's' : ''} ready — press play to arm.`
          : 'Add a grabber below, then arm it with play.',
    canStart: hasGrabbers && input.activeCount < input.total && input.loading !== 'start',
    canStop: isActive && input.loading !== 'stop',
  };
};
