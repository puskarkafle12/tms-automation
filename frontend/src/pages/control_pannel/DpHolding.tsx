import React, { useState, useEffect } from 'react';
import './DpHolding.css';
import CommonTable from '../../components/table/Table';
import ErrorMessage from '../../components/ErrorMessage';

interface DPHolding {
  clientID: string;
  valueAsOfPreviousClosePrice: number;
  valueAsOfLTP: number;
  percentChange?: string;
  gainedProfit?: number;
  color?: string;
  scrip?: string;
  symbolName?: string;
  previousCloseprice?: number;
  ltp?: number;
  currentBalance?: number;
}

const getApiUrl = () => localStorage.getItem('apiUrl') || 'http://localhost:8000';

const formatCurrency = (value: number) =>
  value.toLocaleString('en-NP', { maximumFractionDigits: 2 });

const DPHoldings: React.FC = () => {
  const [loggedInClientIDs, setLoggedInClientIDs] = useState<string[]>([]);
  const [clientID, setClientID] = useState('');
  const [dpHoldings, setDPHoldings] = useState<DPHolding[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const [hasFetched, setHasFetched] = useState(false);

  useEffect(() => {
    const fetchLoggedInClientIDs = async () => {
      try {
        const response = await fetch(`${getApiUrl()}/logged_in_clients/`);
        if (response.ok) {
          const data = await response.json();
          setLoggedInClientIDs(data.logged_in_client_ids);
          setClientID(data.logged_in_client_ids[0] || '');
        }
      } catch (error) {
        console.error('Error fetching logged-in client IDs:', error);
      }
    };
    fetchLoggedInClientIDs();
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setErrorMessage('');
    setHasFetched(true);

    try {
      const response = await fetch(`${getApiUrl()}/dp_holdings?client_id=${clientID}`, {
        headers: { Accept: 'application/json' },
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        setErrorMessage(data.detail || data.message || 'Failed to fetch DP holdings.');
        setDPHoldings([]);
        return;
      }

      const data = await response.json();
      const processedData = data.map((holding: DPHolding) => {
        const gainedProfit = holding.valueAsOfLTP - holding.valueAsOfPreviousClosePrice;
        const percentChange = holding.valueAsOfPreviousClosePrice
          ? ((gainedProfit / holding.valueAsOfPreviousClosePrice) * 100).toFixed(1)
          : '0.0';

        return {
          ...holding,
          percentChange,
          gainedProfit,
          color:
            holding.valueAsOfLTP > holding.valueAsOfPreviousClosePrice
              ? 'lightgreen'
              : holding.valueAsOfLTP < holding.valueAsOfPreviousClosePrice
                ? 'red'
                : 'lightyellow',
        };
      });

      setDPHoldings(processedData);
    } catch (error) {
      setErrorMessage('Failed to fetch DP holdings. Check your API connection.');
      setDPHoldings([]);
    } finally {
      setIsLoading(false);
    }
  };

  const totals = dpHoldings.reduce(
    (acc, row) => {
      acc.valueAsOfPreviousClosePrice += row.valueAsOfPreviousClosePrice || 0;
      acc.valueAsOfLTP += row.valueAsOfLTP || 0;
      return acc;
    },
    { valueAsOfPreviousClosePrice: 0, valueAsOfLTP: 0, profit: 0 },
  );
  totals.profit = totals.valueAsOfLTP - totals.valueAsOfPreviousClosePrice;

  const isProfit = totals.profit >= 0;

  return (
    <div className="dp-holdings-page">
      <div className="dp-holdings-hero panel">
        <div className="dp-holdings-hero-content">
          <div className="dp-holdings-hero-icon" aria-hidden="true">📊</div>
          <div>
            <h2 className="dp-holdings-hero-title">DP Holdings</h2>
            <p className="dp-holdings-hero-subtitle">
              View depository participant holdings and portfolio value for logged-in clients.
            </p>
          </div>
        </div>
        {loggedInClientIDs.length > 0 && (
          <span className="badge badge-success">{loggedInClientIDs.length} client(s) online</span>
        )}
      </div>

      {errorMessage && <ErrorMessage message={errorMessage} variant="error" persistent />}

      <div className="dp-holdings-filters panel">
        <div className="dp-holdings-filters-header">
          <div>
            <h3 className="panel-title">Get Holdings</h3>
            <p className="panel-subtitle">Select a client to load their current DP holdings from TMS.</p>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="dp-holdings-form">
          <div className="form-group">
            <label htmlFor="dpClientId">Client ID</label>
            <select
              id="dpClientId"
              className="select"
              value={clientID}
              onChange={(e) => setClientID(e.target.value)}
              disabled={loggedInClientIDs.length === 0}
              required
            >
              {loggedInClientIDs.length === 0 ? (
                <option value="">No logged-in clients</option>
              ) : (
                loggedInClientIDs.map((id) => (
                  <option key={id} value={id}>{id}</option>
                ))
              )}
            </select>
            {loggedInClientIDs.length === 0 && (
              <span className="dp-holdings-hint">Log in via TMS Login tab first.</span>
            )}
          </div>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={isLoading || loggedInClientIDs.length === 0}
          >
            {isLoading ? 'Loading...' : 'Fetch Holdings'}
          </button>
        </form>
      </div>

      {dpHoldings.length > 0 && (
        <div className="dp-holdings-stats">
          <div className="dp-holdings-stat-card">
            <span className="dp-holdings-stat-label">Holdings</span>
            <span className="dp-holdings-stat-value">{dpHoldings.length}</span>
          </div>
          <div className="dp-holdings-stat-card">
            <span className="dp-holdings-stat-label">Prev. Close Value</span>
            <span className="dp-holdings-stat-value">{formatCurrency(totals.valueAsOfPreviousClosePrice)}</span>
          </div>
          <div className="dp-holdings-stat-card">
            <span className="dp-holdings-stat-label">Current Value (LTP)</span>
            <span className="dp-holdings-stat-value">{formatCurrency(totals.valueAsOfLTP)}</span>
          </div>
          <div className={`dp-holdings-stat-card ${isProfit ? 'profit' : 'loss'}`}>
            <span className="dp-holdings-stat-label">Total P/L</span>
            <span className={`dp-holdings-stat-value ${isProfit ? 'positive' : 'negative'}`}>
              {isProfit ? '+' : ''}{formatCurrency(totals.profit)}
            </span>
          </div>
        </div>
      )}

      <div className="dp-holdings-content panel">
        <div className="dp-holdings-content-header">
          <h3 className="panel-title">Holdings Table</h3>
          {clientID && hasFetched && !isLoading && (
            <span className="badge badge-muted">{clientID}</span>
          )}
        </div>

        {isLoading ? (
          <div className="dp-holdings-loading">
            <span className="dp-holdings-spinner" aria-hidden="true" />
            <p>Fetching DP holdings from TMS...</p>
          </div>
        ) : dpHoldings.length > 0 ? (
          <>
            <CommonTable
              data={dpHoldings}
              columns={[
                'scrip',
                'previousCloseprice',
                'ltp',
                'valueAsOfPreviousClosePrice',
                'valueAsOfLTP',
                'gainedProfit',
                'percentChange',
                'symbolName',
                'currentBalance',
              ]}
            />
            <div className={`dp-holdings-totals ${isProfit ? 'profit' : 'loss'}`}>
              <div className="dp-holdings-total-item">
                <span className="dp-holdings-total-label">Total Prev. Close</span>
                <span className="dp-holdings-total-value">{formatCurrency(totals.valueAsOfPreviousClosePrice)}</span>
              </div>
              <div className="dp-holdings-total-item">
                <span className="dp-holdings-total-label">Total LTP Value</span>
                <span className="dp-holdings-total-value">{formatCurrency(totals.valueAsOfLTP)}</span>
              </div>
              <div className="dp-holdings-total-item">
                <span className="dp-holdings-total-label">Net P/L</span>
                <span className={`dp-holdings-total-value ${isProfit ? 'positive' : 'negative'}`}>
                  {isProfit ? '+' : ''}{formatCurrency(totals.profit)}
                </span>
              </div>
            </div>
          </>
        ) : (
          <div className="dp-holdings-empty">
            <span style={{ fontSize: '2rem', opacity: 0.5 }} aria-hidden="true">📂</span>
            <p>
              {hasFetched
                ? 'No holdings found for this client.'
                : 'Select a client and click Fetch Holdings to load data.'}
            </p>
          </div>
        )}
      </div>
    </div>
  );
};

export default DPHoldings;
