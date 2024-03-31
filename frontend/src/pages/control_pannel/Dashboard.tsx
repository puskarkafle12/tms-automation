import React, { useState } from 'react';
import ScheduleOrder from './ScheduleOrder'; // Import the ScheduleOrder component
import OrderStatus from './OrderStatus';
import CheckOrders from './CheckOrders';

const Home: React.FC = () => {
  const [showAddOrder, setShowAddOrder] = useState(false);
  const [showOrderStatus, setshowOrderStatus] = useState(false);
  const [showCheckOrders, setCheckOrders] = useState(false);

  return (
    <div className="container">
      <p>this is the dashboard </p>

      <button onClick={() => { setShowAddOrder(!showAddOrder); setshowOrderStatus(false); setCheckOrders(false); }}>Schedule Order</button>
      <button onClick={() => { setshowOrderStatus(!showOrderStatus); setShowAddOrder(false); setCheckOrders(false); }}>Show order logs</button>
      <button onClick={() => { setCheckOrders(!showCheckOrders); setShowAddOrder(false); setshowOrderStatus(false); }}>Check order Logs</button>

      {showAddOrder && <ScheduleOrder />}
      {showOrderStatus && <OrderStatus />}
      {showCheckOrders && <CheckOrders />}
    </div>
  );
};

export default Home;
