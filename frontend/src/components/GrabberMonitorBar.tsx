import React, { useEffect, useMemo, useState } from 'react';
import './PageMonitorBar.css';
import { useMonitoring } from '../hooks/useMonitoring';
import { formatMonitorDuration } from '../utils/formatDuration';

const GrabberMonitorBar: React.FC = () => {
  const { state, grabber, startGrabbers, stopGrabbers } = useMonitoring();
  const [runtime, setRuntime] = useState('');

  const earliestStartedAt = useMemo(() => {
    const timestamps = state.remoteGrabbers
      .map((item) => item.started_at)
      .filter((value): value is string => Boolean(value));
    if (!timestamps.length) {
      return null;
    }
    return timestamps.sort()[0];
  }, [state.remoteGrabbers]);

  useEffect(() => {
    const updateRuntime = () => {
      setRuntime(formatMonitorDuration(earliestStartedAt));
    };
    updateRuntime();
    const timer = window.setInterval(updateRuntime, 30000);
    return () => window.clearInterval(timer);
  }, [earliestStartedAt]);

  return (
    <div className={`page-monitor-bar grabber ${state.grabberActiveCount > 0 ? 'active' : state.grabberTotal > 0 ? 'ready' : ''}`}>
      <div className="page-monitor-bar-info">
        <span className="page-monitor-bar-icon" aria-hidden="true">⚡</span>
        <div>
          <h3 className="page-monitor-bar-title">Stock Grabber Monitor</h3>
          <p className="page-monitor-bar-desc">{grabber.description}</p>
          {state.grabberActiveCount > 0 && earliestStartedAt && (
            <p className="page-monitor-runtime">Armed for {runtime || '<1m'}</p>
          )}
        </div>
      </div>
      <div className="page-monitor-bar-actions">
        <span className={`page-monitor-bar-badge ${grabber.badgeClass}`}>
          <span className="dot" />
          {grabber.badgeLabel}
        </span>
        <button
          type="button"
          className={`page-monitor-btn play ${grabber.canStart ? 'is-enabled' : ''}`}
          onClick={() => { void startGrabbers(); }}
          disabled={!grabber.canStart}
          title={grabber.canStart ? 'Arm grabber' : state.grabberTotal > 0 ? 'All grabbers armed' : 'Add a grabber first'}
        >
          {state.grabberLoading === 'start' ? '…' : '▶'}
        </button>
        <button
          type="button"
          className={`page-monitor-btn stop ${grabber.canStop ? 'is-enabled' : 'is-available'}`}
          onClick={() => { void stopGrabbers(); }}
          disabled={!grabber.canStop}
          title="Stop all grabbers"
        >
          {state.grabberLoading === 'stop' ? '…' : '⏹'}
        </button>
      </div>
    </div>
  );
};

export default GrabberMonitorBar;
