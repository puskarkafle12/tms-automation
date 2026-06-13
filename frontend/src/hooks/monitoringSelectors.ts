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

export const getScheduleNavLabel = (active: boolean, phase: MonitorPhase | string): string => {
  if (!active) {
    return 'stopped';
  }
  if (phase === 'active') {
    return 'scanning';
  }
  if (phase === 'waiting_hours' || phase === 'waiting_session') {
    return 'waiting';
  }
  return 'armed';
};

export const getScheduleDisplay = (input: {
  active: boolean;
  scanning: boolean;
  phase: MonitorPhase | string;
  statusMessage: string;
  loading: 'start' | 'stop' | null;
}): ScheduleDisplay => {
  const navLabel = getScheduleNavLabel(input.active, input.phase);
  const badgeLabel = input.active
    ? (SCHEDULE_PHASE_LABELS[input.phase] || 'Armed')
    : 'Stopped';
  const badgeClass: ScheduleDisplay['badgeClass'] = input.scanning
    ? 'active'
    : input.active
      ? 'waiting'
      : 'idle';

  return {
    navLabel,
    badgeLabel,
    badgeClass,
    description: input.active
      ? input.statusMessage || 'Armed — will scan and execute when market is live.'
      : 'Stopped — press play to arm the scheduler. It waits for market hours and TMS session.',
    canStart: !input.active && input.loading !== 'start',
    canStop: input.active && input.loading !== 'stop',
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
      ? `Scanning ${input.scanningCount} of ${input.activeCount} grabber${input.activeCount !== 1 ? 's' : ''} at 2% high price.`
      : isActive
        ? `${input.activeCount} grabber${input.activeCount !== 1 ? 's' : ''} armed${waitingCount > 0 ? ' — waiting for market to open' : ''}.`
        : hasGrabbers
          ? `${input.total} grabber${input.total !== 1 ? 's' : ''} ready — press play to arm.`
          : 'Add a grabber below, then arm it with play.',
    canStart: hasGrabbers && input.activeCount < input.total && input.loading !== 'start',
    canStop: isActive && input.loading !== 'stop',
  };
};
