import { useMonitoring } from './useMonitoring';

/** @deprecated Prefer useMonitoring() for shared state + actions */
export const useMonitoringActions = () => {
  const monitoring = useMonitoring();
  return {
    statusLoaded: monitoring.state.statusLoaded,
    scheduledActive: monitoring.state.scheduledActive,
    grabberActiveCount: monitoring.state.grabberActiveCount,
    grabberTotal: monitoring.state.grabberTotal,
    grabberCanStart: monitoring.state.grabberCanStart,
    grabberIsActive: monitoring.state.grabberActiveCount > 0,
    hasGrabbers: monitoring.state.grabberTotal > 0,
    canStartGrabber: monitoring.grabber.canStart,
    canStopGrabber: monitoring.grabber.canStop,
    canStartSchedule: monitoring.schedule.canStart,
    canStopSchedule: monitoring.schedule.canStop,
    scheduledLoading: monitoring.state.scheduledLoading,
    grabberLoading: monitoring.state.grabberLoading,
    actionMessage: monitoring.state.actionMessage,
    startScheduled: monitoring.startScheduled,
    stopScheduled: monitoring.stopScheduled,
    startGrabbers: monitoring.startGrabbers,
    stopGrabbers: monitoring.stopGrabbers,
  };
};
