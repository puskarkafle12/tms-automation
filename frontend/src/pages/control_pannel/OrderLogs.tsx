import React, { useState, useEffect } from 'react';
import './OrderLogs.css';
import CommonTable from '../../components/table/Table';
import DialogBox from '../../components/dialog_box/DialogBox';

const GetOrderStatus: React.FC = () => {
  const [clientID, setClientID] = useState('');
  const [scriptName, setScriptName] = useState('');
  const [orderedDate, setOrderedDate] = useState('');
  const [orderLogs, setOrderLogs] = useState<any[]>([]);
  const [scheduledOrders, setScheduledOrders] = useState<any[]>([]);
  const [orderBook, setOrderBook] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [loggedInClientIDs, setLoggedInClientIDs] = useState<string[]>([]);
  const [dialogVisible, setDialogVisible] = useState(false);
  const [dialogMessage, setDialogMessage] = useState('');
  const [dialogAction, setDialogAction] = useState<() => void>(() => {});
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
    fetchLoggedInClientIDs();
  }, []);

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
        setScheduledOrders(data.scheduled_orders.map((order: any) => ({ ...order, order_type: order.order_type, actionRequired: true })));
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

  const handleAction = async (orderId: number, actionType: string) => {
    if (actionType === 'Delete') {
      setDialogMessage('Are you sure you want to delete this order?');
      setDialogAction(() => async () => {
        try {
          console.log(orderId)
          const response = await fetch(`${apiUrl}/delete_scheduled_order/?order_id=${orderId}`, {
            method: 'DELETE'
          });
          if (response.ok) {
            setScheduledOrders(scheduledOrders.filter(order => order.order_id !== orderId));
          } else {
            console.error('Failed to delete order');
          }
        } catch (error) {
          console.error('Error deleting order:', error);
        } finally {
          setDialogVisible(false);
        }
      });
      setDialogVisible(true);
    } else if (actionType === 'Cancel') {
      setDialogMessage('Are you sure you want to cancel this order?');
      setDialogAction(() => () => {
        // Handle cancel action
        setDialogVisible(false);
      });
      setDialogVisible(true);
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
          {loggedInClientIDs.length === 0 && (
            <span style={{ color: 'red', marginLeft: '10px' }}>No logged in user found</span>
          )}
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
      <h1>Order Logs:</h1>
      <CommonTable data={orderLogs} columns={['client_id','script_name', 'qty', 'price', 'order_type', 'status', 'timestamp']}/>

      <h1>Order ScheduledOrders:</h1>
      <CommonTable data={scheduledOrders} onAction={handleAction} columns={['client_id', 'script_name', 'order_type', 'price', 'status', 'qty', 'Action']} />

      <h1>Order Book:</h1>
      <CommonTable data={orderBook}  columns={['clientMemberCode', 'symbol', 'buyOrSell', 'orderQuantity', 'orderPrice', 'orderTime', 'activeStatus', 'totalTradedQuantity', 'remainingOrderQuantity']}/>

      {dialogVisible && (
        <DialogBox
          message={dialogMessage}
          onConfirm={dialogAction}
          onCancel={() => setDialogVisible(false)}
        />
      )}
    </div>
  );
};

export default GetOrderStatus;
