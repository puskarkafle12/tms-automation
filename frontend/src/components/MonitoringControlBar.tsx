import React, { useState } from 'react';
import './MonitoringControlBar.css';
import ErrorMessage from './ErrorMessage';

const getApiUrl = () => localStorage.getItem('apiUrl') || window.location.origin;

interface MonitoringControlBarProps {
  title: string;
  description?: string;
  onStatusChange?: (active: boolean, message: string) => void;
}

const MonitoringControlBar: React.FC<MonitoringControlBarProps> = ({
  title,
  description,
  onStatusChange,
}) => {
  const [isActive, setIsActive] = useState(false);
  const [isStarting, setIsStarting] = useState(false);
  const [isStopping, setIsStopping] = useState(false);
  const [feedback, setFeedback] = useState<{ message: string; variant: 'success' | 'error' } | null>(null);

  const handleStart = async () => {
    setIsStarting(true);
    setFeedback(null);
    try {
      const response = await fetch(`${getApiUrl()}/check_orders/`, {
        headers: { accept: 'application/json' },
      });
      const data = await response.json().catch(() => ({}));
      const message = data.message || data.detail || 'Monitoring started';

      if (response.ok) {
        setIsActive(true);
        setFeedback({ message, variant: 'success' });
        onStatusChange?.(true, message);
      } else {
        setFeedback({ message, variant: 'error' });
        onStatusChange?.(false, message);
      }
    } catch {
      const message = 'Failed to start monitoring';
      setFeedback({ message, variant: 'error' });
      onStatusChange?.(false, message);
    } finally {
      setIsStarting(false);
    }
  };

  const handleStop = async () => {
    setIsStopping(true);
    setFeedback(null);
    try {
      const response = await fetch(`${getApiUrl()}/stop_check_orders/`, {
        headers: { accept: 'application/json' },
      });
      const data = await response.json().catch(() => ({}));
      const message = data.message || data.detail || 'Monitoring stopped';

      if (response.ok) {
        setIsActive(false);
        setFeedback({ message, variant: 'success' });
        onStatusChange?.(false, message);
      } else {
        setFeedback({ message, variant: 'error' });
      }
    } catch {
      setFeedback({ message: 'Failed to stop monitoring', variant: 'error' });
    } finally {
      setIsStopping(false);
    }
  };

  return (
    <div>
      <div className="monitoring-control-bar panel">
        <div className="monitoring-control-info">
          <span className={`monitoring-status-dot ${isActive ? 'active' : ''}`} aria-hidden="true" />
          <div>
            <h3 className="monitoring-control-title">{title}</h3>
            <p className="monitoring-control-status">
              {isActive ? 'Monitoring active' : 'Monitoring stopped'}
              {description && !isActive && ` — ${description}`}
            </p>
          </div>
        </div>
        <div className="monitoring-control-actions">
          <button
            type="button"
            className="monitoring-icon-btn play"
            onClick={handleStart}
            disabled={isActive || isStarting || isStopping}
            title="Start monitoring"
            aria-label="Start monitoring"
          >
            {isStarting ? '…' : '▶'}
          </button>
          <button
            type="button"
            className="monitoring-icon-btn stop"
            onClick={handleStop}
            disabled={!isActive || isStarting || isStopping}
            title="Stop monitoring"
            aria-label="Stop monitoring"
          >
            {isStopping ? '…' : '⏹'}
          </button>
        </div>
      </div>
      {feedback && (
        <ErrorMessage message={feedback.message} variant={feedback.variant} persistent={feedback.variant === 'error'} />
      )}
    </div>
  );
};

export default MonitoringControlBar;
