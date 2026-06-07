import React, { useState } from 'react';
import ErrorMessage from '../../components/ErrorMessage';

interface MonitorOrdersProps {
  onStatusChange?: (message: string, variant: 'success' | 'error') => void;
}

const getApiUrl = () => localStorage.getItem('apiUrl') || window.location.origin;

const MonitorOrders: React.FC<MonitorOrdersProps> = ({ onStatusChange }) => {
  const [errorMessage, setErrorMessage] = useState('');
  const [successMessage, setSuccessMessage] = useState('');
  const [isStarting, setIsStarting] = useState(false);
  const [isStopping, setIsStopping] = useState(false);

  const handleResponse = async (response: Response, action: string) => {
    const data = await response.json().catch(() => ({}));
    const message = data.message || data.detail || `${action} completed.`;

    if (response.ok) {
      setSuccessMessage(message);
      setErrorMessage('');
      onStatusChange?.(message, 'success');
    } else {
      setErrorMessage(message);
      setSuccessMessage('');
      onStatusChange?.(message, 'error');
    }
  };

  const handleStartClick = async () => {
    setIsStarting(true);
    setErrorMessage('');
    setSuccessMessage('');
    try {
      const response = await fetch(`${getApiUrl()}/check_orders/`, {
        headers: { accept: 'application/json' },
      });
      await handleResponse(response, 'Monitoring started');
    } catch {
      const message = 'Failed to start monitoring.';
      setErrorMessage(message);
      onStatusChange?.(message, 'error');
    } finally {
      setIsStarting(false);
    }
  };

  const handleStopClick = async () => {
    setIsStopping(true);
    setErrorMessage('');
    setSuccessMessage('');
    try {
      const response = await fetch(`${getApiUrl()}/stop_check_orders/`, {
        headers: { accept: 'application/json' },
      });
      await handleResponse(response, 'Monitoring stopped');
    } catch {
      const message = 'Failed to stop monitoring.';
      setErrorMessage(message);
      onStatusChange?.(message, 'error');
    } finally {
      setIsStopping(false);
    }
  };

  return (
    <div className="check-orders-monitor">
      <button
        type="button"
        className="btn btn-success"
        onClick={handleStartClick}
        disabled={isStarting || isStopping}
      >
        {isStarting ? 'Starting...' : 'Start Monitoring'}
      </button>
      <button
        type="button"
        className="btn btn-secondary"
        onClick={handleStopClick}
        disabled={isStarting || isStopping}
      >
        {isStopping ? 'Stopping...' : 'Stop Monitoring'}
      </button>
      {successMessage && <ErrorMessage message={successMessage} variant="success" />}
      {errorMessage && <ErrorMessage message={errorMessage} variant="error" persistent />}
    </div>
  );
};

export default MonitorOrders;
