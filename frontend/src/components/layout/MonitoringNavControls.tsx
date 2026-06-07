import React from 'react';
import './MonitoringNavControls.css';
import { useMonitoringActions } from '../../hooks/useMonitoringActions';

const MonitoringNavControls: React.FC = () => {
  const {
    scheduledActive,
    grabberActiveCount,
    grabberTotal,
    grabberCanStart,
    grabberIsActive,
    hasGrabbers,
    scheduledLoading,
    grabberLoading,
    startScheduled,
    stopScheduled,
    startGrabbers,
    stopGrabbers,
  } = useMonitoringActions();

  return (
    <div className="monitoring-nav-controls">
      <div className={`monitoring-nav-chip scheduled ${scheduledActive ? 'active' : ''}`}>
        <span className="monitoring-nav-chip-icon" aria-hidden="true">📅</span>
        <div className="monitoring-nav-chip-body">
          <span className="monitoring-nav-chip-label">Schedule</span>
          <span className="monitoring-nav-chip-status">
            <span className="monitoring-nav-chip-dot" />
            {scheduledActive ? 'Active' : 'Stopped'}
          </span>
        </div>
        <div className="monitoring-nav-chip-actions">
          <button
            type="button"
            className="monitoring-nav-btn play"
            onClick={startScheduled}
            disabled={scheduledActive || scheduledLoading !== null}
            title="Start scheduled order monitoring"
            aria-label="Start scheduled order monitoring"
          >
            {scheduledLoading === 'start' ? '…' : '▶'}
          </button>
          <button
            type="button"
            className="monitoring-nav-btn stop"
            onClick={stopScheduled}
            disabled={scheduledLoading !== null}
            title="Stop scheduled order monitoring"
            aria-label="Stop scheduled order monitoring"
          >
            {scheduledLoading === 'stop' ? '…' : '⏹'}
          </button>
        </div>
      </div>

      <div className="monitoring-nav-divider" aria-hidden="true" />

      <div className={`monitoring-nav-chip grabber ${grabberIsActive ? 'active' : hasGrabbers ? 'ready' : ''}`}>
        <span className="monitoring-nav-chip-icon" aria-hidden="true">⚡</span>
        <div className="monitoring-nav-chip-body">
          <span className="monitoring-nav-chip-label">Grabber</span>
          <span className="monitoring-nav-chip-status">
            <span className="monitoring-nav-chip-dot" />
            {grabberIsActive
              ? `Scanning ${grabberActiveCount}/${grabberTotal}`
              : hasGrabbers
                ? `Ready ${grabberTotal}`
                : 'Idle'}
          </span>
        </div>
        <div className="monitoring-nav-chip-actions">
          <button
            type="button"
            className="monitoring-nav-btn play"
            onClick={startGrabbers}
            disabled={
              !grabberCanStart
              || (grabberTotal > 0 && grabberActiveCount >= grabberTotal)
              || grabberLoading !== null
            }
            title="Start stock grabber"
            aria-label="Start stock grabber"
          >
            {grabberLoading === 'start' ? '…' : '▶'}
          </button>
          <button
            type="button"
            className="monitoring-nav-btn stop"
            onClick={stopGrabbers}
            disabled={grabberLoading !== null}
            title="Stop all stock grabbers"
            aria-label="Stop all stock grabbers"
          >
            {grabberLoading === 'stop' ? '…' : '⏹'}
          </button>
        </div>
      </div>
    </div>
  );
};

export default MonitoringNavControls;
