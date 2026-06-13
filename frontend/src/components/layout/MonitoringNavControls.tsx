import React from 'react';
import './MonitoringNavControls.css';
import { useMonitoringActions } from '../../hooks/useMonitoringActions';

const MonitoringNavControls: React.FC = () => {
  const {
    scheduledActive,
    grabberActiveCount,
    grabberTotal,
    grabberIsActive,
    hasGrabbers,
    canStartGrabber,
    canStopGrabber,
    canStartSchedule,
    canStopSchedule,
    scheduledLoading,
    grabberLoading,
    actionMessage,
    startScheduled,
    stopScheduled,
    startGrabbers,
    stopGrabbers,
  } = useMonitoringActions();

  return (
    <div className="monitoring-nav-controls">
      {actionMessage && (
        <span className="monitoring-nav-message" role="status">
          {actionMessage}
        </span>
      )}

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
            className={`monitoring-nav-btn play ${canStartSchedule ? 'is-enabled' : ''}`}
            onClick={() => { void startScheduled(); }}
            disabled={scheduledActive || scheduledLoading !== null}
            title={scheduledActive ? 'Monitoring is running' : 'Start scheduled order monitoring'}
            aria-label="Start scheduled order monitoring"
          >
            {scheduledLoading === 'start' ? '…' : '▶'}
          </button>
          <button
            type="button"
            className={`monitoring-nav-btn stop ${scheduledActive ? 'is-enabled' : 'is-available'}`}
            onClick={() => { void stopScheduled(); }}
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
            className={`monitoring-nav-btn play ${canStartGrabber ? 'is-enabled' : ''}`}
            onClick={() => { void startGrabbers(); }}
            disabled={!canStartGrabber || grabberLoading !== null}
            title={canStartGrabber ? 'Start stock grabber' : hasGrabbers ? 'All grabbers running' : 'Add a grabber first'}
            aria-label="Start stock grabber"
          >
            {grabberLoading === 'start' ? '…' : '▶'}
          </button>
          <button
            type="button"
            className={`monitoring-nav-btn stop ${grabberIsActive ? 'is-enabled' : 'is-available'}`}
            onClick={() => { void stopGrabbers(); }}
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
