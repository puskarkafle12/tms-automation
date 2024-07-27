import React, { useEffect, useState, useCallback } from 'react';
import './CheckOrders.css';
import MonitorOrders from './MonitorOrders';

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
  const [filteredLogs, setFilteredLogs] = useState<OrderLog[]>([]);

  const fetchLoggedInClients = useCallback(async () => {
    try {
      const response = await fetch(`${process.env.REACT_APP_API_URL}/logged_in_clients/`);
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
      const response = await fetch(`${process.env.REACT_APP_API_URL}/logs/?${queryParams}`);
      if (!response.ok) {
        throw new Error('Failed to fetch logs');
      }
      const data = await response.json();
      const newLogs = data.order_logs;
      setLogs(newLogs);
      localStorage.setItem('logs', JSON.stringify(newLogs));
      setFilteredLogs(newLogs); // Initially set filteredLogs to all logs
    } catch (error) {
      console.error('Error fetching logs:', error);
    }
  }, []);

  useEffect(() => {
    const initialize = async () => {
      await fetchLoggedInClients();
      await fetchLogs();
    };

    initialize();
  }, [fetchLoggedInClients, fetchLogs]);

  useEffect(() => {
    const interval = setInterval(() => {
      fetchLogs();
    }, refreshInterval);

    return () => {
      clearInterval(interval);
    };
  }, [fetchLogs, refreshInterval]);

  useEffect(() => {
    const handleShortcut = (event: KeyboardEvent) => {
      if (event.key === 'f') {
        setShowInput(prevShowInput => !prevShowInput);
      }
    };

    window.addEventListener('keydown', handleShortcut);
    return () => {
      window.removeEventListener('keydown', handleShortcut);
    };
  }, []);

  const handleInputChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const value = parseInt(event.target.value, 10);
    if (!isNaN(value) && value >= 3) {
      setRefreshInterval(value * 1000);
      localStorage.setItem('refresh_interval', value.toString());
    }
  };

  useEffect(() => {
    const savedInterval = localStorage.getItem('refresh_interval');
    if (savedInterval) {
      setRefreshInterval(Math.max(parseInt(savedInterval, 10), 3) * 1000);
    }
  }, []);

  const clearLogs = async () => {
    try {
      const clientIds = JSON.parse(localStorage.getItem('client_ids') || '[]');
      const response = await fetch(`${process.env.REACT_APP_API_URL}/logs/?client_ids=${clientIds.join(',')}`, {
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

    setFilteredLogs(filtered); // Update filteredLogs with the matched logs
  };

  useEffect(() => {
    handleSearch(); // Run the search whenever clientID or scriptName changes
  }, [clientID, scriptName, logs]);

  return (
    <div className="check-orders-container">
      <h2>Check Orders Logs</h2>
      <MonitorOrders />
      <button onClick={clearLogs}>Clear Logs</button>
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
                value={refreshInterval / 1000}
                onChange={handleInputChange}
                min="3"
              />
            </div>
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
              <p>Timestamp: {new Date(log.timestamp).toLocaleString('en-GB', { timeZone: 'Asia/Kathmandu' })}</p>
              <p>Logs: {log.logs ? log.logs : 'No logs available'}</p>
              <hr />
            </div>
          ))
        ) : (
          <p>No logs found.</p> // Display message if no logs match the search
        )}
      </div>
    </div>
  );
};

export default CheckOrders;
