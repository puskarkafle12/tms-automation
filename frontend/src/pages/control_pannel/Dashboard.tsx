import React, { useCallback, useEffect, useState } from 'react';
import ScheduleOrder from './ScheduleOrder';
import OrderStatus from './OrderLogs';
import CheckOrders from './CheckOrders';
import Login from './Login';
import './Dashboard.css';
import DPHoldings from './DpHolding';
import StockTable from './StockTable';
import StockGrabber from './StockGrabber';

interface StockGrabberInstance {
  id: string;
  client_id: string;
  stock_symbol: string;
}

interface DashboardProps {
  activeComponent?: string;
}

const DashBoardPage: React.FC<DashboardProps> = ({ activeComponent: initialComponent }) => {
  const [activeComponent, setActiveComponent] = useState<string>(initialComponent || 'OrderStatus');
  const [stockGrabbers, setStockGrabbers] = useState<StockGrabberInstance[]>([]);
  const [newClientId, setNewClientId] = useState<string>('PK479690');
  const [newStockSymbol, setNewStockSymbol] = useState<string>('CREST');

  const handleButtonClick = (componentName: string) => {
    if (activeComponent !== componentName) {
      setActiveComponent(componentName);
    }
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
    console.log('Logged in clients fetched');
  }, []);

  useEffect(() => {
    fetchLoggedInClients();
  }, [fetchLoggedInClients]);

  const addStockGrabber = () => {
    const id = `${newClientId}-${newStockSymbol}-${Date.now()}`;
    setStockGrabbers((prev) => [
      ...prev,
      { id, client_id: newClientId, stock_symbol: newStockSymbol }
    ]);
    setActiveComponent('StockGrabber');
  };

  const removeStockGrabber = (id: string) => {
    setStockGrabbers((prev) => prev.filter((sg) => sg.id !== id));
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
        <button onClick={() => handleButtonClick('StockGrabber')}>Stock Grabber</button>
      </div>

      {activeComponent === 'StockGrabber' && (
        <div className="mb-4">
          <h2 className="text-xl font-semibold mb-2">Add Stock Grabber</h2>
          <div className="flex space-x-4 mb-4">
            <input
              type="text"
              placeholder="Client ID"
              value={newClientId}
              onChange={(e) => setNewClientId(e.target.value)}
              className="border border-gray-300 rounded-md p-2"
            />
            <input
              type="text"
              placeholder="Stock Symbol"
              value={newStockSymbol}
              onChange={(e) => setNewStockSymbol(e.target.value)}
              className="border border-gray-300 rounded-md p-2"
            />
            <button
              onClick={addStockGrabber}
              className="bg-green-600 text-white py-2 px-4 rounded-md hover:bg-green-700"
            >
              Add
            </button>
          </div>
          <div className="space-y-4">
            {stockGrabbers.map((sg) => (
              <StockGrabber
                key={sg.id}
                instanceId={sg.id}
                client_id={sg.client_id}
                stock_symbol={sg.stock_symbol}
                onRemove={() => removeStockGrabber(sg.id)}
              />
            ))}
          </div>
        </div>
      )}

      {activeComponent === 'Login' && <Login />}
      {activeComponent === 'ScheduleOrder' && <ScheduleOrder />}
      {activeComponent === 'OrderStatus' && <OrderStatus />}
      {activeComponent === 'CheckOrders' && <CheckOrders />}
      {activeComponent === 'DPHoldings' && <DPHoldings />}
      {activeComponent === 'StockTable' && <StockTable />}
    </div>
  );
};

export default DashBoardPage;