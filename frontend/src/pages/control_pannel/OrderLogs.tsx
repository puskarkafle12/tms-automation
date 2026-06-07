import React, { useState, useEffect } from 'react';
import './OrderLogs.css';
import CommonTable from '../../components/table/Table';
import DialogBox from '../../components/dialog_box/DialogBox';
import Message from '../../components/message/Message';
import 'react-datepicker/dist/react-datepicker.css';
import { format } from 'date-fns';
import DatePicker from 'react-datepicker';
const GetOrderStatus: React.FC = () => {
  const [orderedDate, setOrderedDate] = useState<string | null>(null);
  const [clientID, setClientID] = useState('');
  const [scriptName, setScriptName] = useState('');
  const [orderLogs, setOrderLogs] = useState<any[]>([]);
  const [scheduledOrders, setScheduledOrders] = useState<any[]>([]);
  const [orderBook, setOrderBook] = useState<any[]>([]);
  const [orderHistory, setOrderHistory] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [loggedInClientIDs, setLoggedInClientIDs] = useState<string[]>([]);
  const [dialogVisible, setDialogVisible] = useState(false);
  const [messageVisible, setMessageVisible] = useState(false);
  const [dialogMessage, setDialogMessage] = useState('');
  const [message, setMessage] = useState('');
  const [dialogAction, setDialogAction] = useState<() => void>(() => { });
  const apiUrl = localStorage.getItem('apiUrl') || '';

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
        setLoggedInClientIDs([]); // Set loggedInClientIDs to an empty array when API fails
        setMessageVisible(true); // Show the error dialog
        setMessage('Failed to fetch logged-in client IDs'); // Set the error message
      }
    } catch (error: any) {
      console.error('Error fetching logged-in client IDs:', error);
      setLoggedInClientIDs([]); // Set loggedInClientIDs to an empty array when API fails
      setMessageVisible(true); // Show the error dialog
      setMessage(`Error fetching logged-in client IDs: ${error.message}`); // Set the error message
    }
  };


  useEffect(() => {
    fetchLoggedInClientIDs();
  }, []);

  const handleDateChange = (date: Date | null) => {
    if (date) {
      const formattedDate = format(date, 'yyyy-MM-dd'); // Format the date to YYYY-MM-DD
      setOrderedDate(formattedDate); // Store the formatted date string
    } else {
      setOrderedDate(''); // Clear the formatted date string if null
    }
  };
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

  const fetchOrderHistory = async (clientID: string) => {
    try {
      const response = await fetch(`${apiUrl}/order_history?client_id=${clientID}`);
      if (response.ok) {
        const data = await response.json();
        setOrderHistory(data);
      } else {
        console.error('Failed to fetch order history data');
      }
    } catch (error) {
      console.error('Error fetching order history data:', error);
    }
  };

  const handleSubmit = async () => {
    if (!clientID) {
      alert("Please select a client ID");
      return;
    }

    await fetchOrderStatusLogs(clientID);
    await fetchOrderBook(clientID);
    await fetchOrderHistory(clientID);
  };

  const handleCancelOrder = async (exchangeSecurityID: number) => {
    try {
      const response = await fetch(`${apiUrl}/cancel_order/?client_id=${clientID}&exchange_order_id=${exchangeSecurityID}`, {
        method: 'DELETE'
      });
      if (response.ok) {
        console.log('Order canceled successfully');
        // Fetch updated order book data after cancellation
        await fetchOrderBook(clientID); // Add this line
      } else {
        console.error('Failed to cancel order');
      }
    } catch (error) {
      console.error('Error canceling order:', error);
    }
  };


  const handleAction = async (row: any, actionType: string) => {
    if (actionType === 'Delete') {
      setDialogMessage('Are you sure you want to delete this order?');
      setDialogAction(() => async () => {
        try {
          let orderId = row.order_id;
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
        handleCancelOrder(row.exchangeOrderId);
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
          <DatePicker
            selected={orderedDate ? new Date(orderedDate) : null} // Convert string back to Date for DatePicker
            onChange={handleDateChange}
            dateFormat="yyyy-MM-dd"
            placeholderText="Select a date"
          />
        </label>
        <br />
        <button type="submit">Submit</button>
      </form>

      {isLoading && <p>Loading...</p>}

      <h1>Order Logs:</h1>
      <CommonTable
        data={orderLogs}
        onAction={handleAction}
        columns={['client_id', 'script_name', 'qty', 'price', 'order_type', 'status', 'timestamp']}
      />

      <h1>Scheduled Orders:</h1>
      <CommonTable
        data={scheduledOrders}
        onAction={handleAction}
        columns={['client_id', 'script_name', 'order_type', 'price', 'status', 'qty']}
      />

      <h1>Order Book:</h1>
      <CommonTable
        data={orderBook}
        columns={[
          'clientMemberCode',
          'symbol',
          'buyOrSell',
          'orderQuantity',
          'orderPrice',
          'orderTime',
          'activeStatus',
          'totalTradedQuantity',
          'remainingOrderQuantity',
        ]}
        onAction={handleAction}
      />

      <h1>Order History:</h1>
      <CommonTable
        data={orderHistory}
        columns={[
          'clientMemberCode',
          'symbol',
          'buyOrSell',
          'orderQuantity',
          'orderPrice',
          'orderTime',
          'activeStatus',
          'totalTradedQuantity',
          'remainingOrderQuantity'
        ]}
      />

      {dialogVisible && (
        <DialogBox
          message={dialogMessage}
          onConfirm={dialogAction}
          onCancel={() => setDialogVisible(false)}
        />
      )}
      {messageVisible && (
        <Message
          message={message}
          onClose={() => setMessageVisible(false)} // Close the message when the close button is clicked
        />
      )}
    </div>
  );
};

export default GetOrderStatus;
