import React, { useEffect, useState } from 'react';
import MonitorOrders from './MonitorOrders';

const CheckOrders: React.FC = () => {
  const wsUrl = process.env.REACT_APP_WS_URL;
  const [logs, setLogs] = useState<string[]>([]);
  const [socket, setSocket] = useState<WebSocket | null>(null);
  // console.log(wsUrl);
  useEffect(() => {
    let newSocket: WebSocket | null = null;
    const savedLogs = localStorage.getItem('logs');
    if (savedLogs) {
      setLogs(JSON.parse(savedLogs));
    }

    const connectSocket = () => {
      newSocket = new WebSocket(wsUrl+'/ws');
      newSocket.onopen = () => {
        console.log('WebSocket connected');
        setSocket(newSocket);
      };

      newSocket.onmessage = (event) => {
        setLogs((prevLogs) => {
          const newLogs = [...prevLogs, event.data];
          localStorage.setItem('logs', JSON.stringify(newLogs));
          return newLogs;
        });
      };

      newSocket.onclose = () => {
        console.log('WebSocket closed');
        setSocket(null);
      };
    };

    connectSocket();

    const interval = setInterval(() => {
      if (!newSocket || newSocket.readyState === WebSocket.CLOSED) {
        connectSocket();
      }
    }, 5000);

    return () => {
      clearInterval(interval);
      if (newSocket) {
        newSocket.close();
      }
    };
  }, []);

  const clearLogs = () => {
    setLogs([]);
    localStorage.removeItem('logs');
  };

  return (
    <div>
      <h2>Check Orders Logs</h2>
      <MonitorOrders />
      <button onClick={clearLogs}>Clear Logs</button>
      <div >
        {logs.map((log, index) => (
          <p key={index}>{log}</p>
        ))}
      </div>
    </div>
  );
};

export default CheckOrders;
