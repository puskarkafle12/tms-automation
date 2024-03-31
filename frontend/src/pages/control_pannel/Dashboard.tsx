import React, { useState } from 'react';
import ScheduleOrder from './ScheduleOrder'; // Import the ScheduleOrder component
import OrderStatus from './OrderStatus';
import CheckOrders from './CheckOrders';
import MonitorOrders from './MonitorOrders';
import './Dashboard.css'; // Import the CSS file for styling

const Home: React.FC = () => {
  const [showAddOrder, setShowAddOrder] = useState(false);
  const [showOrderStatus, setshowOrderStatus] = useState(false);
  const [showCheckOrders, setCheckOrders] = useState(false);

  return (
    <div className="container">
      <h1>Dashboard</h1>
      <div className="dashboard-buttons">
        <button onClick={() => { setShowAddOrder(!showAddOrder); setshowOrderStatus(false); setCheckOrders(false); }}>Schedule Order</button>
        <button onClick={() => { setshowOrderStatus(!showOrderStatus); setShowAddOrder(false); setCheckOrders(false); }}>Show Order Logs</button>
        <button onClick={() => { setCheckOrders(!showCheckOrders); setShowAddOrder(false); setshowOrderStatus(false); }}>Check Order Logs</button>
      </div>

      {showAddOrder && <ScheduleOrder />}
      {showOrderStatus && <OrderStatus />}
      {showCheckOrders && <CheckOrders />}
    </div>
  );
};

export default Home;
