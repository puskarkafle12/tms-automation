import React from 'react';
import './MonitoringNavControls.css';
import { useMonitoring } from '../../hooks/useMonitoring';

const MonitoringNavControls: React.FC = () => {
  const {
    state,
    schedule,
    grabber,
    startGrabbers,
    stopGrabbers,
  } = useMonitoring();

  return (
    <div className="monitoring-nav-controls">
      {state.actionMessage && (
        <span className="monitoring-nav-message" role="status">
          {state.actionMessage}
        </span>
      )}

      <div className={`monitoring-nav-chip scheduled ${state.scheduledActive ? (schedule.badgeClass === 'active' ? 'active' : 'waiting') : ''}`}>
        <span className="monitoring-nav-chip-icon" aria-hidden="true">📅</span>
        <div className="monitoring-nav-chip-body">
          <span className="monitoring-nav-chip-label">Schedule</span>
          <span className="monitoring-nav-chip-status">
            <span className="monitoring-nav-chip-dot" />
            {schedule.navLabel}
          </span>
        </div>
      </div>

      <div className="monitoring-nav-divider" aria-hidden="true" />

      <div className={`monitoring-nav-chip grabber ${state.grabberActiveCount > 0 ? (grabber.badgeClass === 'active' ? 'active' : 'waiting') : state.grabberTotal > 0 ? 'ready' : ''}`}>
        <span className="monitoring-nav-chip-icon" aria-hidden="true">⚡</span>
        <div className="monitoring-nav-chip-body">
          <span className="monitoring-nav-chip-label">Grabber</span>
          <span className="monitoring-nav-chip-status">
            <span className="monitoring-nav-chip-dot" />
            {grabber.navLabel}
            {state.grabberTotal > 0 ? ` ${state.grabberActiveCount}/${state.grabberTotal}` : ''}
          </span>
        </div>
        <div className="monitoring-nav-chip-actions">
          <button
            type="button"
            className={`monitoring-nav-btn play ${grabber.canStart ? 'is-enabled' : ''}`}
            onClick={() => { void startGrabbers(); }}
            disabled={!grabber.canStart}
            title={state.grabberTotal > 0 ? 'Arm stock grabber' : 'Add a grabber first'}
            aria-label="Start stock grabber"
          >
            {state.grabberLoading === 'start' ? '…' : '▶'}
          </button>
          <button
            type="button"
            className={`monitoring-nav-btn stop ${grabber.canStop ? 'is-enabled' : ''}`}
            onClick={() => { void stopGrabbers(); }}
            disabled={!grabber.canStop}
            title="Stop all stock grabbers"
            aria-label="Stop all stock grabbers"
          >
            {state.grabberLoading === 'stop' ? '…' : '⏹'}
          </button>
        </div>
      </div>
    </div>
  );
};

export default MonitoringNavControls;
