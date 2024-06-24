import React, { useState, useEffect } from 'react';

const apiUrl = process.env.REACT_APP_API_URL;

const ScheduleOrder: React.FC = () => {
  const [clientID, setClientID] = useState('');
  const [newClientID, setNewClientID] = useState('');
  const [scriptName, setScriptName] = useState('');
  const [price, setPrice] = useState('');
  const [qty, setQty] = useState('');
  const [status, setStatus] = useState('');
  const [clientIDs, setClientIDs] = useState<string[]>([]);
  const [orderType, setOrderType] = useState('buy'); // Default order type is 'buy'

  useEffect(() => {
    // Fetch logged-in client IDs from the API
    const fetchLoggedInClientIDs = async () => {
      try {
        const response = await fetch(apiUrl + '/logged_in_clients/');
        if (response.ok) {
          const data = await response.json();
          setClientIDs(data.logged_in_client_ids);
          setClientID(data.logged_in_client_ids[0]); // Set default client ID to the first one
        } else {
          console.error('Failed to fetch logged-in client IDs');
        }
      } catch (error) {
        console.error('Error fetching logged-in client IDs:', error);
      }
    };

    fetchLoggedInClientIDs();
  }, []); // Empty dependency array ensures this runs only once when the component mounts

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    try {
      const response = await fetch(apiUrl + '/add_order/', {
        method: 'POST',
        headers: {
          'Accept': 'application/json',
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          client_id: clientID,
          script_name: scriptName,
          price: parseInt(price),
          qty: parseInt(qty),
          order_type: orderType // Include order type in the request body
        })
      });
      if (response.ok) {
        setStatus('success');
      } else {
        setStatus('error');
      }
    } catch (error) {
      setStatus('error');
    }
  };

  return (
    <div>
      <h2>Add Order</h2>
      <form onSubmit={handleSubmit}>
        <label>
          Client ID:
          <select value={clientID} onChange={(e) => setClientID(e.target.value)}>
            {clientIDs.map((id, index) => (
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
          Price:
          <input type="text" value={price} onChange={(e) => setPrice(e.target.value)} />
        </label>
        <br />
        <label>
          Quantity:
          <input type="text" value={qty} onChange={(e) => setQty(e.target.value)} />
        </label>
        <br/>
        <label>
          Order Type:
          <select value={orderType} onChange={(e) => setOrderType(e.target.value)}>
            <option value="buy">Buy</option>
            <option value="sell">Sell</option>
          </select>
        </label>
        <br />
        <button type="submit">Submit</button>
      </form>
      {status === 'success' && <p style={{ color: 'green' }}>Order added successfully</p>}
      {status === 'error' && <p style={{ color: 'red' }}>Failed to add order</p>}
    </div>
  );
};

export default ScheduleOrder;
