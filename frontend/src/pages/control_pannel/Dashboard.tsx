import React, { useState } from 'react';
import ScheduleOrder from './ScheduleOrder';
import OrderStatus from './OrderLogs';
import CheckOrders from './CheckOrders';
import Login from './Login';
import './Dashboard.css';
import DPHoldings from './DpHolding';
import StockTable from './StockTable';
import Settings from './Settings';

const Home: React.FC = () => {
  const [activeComponent, setActiveComponent] = useState<string | null>(null);
  const [apiUrl, setApiUrl] = useState<string>(localStorage.getItem('apiUrl') || localStorage.getItem('apiUrl') || '' || '');
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);

  const handleButtonClick = (componentName: string) => {
    setActiveComponent(activeComponent === componentName ? null : componentName);
  };

  const toggleSettings = () => {
    setIsSettingsOpen(prevState => !prevState);
  };

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
        <button onClick={toggleSettings}>Settings</button>
      </div>

      {activeComponent === 'Login' && <Login  />}
      {activeComponent === 'ScheduleOrder' && <ScheduleOrder  />}
      {activeComponent === 'OrderStatus' && <OrderStatus  />}
      {activeComponent === 'CheckOrders' && <CheckOrders  />}
      {activeComponent === 'DPHoldings' && <DPHoldings  />}
      {activeComponent === 'StockTable' && <StockTable  />}

      {isSettingsOpen && <Settings apiUrl={apiUrl} setApiUrl={setApiUrl} />}
    </div>
  );
};

export default Home;
