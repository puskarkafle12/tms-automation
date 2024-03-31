import React, { useState, useEffect } from 'react';
import './OrderStatus.css';

const GetOrderStatus: React.FC = () => {
  const [clientID, setClientID] = useState('');
  const [scriptName, setScriptName] = useState('');
  const [orderedDate, setOrderedDate] = useState('');
  const [orderLogs, setOrderLogs] = useState<any[]>([]);
  const [scheduledOrders, setScheduledOrders] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const apiUrl = process.env.REACT_APP_API_URL;

  useEffect(() => {
    // Automatically submit the form for the default client ID
    if (!clientID) {
      const defaultClientID = JSON.parse(localStorage.getItem('clientIDs') || '[]')[0];
      if (defaultClientID) {
        setClientID(defaultClientID);
        handleSubmit();
      }
    }
  }, []);

  const handleSubmit = async () => {
    setIsLoading(true);
    try {
      const response = await fetch(apiUrl+`/order_status_logs/?client_id=${clientID}&script_name=${scriptName}&ordered_date=${orderedDate}`, {
        headers: {
          'Accept': 'application/json'
        }
      });
      if (response.ok) {
        const data = await response.json();
        setOrderLogs(data.order_logs.map((log: any) => ({ ...log, order_type: log.order_type })));
        setScheduledOrders(data.scheduled_orders.map((order: any) => ({ ...order, order_type: order.order_type })));

        // Save the clientID into local storage
        const savedClientIDs = JSON.parse(localStorage.getItem('clientIDs') || '[]');
        if (!savedClientIDs.includes(clientID)) {
          savedClientIDs.push(clientID);
          localStorage.setItem('clientIDs', JSON.stringify(savedClientIDs));
        }
      } else {
        alert("Failed to fetch data");
        console.error('Failed to fetch data');
      }
    } catch (error) {
      console.error('Error fetching data:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleDelete = async (orderId: number) => {
    try {
      const response = await fetch(apiUrl+`/delete_scheduled_order/?order_id=${orderId}`, {
        method: 'DELETE'
      });
      if (response.ok) {
        alert("Record deleted");
      } else {
        console.error('Failed to delete order');
      }
    } catch (error) {
      console.error('Error deleting order:', error);
    }
  };

  return (
    <div className='order-status-container'>
      <h2>Get Order Status</h2>
      <form onSubmit={(e) => { e.preventDefault(); handleSubmit(); }}>
        <label>
          Client ID:
          <input
            list="clientIds"
            type="text"
            value={clientID}
            onChange={(e) => setClientID(e.target.value)}
          />
          <datalist id="clientIds">
            {JSON.parse(localStorage.getItem('clientIDs') || '[]').map((id: number, index: number) => (
              <option key={index} value={id} />
            ))}
          </datalist>
        </label>
        <label>
          Script Name:
          <input type="text" value={scriptName} onChange={(e) => setScriptName(e.target.value)} />
        </label>
        <label>
          Ordered Date:
          <input type="text" value={orderedDate} onChange={(e) => setOrderedDate(e.target.value)} />
        </label>
        <button type="submit">Submit</button>
      </form>

      {isLoading && <p>Loading...</p>}

      {!isLoading && orderLogs.length > 0 && (
        <>
          <h2>Order Logs</h2>
          <table className="order-table">
            <thead>
              <tr>
                <th>Order ID</th>
                <th>Script Name</th>
                <th>Status</th>
                <th>Price</th>
                <th>Qty</th>
                <th>Order Type</th>
                <th>Timestamp</th>
              </tr>
            </thead>
            <tbody>
              {orderLogs.map((log, index) => (
                <tr key={index}>
                  <td>{log.order_id}</td>
                  <td>{log.script_name}</td>
                  <td>{log.status}</td>
                  <td>{log.price}</td>
                  <td>{log.qty}</td>
                  <td>{log.order_type}</td>
                  <td>{log.timestamp}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {!isLoading && scheduledOrders.length > 0 && (
        <>
          <h2>Scheduled Orders</h2>
          <table className="order-table">
            <thead>
              <tr>
                <th>Order ID</th>
                <th>Script Name</th>
                <th>Status</th>
                <th>Price</th>
                <th>Qty</th>
                <th>Order Type</th>
                <th>Last Updated</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {scheduledOrders.map((order, index) => (
                <tr key={index}>
                  <td>{order.order_id}</td>
                  <td>{order.script_name}</td>
                  <td>{order.status}</td>
                  <td>{order.price}</td>
                  <td>{order.qty}</td>
                  <td>{order.order_type}</td>
                  <td>{order.last_updated}</td>
                  <td>
                    {order.status === 'order_placed' && <button style={{ color: 'red' }}>Cancel</button>}
                    {order.status === 'pending' && <button onClick={() => handleDelete(order.order_id)}>Delete</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
};

export default GetOrderStatus;
