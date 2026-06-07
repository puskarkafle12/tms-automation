import React, { useState, useEffect } from 'react';
import './DpHolding.css';
import CommonTable from '../../components/table/Table';
import axios from 'axios';

interface DPHolding {
  clientID: string;
  valueAsOfPreviousClosePrice: number;
  valueAsOfLTP: number;
  percentChange?: number; // Add percentChange property
  color?: string; // Optional color property for row coloring
}

const DPHoldings: React.FC = () => {
  const [loggedInClientIDs, setLoggedInClientIDs] = useState<string[]>([]);
  const [clientID, setClientID] = useState('');
  const [dpHoldings, setDPHoldings] = useState<DPHolding[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const apiUrl = localStorage.getItem('apiUrl') || '';

  useEffect(() => {
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
    fetchLoggedInClientIDs();
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

        // Map the data to include the percentChange and color properties
        const processedData = data.map((holding: DPHolding) => {
          const percentChange = ((holding.valueAsOfLTP - holding.valueAsOfPreviousClosePrice) / holding.valueAsOfPreviousClosePrice * 100).toFixed(1);
          const gainedProfit = holding.valueAsOfLTP - holding.valueAsOfPreviousClosePrice;

          return {
            ...holding,
            percentChange: percentChange,
            gainedProfit: gainedProfit,
            color: holding.valueAsOfLTP > holding.valueAsOfPreviousClosePrice
              ? 'lightgreen'
              : holding.valueAsOfLTP < holding.valueAsOfPreviousClosePrice
                ? 'red'
                : 'lightyellow' // For no change
          };
        });

        setDPHoldings(processedData);
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
    }, { valueAsOfPreviousClosePrice: 0, valueAsOfLTP: 0, profit: 0 });

    totals.profit = totals.valueAsOfLTP - totals.valueAsOfPreviousClosePrice;

    return totals;
  };

  const totals = calculateTotals(dpHoldings);

  return (
    <div className='order-status-container'>
      <h2>Get DP Holdings</h2>
      <form onSubmit={(e) => { e.preventDefault(); handleSubmit(); }}>
        <label>
          Client ID:
          <select value={clientID} onChange={(e) => setClientID(e.target.value)}>
              {loggedInClientIDs.map((id, index) => (
                <option key={index} value={id}>{id}</option>
              ))}
            </select>
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
            data={dpHoldings}
            columns={["scrip", "previousCloseprice", "ltp", "valueAsOfPreviousClosePrice", "valueAsOfLTP", "gainedProfit", "percentChange", "symbolName", "currentBalance"]}
          />
          <table className="common-table" >
            <tfoot>
            <tr style={{ background: totals.profit < 0 ? '#ffcccb' : '#d4edda' ,}}>
                <td>Total</td>
                <td>{totals.valueAsOfPreviousClosePrice}</td>
                <td>{totals.valueAsOfLTP}</td>
                <td>{totals.valueAsOfLTP}</td>
                <td>
                  {totals.profit}
                </td>
              </tr>
            </tfoot>
          </table>
        </>
      )}
    </div>
  );
};

export default DPHoldings;
