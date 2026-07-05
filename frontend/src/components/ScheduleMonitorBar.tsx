import React from 'react';
import './PageMonitorBar.css';
import { useMonitoring } from '../hooks/useMonitoring';
import { formatMonitorDuration } from '../utils/formatDuration';

const ScheduleMonitorBar: React.FC = () => {
  const { state, schedule, startScheduled, stopScheduled } = useMonitoring();
  const [runtime, setRuntime] = React.useState('');
  const showControls = state.scheduledStatusMessage.includes('Test mode');
  const canStart = showControls && !state.scheduledActive && state.scheduledLoading !== 'start';
  const canStop = showControls && state.scheduledActive && state.scheduledLoading !== 'stop';

  React.useEffect(() => {
    const updateRuntime = () => {
      setRuntime(formatMonitorDuration(state.scheduledStartedAt));
    };
    updateRuntime();
    const timer = window.setInterval(updateRuntime, 30000);
    return () => window.clearInterval(timer);
  }, [state.scheduledStartedAt]);

  return (
    <div className={`page-monitor-bar scheduled ${schedule.badgeClass !== 'idle' ? schedule.badgeClass : ''}`}>
      <div className="page-monitor-bar-info">
        <span className="page-monitor-bar-icon" aria-hidden="true">📅</span>
        <div>
          <h3 className="page-monitor-bar-title">Scheduled Order Monitor</h3>
          <p className="page-monitor-bar-desc">{schedule.description}</p>
          {state.scheduledActive && state.scheduledStartedAt && (
            <p className="page-monitor-runtime">Running for {runtime || '<1m'}</p>
          )}
        </div>
      </div>
      <div className="page-monitor-bar-actions">
        <span className={`page-monitor-bar-badge ${schedule.badgeClass}`}>
          <span className="dot" />
          {schedule.badgeLabel}
        </span>
        {showControls && (
          <>
            <button
              type="button"
              className={`page-monitor-btn play ${canStart ? 'is-enabled' : ''}`}
              onClick={() => { void startScheduled(); }}
              disabled={!canStart}
              title="Start scheduled monitoring"
            >
              ▶
            </button>
            <button
              type="button"
              className={`page-monitor-btn stop ${canStop ? 'is-enabled' : 'is-available'}`}
              onClick={() => { void stopScheduled(); }}
              disabled={!canStop}
              title="Stop scheduled monitoring"
            >
              ⏹
            </button>
          </>
        )}
      </div>
    </div>
  );
};

export default ScheduleMonitorBar;
