import React, { useEffect, useState, useCallback } from 'react';
import './CheckOrders.css';
import MonitorOrders from './MonitorOrders';
import ErrorMessage from '../../components/ErrorMessage';
import useHotkeys from '@reecelucas/react-use-hotkeys';
import moment from 'moment-timezone';

interface OrderLog {
  id: number;
  client_id: string;
  script_name: string;
  scanning_count: number;
  current_price: number;
  order_placed: boolean;
  timestamp: string;
  logs: string | null;
}

const getApiUrl = () => localStorage.getItem('apiUrl') || 'http://localhost:8000';

const CheckOrders: React.FC = () => {
  const [logs, setLogs] = useState<OrderLog[]>([]);
  const [refreshInterval, setRefreshInterval] = useState<number>(5000);
  const [showSettings, setShowSettings] = useState(false);
  const [clientID, setClientID] = useState('');
  const [scriptName, setScriptName] = useState('');
  const [newRefreshInterval, setNewRefreshInterval] = useState<number>(5);
  const [filteredLogs, setFilteredLogs] = useState<OrderLog[]>([]);
  const [statusMessage, setStatusMessage] = useState('');
  const [statusVariant, setStatusVariant] = useState<'success' | 'error'>('success');
  const [isClearing, setIsClearing] = useState(false);

  const fetchLoggedInClients = useCallback(async () => {
    try {
      const response = await fetch(`${getApiUrl()}/logged_in_clients/`);
      if (!response.ok) {
        throw new Error('Failed to fetch logged-in clients');
      }
      const data = await response.json();
      localStorage.setItem('client_ids', JSON.stringify(data.logged_in_client_ids));
    } catch (error) {
      console.error('Error fetching logged-in clients:', error);
    }
  }, []);

  const fetchLogs = useCallback(async () => {
    try {
      const clientIds = JSON.parse(localStorage.getItem('client_ids') || '[]');
      if (clientIds.length === 0) {
        setLogs([]);
        setFilteredLogs([]);
        return;
      }

      const queryParams = clientIds.map((id: string) => `client_ids=${id}`).join('&');
      const response = await fetch(`${getApiUrl()}/logs/?${queryParams}`);
      if (!response.ok) {
        throw new Error('Failed to fetch logs');
      }
      const data = await response.json();
      const newLogs = data.order_logs;
      setLogs(newLogs);
      localStorage.setItem('logs', JSON.stringify(newLogs));
      setFilteredLogs(newLogs);
    } catch (error) {
      console.error('Error fetching logs:', error);
    }
  }, []);

  const fetchMonitorInterval = useCallback(async () => {
    try {
      const response = await fetch(`${getApiUrl()}/get_monitor_interval`);
      if (!response.ok) {
        throw new Error('Failed to fetch monitor interval');
      }
      const data = await response.json();
      const interval = data.monitor_interval;
      if (interval) {
        setRefreshInterval(interval * 1000);
        setNewRefreshInterval(interval);
        localStorage.setItem('refresh_interval', interval.toString());
      }
    } catch (error) {
      console.error('Error fetching monitor interval:', error);
    }
  }, []);

  useEffect(() => {
    const initialize = async () => {
      await fetchLoggedInClients();
      await fetchLogs();
      await fetchMonitorInterval();
    };

    initialize();
  }, [fetchLoggedInClients, fetchLogs, fetchMonitorInterval]);

  useEffect(() => {
    const interval = setInterval(() => {
      fetchLogs();
    }, refreshInterval);

    return () => clearInterval(interval);
  }, [fetchLogs, refreshInterval]);

  useHotkeys('s', () => {
    setShowSettings((prev) => !prev);
  });

  const handleInputChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const value = parseInt(event.target.value, 10);
    if (!isNaN(value) && value >= 3) {
      setNewRefreshInterval(value);
    }
  };

  const handleUpdateInterval = async () => {
    try {
      const response = await fetch(`${getApiUrl()}/update_monitor_interval`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ monitor_interval: newRefreshInterval }),
      });

      if (response.ok) {
        setRefreshInterval(newRefreshInterval * 1000);
        localStorage.setItem('refresh_interval', newRefreshInterval.toString());
        setStatusMessage(`Refresh interval updated to ${newRefreshInterval}s.`);
        setStatusVariant('success');
      } else {
        throw new Error('Failed to update monitor interval');
      }
    } catch (error) {
      setStatusMessage('Failed to update refresh interval.');
      setStatusVariant('error');
    } finally {
      setShowSettings(false);
    }
  };

  const clearLogs = async () => {
    setIsClearing(true);
    try {
      const clientIds = JSON.parse(localStorage.getItem('client_ids') || '[]');
      const response = await fetch(`${getApiUrl()}/logs/?client_ids=${clientIds.join(',')}`, {
        method: 'DELETE',
      });
      if (!response.ok) {
        throw new Error('Failed to clear logs');
      }
      setLogs([]);
      setFilteredLogs([]);
      localStorage.removeItem('logs');
      setStatusMessage('Logs cleared successfully.');
      setStatusVariant('success');
    } catch (error) {
      setStatusMessage('Failed to clear logs.');
      setStatusVariant('error');
    } finally {
      setIsClearing(false);
    }
  };

  const handleSearch = useCallback(() => {
    const trimmedClientID = clientID.trim().toLowerCase();
    const trimmedScriptName = scriptName.trim().toLowerCase();
    const filtered = logs.filter((log) => {
      const clientIDMatch = trimmedClientID ? log.client_id.toLowerCase().includes(trimmedClientID) : true;
      const scriptNameMatch = trimmedScriptName ? log.script_name.toLowerCase().includes(trimmedScriptName) : true;
      return clientIDMatch && scriptNameMatch;
    });

    setFilteredLogs(filtered);
  }, [clientID, scriptName, logs]);

  useEffect(() => {
    handleSearch();
  }, [handleSearch]);

  const convertToKathmanduTime = (timestamp: string): string => {
    if (!timestamp) return '—';
    try {
      return moment.utc(timestamp).tz('Asia/Kathmandu').format('hh:mm:ss A');
    } catch {
      return '—';
    }
  };

  const placedCount = filteredLogs.filter((log) => log.order_placed).length;

  return (
    <div className="check-orders-page">
      <div className="check-orders-hero panel">
        <div className="check-orders-hero-content">
          <div className="check-orders-hero-icon" aria-hidden="true">✓</div>
          <div>
            <h2 className="check-orders-hero-title">Check Orders</h2>
            <p className="check-orders-hero-subtitle">
              Monitor stock prices and track automated order placement logs.
            </p>
          </div>
        </div>
        <button type="button" className="btn btn-secondary" onClick={fetchLogs}>
          Refresh Logs
        </button>
      </div>

      {statusMessage && (
        <ErrorMessage
          message={statusMessage}
          variant={statusVariant}
          persistent={statusVariant === 'error'}
        />
      )}

      <div className="check-orders-stats">
        <div className="check-orders-stat-card">
          <span className="check-orders-stat-label">Active Logs</span>
          <span className="check-orders-stat-value">{filteredLogs.length}</span>
        </div>
        <div className="check-orders-stat-card">
          <span className="check-orders-stat-label">Orders Placed</span>
          <span className="check-orders-stat-value">{placedCount}</span>
        </div>
        <div className="check-orders-stat-card">
          <span className="check-orders-stat-label">Refresh Interval</span>
          <span className="check-orders-stat-value">{refreshInterval / 1000}s</span>
        </div>
      </div>

      <div className="check-orders-toolbar panel">
        <div className="check-orders-toolbar-header">
          <div>
            <h3 className="panel-title">Monitoring Controls</h3>
            <p className="panel-subtitle">Start or stop stock monitoring and filter live logs.</p>
          </div>
          <div className="check-orders-toolbar-actions">
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => setShowSettings(true)}>
              Settings
            </button>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={clearLogs}
              disabled={isClearing || filteredLogs.length === 0}
            >
              {isClearing ? 'Clearing...' : 'Clear Logs'}
            </button>
          </div>
        </div>

        <MonitorOrders
          onStatusChange={(message, variant) => {
            setStatusMessage(message);
            setStatusVariant(variant);
          }}
        />

        <div className="check-orders-filters">
          <div className="form-group">
            <label htmlFor="checkClientId">Filter by Client ID</label>
            <input
              id="checkClientId"
              type="text"
              className="input"
              value={clientID}
              onChange={(e) => setClientID(e.target.value)}
              placeholder="All clients"
            />
          </div>
          <div className="form-group">
            <label htmlFor="checkScriptName">Filter by Script</label>
            <input
              id="checkScriptName"
              type="text"
              className="input"
              value={scriptName}
              onChange={(e) => setScriptName(e.target.value)}
              placeholder="All scripts"
            />
          </div>
          <button type="button" className="btn btn-primary" onClick={handleSearch}>
            Apply Filter
          </button>
        </div>
        <p className="check-orders-hint">Press <kbd>S</kbd> to open refresh interval settings.</p>
      </div>

      <div className="check-orders-content panel">
        <div className="check-orders-content-header">
          <h3 className="panel-title">Live Order Logs</h3>
          <span className="badge badge-muted">Auto-refresh every {refreshInterval / 1000}s</span>
        </div>

        {filteredLogs.length > 0 ? (
          <div className="check-orders-log-grid">
            {filteredLogs.map((log) => (
              <div key={log.id} className="check-orders-log-card">
                <div className="check-orders-log-card-header">
                  <span className="check-orders-log-symbol">{log.script_name}</span>
                  <span className={`badge ${log.order_placed ? 'badge-success' : 'badge-muted'}`}>
                    {log.order_placed ? 'Placed' : 'Watching'}
                  </span>
                </div>
                <span className="check-orders-log-client">{log.client_id}</span>
                <div className="check-orders-log-meta">
                  <div className="check-orders-log-field">
                    <span className="check-orders-log-label">Current Price</span>
                    <span className="check-orders-log-value">{log.current_price}</span>
                  </div>
                  <div className="check-orders-log-field">
                    <span className="check-orders-log-label">Scans</span>
                    <span className="check-orders-log-value">{log.scanning_count}</span>
                  </div>
                  <div className="check-orders-log-field">
                    <span className="check-orders-log-label">Last Fetched</span>
                    <span className="check-orders-log-value">{convertToKathmanduTime(log.timestamp)}</span>
                  </div>
                  <div className="check-orders-log-field">
                    <span className="check-orders-log-label">Order Placed</span>
                    <span className="check-orders-log-value">{log.order_placed ? 'Yes' : 'No'}</span>
                  </div>
                </div>
                {log.logs && (
                  <p className="check-orders-log-message">{log.logs}</p>
                )}
              </div>
            ))}
          </div>
        ) : (
          <div className="check-orders-empty">
            <span className="check-orders-empty-icon" aria-hidden="true">📭</span>
            <p>No logs found. Start monitoring to begin tracking orders.</p>
          </div>
        )}
      </div>

      {showSettings && (
        <div className="check-orders-modal-overlay" onClick={() => setShowSettings(false)}>
          <div className="check-orders-modal" onClick={(e) => e.stopPropagation()}>
            <button
              type="button"
              className="check-orders-modal-close"
              onClick={() => setShowSettings(false)}
              aria-label="Close"
            >
              ×
            </button>
            <h3 className="check-orders-modal-title">Monitor Settings</h3>
            <p className="check-orders-modal-subtitle">Configure how often logs are refreshed.</p>
            <div className="form-group">
              <label htmlFor="refreshInterval">Refresh Interval (seconds)</label>
              <input
                id="refreshInterval"
                type="number"
                className="input"
                value={newRefreshInterval}
                min={3}
                onChange={handleInputChange}
              />
            </div>
            <div className="check-orders-modal-actions">
              <button type="button" className="btn btn-secondary" onClick={() => setShowSettings(false)}>
                Cancel
              </button>
              <button type="button" className="btn btn-primary" onClick={handleUpdateInterval}>
                Save
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default CheckOrders;
