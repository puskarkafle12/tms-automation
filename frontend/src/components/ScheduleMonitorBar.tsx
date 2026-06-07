import React from 'react';
import './PageMonitorBar.css';
import { useMonitoringActions } from '../hooks/useMonitoringActions';

const ScheduleMonitorBar: React.FC = () => {
  const {
    scheduledActive,
    scheduledLoading,
    startScheduled,
    stopScheduled,
  } = useMonitoringActions();

  return (
    <div className={`page-monitor-bar scheduled ${scheduledActive ? 'active' : ''}`}>
      <div className="page-monitor-bar-info">
        <span className="page-monitor-bar-icon" aria-hidden="true">📅</span>
        <div>
          <h3 className="page-monitor-bar-title">Scheduled Order Monitor</h3>
          <p className="page-monitor-bar-desc">
            {scheduledActive
              ? 'Watching queued orders — executes when price conditions are met.'
              : 'Stopped — start monitoring to execute queued orders automatically.'}
          </p>
        </div>
      </div>
      <div className="page-monitor-bar-actions">
        <span className={`page-monitor-bar-badge ${scheduledActive ? 'active' : 'idle'}`}>
          <span className="dot" />
          {scheduledActive ? 'Active' : 'Stopped'}
        </span>
        <button
          type="button"
          className={`page-monitor-btn play ${!scheduledActive ? 'is-enabled' : ''}`}
          onClick={startScheduled}
          disabled={scheduledActive || scheduledLoading !== null}
          title={scheduledActive ? 'Monitoring is running' : 'Start monitoring'}
          aria-pressed={scheduledActive}
        >
          {scheduledLoading === 'start' ? '…' : '▶'}
        </button>
        <button
          type="button"
          className={`page-monitor-btn stop ${scheduledActive ? 'is-enabled' : ''}`}
          onClick={stopScheduled}
          disabled={!scheduledActive || scheduledLoading !== null}
          title={!scheduledActive ? 'Monitoring is stopped' : 'Stop monitoring'}
          aria-pressed={!scheduledActive}
        >
          {scheduledLoading === 'stop' ? '…' : '⏹'}
        </button>
      </div>
    </div>
  );
};

export default ScheduleMonitorBar;
