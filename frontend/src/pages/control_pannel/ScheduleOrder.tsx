import React, { useState, useEffect, useRef } from 'react';
import StockDetails from './StockDetails';

const apiUrl = process.env.REACT_APP_API_URL;

const ScheduleOrder: React.FC = () => {
  const [clientID, setClientID] = useState('');
  const [scriptName, setScriptName] = useState('');
  const [filteredScriptNames, setFilteredScriptNames] = useState<string[]>([]);
  const [price, setPrice] = useState('');
  const [qty, setQty] = useState('');
  const [status, setStatus] = useState('');
  const [loggedInClientIDs, setLoggedInClientIDs] = useState<string[]>([]);
  const [orderType, setOrderType] = useState('buy'); // Default order type is 'buy'
  const [stockDetails, setStockDetails] = useState<any[]>([]);
  const [selectedStock, setSelectedStock] = useState<any | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const dropdownRef = useRef<HTMLDataListElement>(null);

  useEffect(() => {
    // Fetch logged-in client IDs from the API
    const fetchLoggedInClientIDs = async () => {
      try {
        const response = await fetch(apiUrl + '/logged_in_clients/');
        if (response.ok) {
          const data = await response.json();
          setLoggedInClientIDs(data.logged_in_client_ids);
          setClientID(data.logged_in_client_ids[0]); // Set default client ID to the first one
        } else {
          console.error('Failed to fetch logged-in client IDs');
        }
      } catch (error) {
        console.error('Error fetching logged-in client IDs:', error);
      }
    };

    // Fetch stock details from the API
    const fetchStockDetails = async () => {
      try {
        const response = await fetch('http://localhost:8000/get_script_details?client_id=PK479690');
        if (response.ok) {
          const data = await response.json();
          setStockDetails(data.payload.data);
        } else {
          console.error('Failed to fetch stock details');
        }
      } catch (error) {
        console.error('Error fetching stock details:', error);
      }
    };

    fetchLoggedInClientIDs();
    fetchStockDetails();
  }, []); // Empty dependency array ensures this runs only once when the component mounts

  const handleScriptNameChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const name = e.target.value;
    setScriptName(name);
    const filteredNames = stockDetails
      .map(stock => stock.symbol)
      .filter(symbol => symbol.toLowerCase().includes(name.toLowerCase()));
    setFilteredScriptNames(filteredNames);
    const stockDetail = stockDetails.find(stock => stock.symbol === name);
    setSelectedStock(stockDetail || null);
  };

  const handleScriptNameSelect = (symbol: string) => {
    setScriptName(symbol);
    setFilteredScriptNames([]);
    const stockDetail = stockDetails.find(stock => stock.symbol === symbol);
    setSelectedStock(stockDetail || null);
  };

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

  useEffect(() => {
    const handleEnterPress = (event: KeyboardEvent) => {
      if (event.key === 'Enter' && dropdownRef.current && document.activeElement !== dropdownRef.current) {
        if (filteredScriptNames.length > 0 && inputRef.current) {
          inputRef.current.value = filteredScriptNames[0];
          handleScriptNameSelect(filteredScriptNames[0]);
        }
        event.preventDefault(); // Prevent form submission
      }
    };

    document.addEventListener('keydown', handleEnterPress);

    return () => {
      document.removeEventListener('keydown', handleEnterPress);
    };
  }, [filteredScriptNames]);

  return (
    <div style={{ display: 'flex' }}>
      <div style={{ flex: '5' }}>
        <h2>Add Order</h2>
        <form onSubmit={handleSubmit}>
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
            <input
              type="text"
              value={scriptName}
              onChange={handleScriptNameChange}
              list="scriptNameSuggestions"
              ref={inputRef}
            />
            <datalist id="scriptNameSuggestions" ref={dropdownRef}>
              {filteredScriptNames.map((symbol, index) => (
                <option key={index} value={symbol} onClick={() => handleScriptNameSelect(symbol)}>
                  {symbol}
                </option>
              ))}
            </datalist>
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
      <div style={{ flex: '4', paddingLeft: '20px' }}>
        {selectedStock && <StockDetails stock={selectedStock} />}
      </div>
    </div>
  );
};

export default ScheduleOrder;
