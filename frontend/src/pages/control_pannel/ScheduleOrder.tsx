import React, { useState, useEffect } from 'react';

const apiUrl = process.env.REACT_APP_API_URL || 'http://localhost:8000';

const ScheduleOrder: React.FC = () => {
  const [clientID, setClientID] = useState('');
  const [newClientID, setNewClientID] = useState('');
  const [scriptName, setScriptName] = useState('');
  const [price, setPrice] = useState('');
  const [qty, setQty] = useState('');
  const [status, setStatus] = useState('');
  const [clientIDs, setClientIDs] = useState<string[]>([]);

  useEffect(() => {
    // Retrieve client IDs from local storage
    const storedClientIDs = localStorage.getItem('clientIDs');
    if (storedClientIDs) {
      setClientIDs(JSON.parse(storedClientIDs));
      setClientID(JSON.parse(storedClientIDs)[0]); // Set default client ID to the first one
    }
  }, []);

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    try {
      console.log(apiUrl)
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
          qty: parseInt(qty)
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

  const handleDeleteClientID = (id: string) => {
    const updatedClientIDs = clientIDs.filter(clientID => clientID !== id);
    setClientIDs(updatedClientIDs);
    localStorage.setItem('clientIDs', JSON.stringify(updatedClientIDs));
    setClientID(updatedClientIDs[0]); // Set default client ID to the first one after deletion
  };

  const handleAddNewClientID = () => {
    if (newClientID.trim() !== '' && !clientIDs.includes(newClientID)) {
      setClientIDs([...clientIDs, newClientID]);
      localStorage.setItem('clientIDs', JSON.stringify([...clientIDs, newClientID]));
      setClientID(newClientID); // Set the new client ID as selected
      setNewClientID(''); // Clear the input field
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
          <label>
            <span style={{ display: 'flex', alignItems: 'center', padding: '5px' }}>
              New Client ID:
              <input type="text" value={newClientID} onChange={(e) => setNewClientID(e.target.value)} style={{ marginLeft: '5px', marginRight: '5px', padding: '3px' }} />
              <button type="button" style={{ marginRight: '5px' }}  onClick={handleAddNewClientID}>Add</button>
              <button style={{ marginLeft: '5px' }} onClick={() => handleDeleteClientID(clientID)}>Delete</button>
            </span>



          </label>

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
        <br />
        <button type="submit">Submit</button>
      </form>
      {status === 'success' && <p style={{ color: 'green' }}>Order added successfully</p>}
      {status === 'error' && <p style={{ color: 'red' }}>Failed to add order</p>}
    </div>
  );
};

export default ScheduleOrder;
