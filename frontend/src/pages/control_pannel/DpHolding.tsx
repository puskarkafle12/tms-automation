import React, { useState, useEffect } from 'react';
import './DpHolding.css';
import CommonTable from '../../components/Table/Table';
import axios from 'axios';

interface DPHolding {
  // Define the structure of your DPHolding data based on your API response
  clientID: string;
  valueAsOfPreviousClosePrice: number;
  valueAsOfLTP: number;
  // Add other properties as necessary
  color?: string; // Optional color property for row coloring
}

const DPHoldings: React.FC = () => {
  const [clientID, setClientID] = useState('');
  const [dpHoldings, setDPHoldings] = useState<DPHolding[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const apiUrl = process.env.REACT_APP_API_URL;

  useEffect(() => {
    const fetchLoggedInClients = async () => {
      try {
        const response = await fetch(`${apiUrl}/logged_in_clients/`);
        const data = await response.json();
        if (data.logged_in_client_ids.length > 0) {
          setClientID(data.logged_in_client_ids[0]);
        }
      } catch (error) {
        console.error('Error fetching logged in clients:', error);
      }
    };
    fetchLoggedInClients();
  }, [apiUrl]);

  const handleSubmit = async () => {
    setIsLoading(true);
    try {
      const response = await fetch(`${apiUrl}/dp_holdings?client_id=${clientID}`, {
        headers: {
          'Accept': 'application/json'
        }
      });
      if (response.ok) {
        const data = await response.json();
        
        // Map the data to include the color property
        const coloredData = data.map((holding: DPHolding) => ({
          ...holding,
          color: holding.valueAsOfLTP > holding.valueAsOfPreviousClosePrice
            ? 'lightgreen'
            : holding.valueAsOfLTP < holding.valueAsOfPreviousClosePrice
            ? 'red'
            : 'lightyellow' // For no change
        }));

        setDPHoldings(coloredData);
      } else {
        alert("Failed to fetch DP holdings");
        console.error('Failed to fetch DP holdings');
      }
    } catch (error) {
      console.error('Error fetching DP holdings:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const calculateTotals = (data: DPHolding[]) => {
    const totals = data.reduce((acc, row) => {
      acc.valueAsOfPreviousClosePrice += row.valueAsOfPreviousClosePrice || 0;
      acc.valueAsOfLTP += row.valueAsOfLTP || 0;
      return acc;
    }, { valueAsOfPreviousClosePrice: 0, valueAsOfLTP: 0 });
    return totals;
  };

  const totals = calculateTotals(dpHoldings);

  return (
    <div className='order-status-container'>
      <h2>Get DP Holdings</h2>
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
            {/* Update this to dynamically fetch client IDs from API */}
          </datalist>
        </label>
        <button type="submit">Submit</button>
      </form>

      {isLoading && <p>Loading...</p>}

      {!isLoading && dpHoldings.length > 0 && (
        <>
          <CommonTable
            data={dpHoldings} // Pass the colored data to the CommonTable
          />
          <table className="common-table">
            <tfoot>
              <tr>
                <td>Total</td>
                <td>{totals.valueAsOfPreviousClosePrice}</td>
                <td>{totals.valueAsOfLTP}</td>
              </tr>
            </tfoot>
          </table>
        </>
      )}
    </div>
  );
};

export default DPHoldings;
