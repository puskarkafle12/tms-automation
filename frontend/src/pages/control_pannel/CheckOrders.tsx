import React, { useEffect, useState } from 'react';

const CheckOrders: React.FC = () => {
  const [logs, setLogs] = useState<string[]>([]);
  const [socket, setSocket] = useState<WebSocket | null>(null);

  useEffect(() => {
    const newSocket = new WebSocket('ws://localhost:8000/ws');
    newSocket.onopen = () => {
      console.log('WebSocket connected');
      setSocket(newSocket);
    };

    newSocket.onmessage = (event) => {

      setLogs((prevLogs) => [...prevLogs, event.data])
    };

    newSocket.onclose = () => {
      console.log('WebSocket closed');
    };

    return () => {
      newSocket.close();
    };
  }, []);

  return (
    <div>
      <h2>Check Orders Logs</h2>
      <div>
        {logs.map((log, index) => (
          <p key={index}>{log}</p>
        ))}
      </div>
    </div>
  );
};

export default CheckOrders;
