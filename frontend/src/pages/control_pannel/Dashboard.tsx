import React, { useState } from 'react';
import ScheduleOrder from './ScheduleOrder';
import OrderStatus from './OrderLogs';
import CheckOrders from './CheckOrders';
import Login from './Login';
import './Dashboard.css';

const Home: React.FC = () => {
  const [activeComponent, setActiveComponent] = useState<string | null>(null);

  const handleButtonClick = (componentName: string) => {
    setActiveComponent(activeComponent === componentName ? null : componentName);
  };

  return (
    <div className="container">
      <h1>Dashboard</h1>
      <div className="dashboard-buttons">
        <button onClick={() => handleButtonClick('Login')}>Login</button>
        <button onClick={() => handleButtonClick('ScheduleOrder')}>Schedule Order</button>
        <button onClick={() => handleButtonClick('OrderStatus')}>Show Order Logs</button>
        <button onClick={() => handleButtonClick('CheckOrders')}>Check Order Logs</button>
      </div>

      {activeComponent === 'Login' && <Login />}
      {activeComponent === 'ScheduleOrder' && <ScheduleOrder />}
      {activeComponent === 'OrderStatus' && <OrderStatus />}
      {activeComponent === 'CheckOrders' && <CheckOrders />}
    </div>
  );
};

export default Home;
