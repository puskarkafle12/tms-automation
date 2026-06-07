import React, { useState, useEffect } from 'react';
import './DpHolding.css';
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

interface QuoteLevel {
  sequenceId?: number;
  quantity?: number;
  price?: number;
  totalOrders?: number;
  buySell?: number;
}

interface StockQuote {
  ltp?: number;
  averageTradedPrice?: number;
  openPrice?: number;
  dayHigh?: number;
  dayLow?: number;
  closePrice?: number;
  lastTradedQty?: number;
  volume?: number;
  lastTradedTime?: string;
  totalBuyQty?: number;
  totalSellQty?: number;
  topBuy?: QuoteLevel[];
  topSell?: QuoteLevel[];
  security?: {
    id?: number;
    symbol?: string;
    securityName?: string;
    companyName?: string;
  };
}

const getApiUrl = () => localStorage.getItem('apiUrl') || window.location.origin;

const formatCurrency = (value: number) =>
  value.toLocaleString('en-NP', { maximumFractionDigits: 2 });

const holdingSymbol = (holding: DPHolding) => holding.scrip || holding.symbolName || '';

const formatValue = (value: unknown) => {
  if (typeof value === 'number') {
    return value.toLocaleString('en-NP', { maximumFractionDigits: 2 });
  }
  if (typeof value === 'string') {
    return value || '-';
  }
  return '-';
};

const DPHoldings: React.FC = () => {
  const [loggedInClientIDs, setLoggedInClientIDs] = useState<string[]>([]);
  const [clientID, setClientID] = useState('');
  const [dpHoldings, setDPHoldings] = useState<DPHolding[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const [successMessage, setSuccessMessage] = useState('');
  const [hasFetched, setHasFetched] = useState(false);
  const [sellHolding, setSellHolding] = useState<DPHolding | null>(null);
  const [sellPrice, setSellPrice] = useState('');
  const [sellQty, setSellQty] = useState('');
  const [quote, setQuote] = useState<StockQuote | null>(null);
  const [quoteLoading, setQuoteLoading] = useState(false);
  const [quoteError, setQuoteError] = useState('');
  const [sellSubmitting, setSellSubmitting] = useState(false);

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

  const openSellDialog = async (holding: DPHolding) => {
    const symbol = holdingSymbol(holding);
    setSellHolding(holding);
    setSellPrice(String(holding.ltp || ''));
    setSellQty('');
    setQuote(null);
    setQuoteError('');
    setSuccessMessage('');

    if (!clientID || !symbol) {
      setQuoteError('Stock quote is not available for this holding.');
      return;
    }

    setQuoteLoading(true);
    try {
      const params = new URLSearchParams({ client_id: clientID, symbol });
      const response = await fetch(`${getApiUrl()}/stock_quote?${params.toString()}`, {
        headers: { Accept: 'application/json' },
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        setQuoteError(data.detail || data.message || 'Stock quote unavailable.');
        return;
      }
      const data = await response.json();
      const nextQuote = data.quote || null;
      setQuote(nextQuote);
      if (nextQuote?.ltp) {
        setSellPrice(String(nextQuote.ltp));
      }
    } catch {
      setQuoteError('Stock quote unavailable.');
    } finally {
      setQuoteLoading(false);
    }
  };

  const closeSellDialog = () => {
    setSellHolding(null);
    setSellPrice('');
    setSellQty('');
    setQuote(null);
    setQuoteError('');
    setSellSubmitting(false);
  };

  const submitSellOrder = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!sellHolding) {
      return;
    }

    const symbol = holdingSymbol(sellHolding);
    const qty = Number.parseInt(sellQty, 10);
    const price = Number.parseFloat(sellPrice);
    const availableQty = Number(sellHolding.currentBalance || 0);

    if (!symbol || !qty || qty < 1 || !price || price <= 0) {
      setQuoteError('Enter a valid sell quantity and price.');
      return;
    }
    if (availableQty > 0 && qty > availableQty) {
      setQuoteError(`Quantity cannot exceed holding balance (${availableQty}).`);
      return;
    }

    setSellSubmitting(true);
    setQuoteError('');
    try {
      const response = await fetch(`${getApiUrl()}/add_order/`, {
        method: 'POST',
        headers: {
          Accept: 'application/json',
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          client_id: clientID,
          script_name: symbol,
          price,
          qty,
          order_type: 'sell',
          security_details: quote?.security || {},
        }),
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        setQuoteError(data.detail || data.message || 'Failed to schedule sell order.');
        return;
      }

      setSuccessMessage(`Sell order scheduled for ${symbol}.`);
      closeSellDialog();
    } catch {
      setQuoteError('Failed to schedule sell order. Check your API connection.');
    } finally {
      setSellSubmitting(false);
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
      {successMessage && <ErrorMessage message={successMessage} variant="success" />}

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
            <div className="common-table-wrap">
              <table className="common-table dp-holdings-table">
                <thead>
                  <tr>
                    <th>Scrip</th>
                    <th>LTP</th>
                    <th>Prev. Close</th>
                    <th>LTP Value</th>
                    <th>P/L</th>
                    <th>%</th>
                    <th>Balance</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {dpHoldings.map((holding, index) => (
                    <tr key={`${holdingSymbol(holding)}-${index}`} style={{ backgroundColor: holding.color }}>
                      <td>
                        <strong>{formatValue(holding.scrip)}</strong>
                        <span className="dp-holdings-symbol-name">{holding.symbolName}</span>
                      </td>
                      <td>{formatValue(holding.ltp)}</td>
                      <td>{formatValue(holding.previousCloseprice)}</td>
                      <td>{formatValue(holding.valueAsOfLTP)}</td>
                      <td className={(holding.gainedProfit || 0) >= 0 ? 'positive' : 'negative'}>
                        {formatValue(holding.gainedProfit)}
                      </td>
                      <td>{holding.percentChange}%</td>
                      <td>{formatValue(holding.currentBalance)}</td>
                      <td>
                        <button
                          type="button"
                          className="table-action-btn dp-sell-btn"
                          onClick={() => openSellDialog(holding)}
                        >
                          Sell
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
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

      {sellHolding && (
        <div className="dp-sell-modal-backdrop" role="presentation" onClick={closeSellDialog}>
          <div className="dp-sell-modal panel" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
            <div className="dp-sell-modal-header">
              <div>
                <h3>Sell {holdingSymbol(sellHolding)}</h3>
                <p>{sellHolding.symbolName || quote?.security?.securityName || 'DP holding sell order'}</p>
              </div>
              <button type="button" className="dp-sell-close" onClick={closeSellDialog} aria-label="Close">×</button>
            </div>

            {quoteError && <ErrorMessage message={quoteError} variant="error" />}

            <div className="dp-sell-summary">
              <div>
                <span>LTP</span>
                <strong>{quoteLoading ? 'Loading...' : formatValue(quote?.ltp ?? sellHolding.ltp)}</strong>
              </div>
              <div>
                <span>Balance</span>
                <strong>{formatValue(sellHolding.currentBalance)}</strong>
              </div>
              <div>
                <span>Day Range</span>
                <strong>{quote ? `${formatValue(quote.dayLow)} - ${formatValue(quote.dayHigh)}` : '-'}</strong>
              </div>
              <div>
                <span>Volume</span>
                <strong>{formatValue(quote?.volume)}</strong>
              </div>
            </div>

            <div className="dp-depth-grid">
              <DepthTable title="Top Buy" rows={quote?.topBuy || []} />
              <DepthTable title="Top Sell" rows={quote?.topSell || []} />
            </div>

            <form className="dp-sell-form" onSubmit={submitSellOrder}>
              <div className="form-group">
                <label htmlFor="dpSellQty">Quantity</label>
                <input
                  id="dpSellQty"
                  className="input"
                  type="number"
                  min="1"
                  max={sellHolding.currentBalance || undefined}
                  value={sellQty}
                  onChange={(e) => setSellQty(e.target.value)}
                  placeholder="Shares to sell"
                  required
                />
              </div>
              <div className="form-group">
                <label htmlFor="dpSellPrice">Price</label>
                <input
                  id="dpSellPrice"
                  className="input"
                  type="number"
                  min="0"
                  step="0.1"
                  value={sellPrice}
                  onChange={(e) => setSellPrice(e.target.value)}
                  placeholder="Sell price"
                  required
                />
              </div>
              <button type="submit" className="btn btn-primary dp-sell-submit" disabled={sellSubmitting}>
                {sellSubmitting ? 'Scheduling...' : 'Schedule Sell Order'}
              </button>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

const DepthTable: React.FC<{ title: string; rows: QuoteLevel[] }> = ({ title, rows }) => {
  const activeRows = rows.filter((row) => Number(row.quantity || 0) > 0 || Number(row.price || 0) > 0);

  return (
    <div className="dp-depth-table">
      <h4>{title}</h4>
      {activeRows.length > 0 ? (
        <table>
          <thead>
            <tr>
              <th>Price</th>
              <th>Qty</th>
              <th>Orders</th>
            </tr>
          </thead>
          <tbody>
            {activeRows.map((row, index) => (
              <tr key={`${title}-${row.sequenceId ?? index}`}>
                <td>{formatValue(row.price)}</td>
                <td>{formatValue(row.quantity)}</td>
                <td>{formatValue(row.totalOrders)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p>No depth available.</p>
      )}
    </div>
  );
};

export default DPHoldings;
