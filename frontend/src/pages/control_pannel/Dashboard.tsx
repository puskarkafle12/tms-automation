import React, { useCallback, useEffect, useState } from 'react';
import ScheduleOrder from './ScheduleOrder';
import OrderStatus from './OrderLogs';
import CheckOrders from './CheckOrders';
import Login from './Login';
import './Dashboard.css';
import DPHoldings from './DpHolding';
import StockTable from './StockTable';

const Home: React.FC = () => {
  const [activeComponent, setActiveComponent] = useState<string | null>(null);

  const handleButtonClick = (componentName: string) => {
    setActiveComponent(activeComponent === componentName ? null : componentName);
  };

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
    console.log("logged in client fetched ")
  }, []);
  useEffect(() => {
    fetchLoggedInClients();
  }, [fetchLoggedInClients]);

  
  return (
    <div className="container">
      <h1>Dashboard</h1>
      <div className="dashboard-buttons">
        <button onClick={() => handleButtonClick('Login')}>Login</button>
        <button onClick={() => handleButtonClick('ScheduleOrder')}>Schedule Order</button>
        <button onClick={() => handleButtonClick('OrderStatus')}>Show Order Logs</button>
        <button onClick={() => handleButtonClick('CheckOrders')}>Check Order Logs</button>
        <button onClick={() => handleButtonClick('DPHoldings')}>DP Holdings</button>
        <button onClick={() => handleButtonClick('StockTable')}>Stock Table</button>
      </div>

      {activeComponent === 'Login' && <Login  />}
      {activeComponent === 'ScheduleOrder' && <ScheduleOrder  />}
      {activeComponent === 'OrderStatus' && <OrderStatus  />}
      {activeComponent === 'CheckOrders' && <CheckOrders  />}
      {activeComponent === 'DPHoldings' && <DPHoldings  />}
      {activeComponent === 'StockTable' && <StockTable  />}

    </div>
  );
};

export default Home;
