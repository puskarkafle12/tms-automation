import React, { useState } from 'react';
import './MonitoringDashboard.css';
import ErrorMessage from './ErrorMessage';
import { monitoringStore } from '../hooks/monitoringStore';
import { useMonitoringStore } from '../hooks/useMonitoringStore';

const getApiUrl = () => localStorage.getItem('apiUrl') || 'http://localhost:8000';

export interface GrabberControls {
  start: () => void;
  stop: () => void;
  getIsRunning: () => boolean;
}

interface MonitoringDashboardProps {
  getGrabberControls?: () => Map<string, GrabberControls>;
  grabberCanStart?: boolean;
  enableGrabberControls?: boolean;
}

const MonitoringDashboard: React.FC<MonitoringDashboardProps> = ({
  getGrabberControls,
  grabberCanStart = false,
  enableGrabberControls = true,
}) => {
  const { scheduledActive, grabberActiveCount, grabberTotal } = useMonitoringStore();
  const [scheduledLoading, setScheduledLoading] = useState<'start' | 'stop' | null>(null);
  const [grabberLoading, setGrabberLoading] = useState<'start' | 'stop' | null>(null);
  const [feedback, setFeedback] = useState<{ message: string; variant: 'success' | 'error' } | null>(null);

  const startScheduled = async () => {
    setScheduledLoading('start');
    setFeedback(null);
    try {
      const response = await fetch(`${getApiUrl()}/check_orders/`, {
        headers: { accept: 'application/json' },
      });
      const data = await response.json().catch(() => ({}));
      const message = data.message || data.detail || 'Scheduled order monitoring started';

      if (response.ok) {
        monitoringStore.setScheduledActive(true);
        setFeedback({ message, variant: 'success' });
      } else {
        setFeedback({ message, variant: 'error' });
      }
    } catch {
      setFeedback({ message: 'Failed to start scheduled order monitoring', variant: 'error' });
    } finally {
      setScheduledLoading(null);
    }
  };

  const stopScheduled = async () => {
    setScheduledLoading('stop');
    setFeedback(null);
    try {
      const response = await fetch(`${getApiUrl()}/stop_check_orders/`, {
        headers: { accept: 'application/json' },
      });
      const data = await response.json().catch(() => ({}));
      const message = data.message || data.detail || 'Scheduled order monitoring stopped';

      if (response.ok) {
        monitoringStore.setScheduledActive(false);
        setFeedback({ message, variant: 'success' });
      } else {
        setFeedback({ message, variant: 'error' });
      }
    } catch {
      setFeedback({ message: 'Failed to stop scheduled order monitoring', variant: 'error' });
    } finally {
      setScheduledLoading(null);
    }
  };

  const startGrabbers = () => {
    const controls = getGrabberControls?.() ?? new Map();
    if (!controls.size) {
      setFeedback({ message: 'Add a stock grabber below first', variant: 'error' });
      return;
    }

    setGrabberLoading('start');
    const idle = Array.from(controls.values()).find((c) => !c.getIsRunning());
    if (idle) {
      idle.start();
      setFeedback({ message: 'Stock grabber started', variant: 'success' });
    } else {
      setFeedback({ message: 'All grabbers are already running', variant: 'error' });
    }
    setGrabberLoading(null);
  };

  const stopGrabbers = async () => {
    const controls = getGrabberControls?.() ?? new Map();
    if (!controls.size) {
      return;
    }

    setGrabberLoading('stop');
    const running = Array.from(controls.values()).filter((c) => c.getIsRunning());
    await Promise.all(running.map((c) => Promise.resolve(c.stop())));
    setFeedback({ message: 'All stock grabbers stopped', variant: 'success' });
    setGrabberLoading(null);
  };

  const grabberIsActive = grabberActiveCount > 0;
  const hasGrabbers = grabberTotal > 0;

  return (
    <div>
      <div className="monitoring-dashboard panel">
        <div className="monitoring-dashboard-header">
          <h2 className="monitoring-dashboard-title">Monitoring Control</h2>
          <p className="monitoring-dashboard-subtitle">
            Start or stop scheduled order checks and stock grabber scans from one place.
          </p>
        </div>

        <div className="monitoring-dashboard-grid">
          <div className="monitoring-card scheduled">
            <div className="monitoring-card-top">
              <div className="monitoring-card-icon-wrap" aria-hidden="true">📅</div>
              <div className="monitoring-card-heading">
                <h3 className="monitoring-card-title">Scheduled Orders</h3>
                <p className="monitoring-card-desc">
                  Watches queued orders and executes when price conditions are met.
                </p>
              </div>
              <span className={`monitoring-status-badge ${scheduledActive ? 'active' : 'idle'}`}>
                <span className="dot" />
                {scheduledActive ? 'Active' : 'Stopped'}
              </span>
            </div>
            <div className="monitoring-card-footer">
              <p className="monitoring-card-meta">
                Status: <strong>{scheduledActive ? 'Monitoring scheduled orders' : 'Not monitoring'}</strong>
              </p>
              <div className="monitoring-card-actions">
                <button
                  type="button"
                  className="monitoring-action-btn play"
                  onClick={startScheduled}
                  disabled={scheduledActive || scheduledLoading !== null}
                  title="Start scheduled order monitoring"
                >
                  <span className="icon">{scheduledLoading === 'start' ? '…' : '▶'}</span>
                  Start
                </button>
                <button
                  type="button"
                  className="monitoring-action-btn stop"
                  onClick={stopScheduled}
                  disabled={!scheduledActive || scheduledLoading !== null}
                  title="Stop scheduled order monitoring"
                >
                  <span className="icon">{scheduledLoading === 'stop' ? '…' : '⏹'}</span>
                  Stop
                </button>
              </div>
            </div>
          </div>

          <div className="monitoring-card grabber">
            <div className="monitoring-card-top">
              <div className="monitoring-card-icon-wrap" aria-hidden="true">⚡</div>
              <div className="monitoring-card-heading">
                <h3 className="monitoring-card-title">Stock Grabber</h3>
                <p className="monitoring-card-desc">
                  Scans at 2% high price — places orders when the price moves.
                </p>
              </div>
              <span className={`monitoring-status-badge ${grabberIsActive ? 'active' : hasGrabbers ? 'warn' : 'idle'}`}>
                <span className="dot" />
                {grabberIsActive ? 'Scanning' : hasGrabbers ? 'Ready' : 'Idle'}
              </span>
            </div>
            <div className="monitoring-card-footer">
              <p className="monitoring-card-meta">
                {enableGrabberControls ? (
                  <>
                    Active: <strong>{grabberActiveCount}</strong> / {grabberTotal} monitor{grabberTotal !== 1 ? 's' : ''}
                  </>
                ) : (
                  <>Manage grabbers in the <strong>Stock Grabber</strong> tab</>
                )}
              </p>
              <div className="monitoring-card-actions">
                <button
                  type="button"
                  className="monitoring-action-btn play"
                  onClick={startGrabbers}
                  disabled={
                    !enableGrabberControls
                    || !grabberCanStart
                    || (grabberTotal > 0 && grabberActiveCount >= grabberTotal)
                    || grabberLoading !== null
                  }
                  title="Start stock grabber"
                >
                  <span className="icon">{grabberLoading === 'start' ? '…' : '▶'}</span>
                  Start
                </button>
                <button
                  type="button"
                  className="monitoring-action-btn stop"
                  onClick={stopGrabbers}
                  disabled={!enableGrabberControls || !grabberIsActive || grabberLoading !== null}
                  title="Stop all stock grabbers"
                >
                  <span className="icon">{grabberLoading === 'stop' ? '…' : '⏹'}</span>
                  Stop
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      {feedback && (
        <div className="monitoring-dashboard-feedback">
          <ErrorMessage message={feedback.message} variant={feedback.variant} persistent={feedback.variant === 'error'} />
        </div>
      )}
    </div>
  );
};

export default MonitoringDashboard;
