import React, { useState, useEffect } from 'react';
import './OrderStatus.css';

const GetOrderStatus: React.FC = () => {
  const [clientID, setClientID] = useState('');
  const [scriptName, setScriptName] = useState('');
  const [orderedDate, setOrderedDate] = useState('');
  const [orderLogs, setOrderLogs] = useState<any[]>([]);
  const [scheduledOrders, setScheduledOrders] = useState<any[]>([]);
  const [orderBook, setOrderBook] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [loggedInClientIDs, setLoggedInClientIDs] = useState<string[]>([]);
  const apiUrl = process.env.REACT_APP_API_URL;

  const fetchLoggedInClientIDs = async () => {
    try {
      const response = await fetch(apiUrl + '/logged_in_clients/');
      if (response.ok) {
        const data = await response.json();
        setLoggedInClientIDs(data.logged_in_client_ids);

        if (data.logged_in_client_ids.length > 0) {
          setClientID(data.logged_in_client_ids[0]);
        }
      } else {
        console.error('Failed to fetch logged-in client IDs');
      }
    } catch (error) {
      console.error('Error fetching logged-in client IDs:', error);
    }
  };

  useEffect(() => {
    console.log("hello")
    fetchLoggedInClientIDs();
  },[]);

  const fetchOrderBook = async (clientID: string) => {
    try {
      const response = await fetch(`${apiUrl}/get_order_book?client_id=${clientID}`);
      if (response.ok) {
        const data = await response.json();
        setOrderBook(data);
      } else {
        console.error('Failed to fetch order book data');
      }
    } catch (error) {
      console.error('Error fetching order book data:', error);
    }
  };

  const fetchOrderStatusLogs = async (clientID: string) => {
    setIsLoading(true);
    try {
      const response = await fetch(`${apiUrl}/order_status_logs/?client_id=${clientID}&script_name=${scriptName}&ordered_date=${orderedDate}`, {
        headers: {
          'Accept': 'application/json'
        }
      });
      if (response.ok) {
        const data = await response.json();
        setOrderLogs(data.order_logs.map((log: any) => ({ ...log, order_type: log.order_type })));
        setScheduledOrders(data.scheduled_orders.map((order: any) => ({ ...order, order_type: order.order_type })));
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

  const handleSubmit = async () => {
    if (!clientID) {
      alert("Please select a client ID");
      return;
    }

    await fetchOrderStatusLogs(clientID);
    await fetchOrderBook(clientID);
  };

  const handleDelete = async (orderId: number) => {
    try {
      const response = await fetch(`${apiUrl}/delete_scheduled_order/?order_id=${orderId}`, {
        method: 'DELETE'
      });
      if (response.ok) {
        alert("Record deleted");
        setScheduledOrders(scheduledOrders.filter(order => order.order_id !== orderId));
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
          <select value={clientID} onChange={(e) => setClientID(e.target.value)}>
            {loggedInClientIDs.map((id, index) => (
              <option key={index} value={id}>{id}</option>
            ))}
          </select>
        </label>
        <br />
        <label>
          Script Name:
          <input type="text" value={scriptName} onChange={(e) => setScriptName(e.target.value)} />
        </label>
        <br />
        <label>
          Ordered Date:
          <input type="text" value={orderedDate} onChange={(e) => setOrderedDate(e.target.value)} />
        </label>
        <br />
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

      {!isLoading && orderBook.length > 0 && (
        <>
          <h2>Order Book</h2>
          <table className="order-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Client Member Code</th>
                <th>Symbol</th>
                <th>Security Name</th>
                <th>Order Quantity</th>
                <th>Order Price</th>
                <th>Active Status</th>
                <th>Display Active Status</th>
                <th>Total Traded Quantity</th>
                <th>Remaining Order Quantity</th>
                <th>Disclosed Quantity</th>
                <th>Remaining Disclosed Quantity</th>
                <th>Display Name</th>
                <th>Order Placed By</th>
              </tr>
            </thead>
            <tbody>
              {orderBook.map((order, index) => (
                <tr key={index}>
                  <td>{order.id}</td>
                  <td>{order.clientMemberCode}</td>
                  <td>{order.symbol}</td>
                  <td>{order.securityName}</td>
                  <td>{order.orderQuantity}</td>
                  <td>{order.orderPrice}</td>
                  <td>{order.activeStatus}</td>
                  <td>{order.displayActiveStatus}</td>
                  <td>{order.totalTradedQuantity}</td>
                  <td>{order.remainingOrderQuantity}</td>
                  <td>{order.disclosedQuantity}</td>
                  <td>{order.remainingDisclosedQuantity}</td>
                  <td>{order.displayName}</td>
                  <td>{order.orderPlacedBy}</td>
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
