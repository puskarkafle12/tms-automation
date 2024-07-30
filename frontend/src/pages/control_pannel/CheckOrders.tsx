import React, { useEffect, useState, useCallback } from 'react';
import './CheckOrders.css';
import MonitorOrders from './MonitorOrders';
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

const CheckOrders: React.FC = () => {
  const [logs, setLogs] = useState<OrderLog[]>([]);
  const [refreshInterval, setRefreshInterval] = useState<number>(5000);
  const [showInput, setShowInput] = useState<boolean>(false);
  const [clientID, setClientID] = useState('');
  const [scriptName, setScriptName] = useState('');
  const [newRefreshInterval, setNewRefreshInterval] = useState<number>(5);
  const [filteredLogs, setFilteredLogs] = useState<OrderLog[]>([]);

  const fetchLoggedInClients = useCallback(async () => {
    try {
      const response = await fetch(`${localStorage.getItem('apiUrl') || ''}/logged_in_clients/`);
      if (!response.ok) {
        throw new Error('Failed to fetch logged-in clients');
      }
      const data = await response.json();
      const clientIds = data.logged_in_client_ids;
      localStorage.setItem('client_ids', JSON.stringify(clientIds));
    } catch (error) {
      console.error('Error fetching logged-in clients:', error);
    }
  }, []);

  const fetchLogs = useCallback(async () => {
    try {
      const clientIds = JSON.parse(localStorage.getItem('client_ids') || '[]');
      if (clientIds.length === 0) return;

      const queryParams = clientIds.map((id: string) => `client_ids=${id}`).join('&');
      const response = await fetch(`${localStorage.getItem('apiUrl') || ''}/logs/?${queryParams}`);
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
      const response = await fetch(`${localStorage.getItem('apiUrl') || ''}/get_monitor_interval`);
      if (!response.ok) {
        throw new Error('Failed to fetch monitor interval');
      }
      const data = await response.json();
      const interval = data.monitor_interval;
      if (interval) {
        setRefreshInterval(interval * 1000);
        localStorage.setItem('refresh_interval', interval.toString());
        return interval;
      }
    } catch (error) {
      console.error('Error fetching monitor interval:', error);
      return 'error';
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

    return () => {
      clearInterval(interval);
    };
  }, [fetchLogs, refreshInterval]);

  useHotkeys('s', () => {
    setShowInput(prevShowInput => !prevShowInput);
  });

  const handleInputChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const value = parseInt(event.target.value, 10);
    if (!isNaN(value) && value >= 3) {
      setNewRefreshInterval(value);
    }
  };

  const handleDialogClose = async () => {
    try {
      const response = await fetch(`${localStorage.getItem('apiUrl') || ''}/update_monitor_interval`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ monitor_interval: newRefreshInterval }),
      });

      if (response.ok) {
        setRefreshInterval(newRefreshInterval * 1000);
        localStorage.setItem('refresh_interval', newRefreshInterval.toString());
        const data = await response.json();
        console.log('Monitor interval updated successfully:', data);
      } else {
        throw new Error('Failed to update monitor interval');
      }
    } catch (error) {
      console.error('Error updating monitor interval:', error);
    } finally {
      setShowInput(false);
    }
  };

  const clearLogs = async () => {
    try {
      const clientIds = JSON.parse(localStorage.getItem('client_ids') || '[]');
      const response = await fetch(`${localStorage.getItem('apiUrl') || ''}/logs/?client_ids=${clientIds.join(',')}`, {
        method: 'DELETE',
      });
      if (!response.ok) {
        throw new Error('Failed to clear logs');
      }
      setLogs([]);
      setFilteredLogs([]);
      localStorage.removeItem('logs');
    } catch (error) {
      console.error('Error clearing logs:', error);
    }
  };

  const handleSearch = () => {
    const trimmedClientID = clientID.trim().toLowerCase();
    const trimmedScriptName = scriptName.trim().toLowerCase();
    const filtered = logs.filter(log => {
      const clientIDMatch = trimmedClientID ? log.client_id.toLowerCase().includes(trimmedClientID) : true;
      const scriptNameMatch = trimmedScriptName ? log.script_name.toLowerCase().includes(trimmedScriptName) : true;
      return clientIDMatch && scriptNameMatch;
    });

    setFilteredLogs(filtered);
  };

  useEffect(() => {
    handleSearch();
  }, [clientID, scriptName, logs]);

  const convertToKathmanduTime = (timestamp: string): string => {
    if (!timestamp) return 'Invalid timestamp';

    try {
      const date = moment.utc(timestamp).tz('Asia/Kathmandu');
      return date.format('hh:mm:ss A'); // Format time in 12-hour format
    } catch (error) {
      console.error('Error converting timestamp:', error);
      return 'Invalid timestamp';
    }
  };
  return (
    <div className="check-orders-container">
      <h2>Check Orders Logs</h2>
      <MonitorOrders />
      <button onClick={clearLogs}>Clear Logs</button>
      <p>Refresh interval: {refreshInterval / 1000}</p>
      {showInput && (
        <div className="overlay">
          <div className="popup">
            <button className="popup-close" onClick={() => setShowInput(false)}>✖</button>
            <div className="form-group">
              <label>Client ID:</label>
              <input
                type="text"
                value={clientID}
                onChange={(e) => setClientID(e.target.value)}
                placeholder="Enter Client ID"
              />
            </div>
            <div className="form-group">
              <label>Script Name:</label>
              <input
                type="text"
                value={scriptName}
                onChange={(e) => setScriptName(e.target.value)}
                placeholder="Enter Script Name"
              />
            </div>
            <div className="form-group">
              <label>Set Refresh Interval (seconds): </label>
              <input
                type="number"
                value={newRefreshInterval}
                onChange={handleInputChange}
              />
            </div>
            <button onClick={handleDialogClose}>Update Interval</button>
          </div>
        </div>
      )}
      <div>
        {filteredLogs.length > 0 ? (
          filteredLogs.map((log, index) => (
            <div key={index} className="log-item">
              <p>Client ID: {log.client_id}</p>
              <p>Script Name: {log.script_name}</p>
              <p>Scanning Count: {log.scanning_count}</p>
              <p>Current Price: {log.current_price}</p>
              <p>Order Placed: {log.order_placed ? 'Yes' : 'No'}</p>
              <p>Last Fetched: {convertToKathmanduTime(log.timestamp)}</p>
              <p>Logs: {log.logs ? log.logs : 'No logs available'}</p>
              <hr />
            </div>
          ))
        ) : (
          <p>No logs found.</p>
        )}
      </div>
    </div>
  );
};

export default CheckOrders;
