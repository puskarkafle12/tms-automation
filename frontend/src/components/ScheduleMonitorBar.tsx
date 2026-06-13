import React, { useEffect, useState } from 'react';
import './PageMonitorBar.css';
import { useMonitoring } from '../hooks/useMonitoring';
import { formatMonitorDuration } from '../utils/formatDuration';

const ScheduleMonitorBar: React.FC = () => {
  const { state, schedule, startScheduled, stopScheduled } = useMonitoring();
  const [runtime, setRuntime] = useState('');

  useEffect(() => {
    const updateRuntime = () => {
      setRuntime(formatMonitorDuration(state.scheduledStartedAt));
    };
    updateRuntime();
    const timer = window.setInterval(updateRuntime, 30000);
    return () => window.clearInterval(timer);
  }, [state.scheduledStartedAt]);

  return (
    <div className={`page-monitor-bar scheduled ${state.scheduledActive ? 'active' : ''}`}>
      <div className="page-monitor-bar-info">
        <span className="page-monitor-bar-icon" aria-hidden="true">📅</span>
        <div>
          <h3 className="page-monitor-bar-title">Scheduled Order Monitor</h3>
          <p className="page-monitor-bar-desc">{schedule.description}</p>
          {state.scheduledActive && state.scheduledStartedAt && (
            <p className="page-monitor-runtime">Armed for {runtime || '<1m'}</p>
          )}
        </div>
      </div>
      <div className="page-monitor-bar-actions">
        <span className={`page-monitor-bar-badge ${schedule.badgeClass}`}>
          <span className="dot" />
          {schedule.badgeLabel}
        </span>
        <button
          type="button"
          className={`page-monitor-btn play ${schedule.canStart ? 'is-enabled' : ''}`}
          onClick={() => { void startScheduled(); }}
          disabled={!schedule.canStart}
          title={state.scheduledActive ? 'Scheduler is armed' : 'Arm scheduler'}
        >
          {state.scheduledLoading === 'start' ? '…' : '▶'}
        </button>
        <button
          type="button"
          className={`page-monitor-btn stop ${schedule.canStop ? 'is-enabled' : 'is-available'}`}
          onClick={() => { void stopScheduled(); }}
          disabled={!schedule.canStop}
          title="Stop scheduler"
        >
          {state.scheduledLoading === 'stop' ? '…' : '⏹'}
        </button>
      </div>
    </div>
  );
};

export default ScheduleMonitorBar;
