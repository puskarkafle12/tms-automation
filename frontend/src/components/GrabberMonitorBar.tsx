import React from 'react';
import './PageMonitorBar.css';
import { useMonitoringActions } from '../hooks/useMonitoringActions';

const GrabberMonitorBar: React.FC = () => {
  const {
    grabberActiveCount,
    grabberTotal,
    grabberIsActive,
    hasGrabbers,
    canStartGrabber,
    canStopGrabber,
    grabberLoading,
    startGrabbers,
    stopGrabbers,
  } = useMonitoringActions();

  return (
    <div className={`page-monitor-bar grabber ${grabberIsActive ? 'active' : hasGrabbers ? 'ready' : ''}`}>
      <div className="page-monitor-bar-info">
        <span className="page-monitor-bar-icon" aria-hidden="true">⚡</span>
        <div>
          <h3 className="page-monitor-bar-title">Stock Grabber Monitor</h3>
          <p className="page-monitor-bar-desc">
            {grabberIsActive
              ? `Scanning ${grabberActiveCount} of ${grabberTotal} grabber${grabberTotal !== 1 ? 's' : ''} at 2% high price.`
              : hasGrabbers
                ? `${grabberTotal} grabber${grabberTotal !== 1 ? 's' : ''} ready — start to begin scanning.`
                : 'Add a grabber below, then start scanning.'}
          </p>
        </div>
      </div>
      <div className="page-monitor-bar-actions">
        <span className={`page-monitor-bar-badge ${grabberIsActive ? 'active' : hasGrabbers ? 'ready' : 'idle'}`}>
          <span className="dot" />
          {grabberIsActive ? 'Scanning' : hasGrabbers ? 'Ready' : 'Idle'}
        </span>
        <button
          type="button"
          className={`page-monitor-btn play ${canStartGrabber ? 'is-enabled' : ''}`}
          onClick={() => { void startGrabbers(); }}
          disabled={!canStartGrabber || grabberLoading !== null}
          title={canStartGrabber ? 'Start grabber' : hasGrabbers ? 'All grabbers running' : 'Add a grabber first'}
        >
          {grabberLoading === 'start' ? '…' : '▶'}
        </button>
        <button
          type="button"
          className={`page-monitor-btn stop ${grabberIsActive ? 'is-enabled' : 'is-available'}`}
          onClick={() => { void stopGrabbers(); }}
          disabled={grabberLoading !== null}
          title="Stop all grabbers"
        >
          {grabberLoading === 'stop' ? '…' : '⏹'}
        </button>
      </div>
    </div>
  );
};

export default GrabberMonitorBar;
