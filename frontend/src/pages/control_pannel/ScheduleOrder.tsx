import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import './ScheduleOrder.css';
import StockDetails from './StockDetails';
import ErrorMessage from '../../components/ErrorMessage';
import ScriptNameAutocomplete, { ScriptOption } from '../../components/ScriptNameAutocomplete';
import ScheduleMonitorBar from '../../components/ScheduleMonitorBar';

const getApiUrl = () => localStorage.getItem('apiUrl') || window.location.origin;

interface DPHolding {
  scrip?: string;
  symbolName?: string;
  currentBalance?: number;
}

const ScheduleOrder: React.FC = () => {
  const [clientID, setClientID] = useState('');
  const [scriptName, setScriptName] = useState('');
  const [price, setPrice] = useState('');
  const [qty, setQty] = useState('');
  const [status, setStatus] = useState<'idle' | 'success' | 'error'>('idle');
  const [statusMessage, setStatusMessage] = useState('');
  const [loggedInClientIDs, setLoggedInClientIDs] = useState<string[]>([]);
  const [orderType, setOrderType] = useState<'buy' | 'sell'>('buy');
  const [stockDetails, setStockDetails] = useState<any[]>([]);
  const [selectedStock, setSelectedStock] = useState<any | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [latestLtp, setLatestLtp] = useState<number | null>(null);
  const [quoteLoading, setQuoteLoading] = useState(false);
  const [quoteError, setQuoteError] = useState('');
  const [holdingQty, setHoldingQty] = useState<number | null>(null);
  const [holdingLabel, setHoldingLabel] = useState('');
  const [holdingLoading, setHoldingLoading] = useState(false);
  const [holdingError, setHoldingError] = useState('');
  const quoteRequestId = useRef(0);
  const holdingRequestId = useRef(0);

  const buyHighLimit = useMemo(() => {
    if (orderType !== 'buy' || !selectedStock?.high) {
      return null;
    }
    const high = Number(selectedStock.high);
    return Number.isFinite(high) && high > 0 ? high : null;
  }, [orderType, selectedStock]);

  const scriptOptions = useMemo<ScriptOption[]>(
    () =>
      stockDetails.map((stock) => ({
        symbol: stock.symbol,
        ltp: stock.ltp,
        percentChange: stock.percentChange,
      })),
    [stockDetails],
  );

  const fetchStockDetails = useCallback(async (clientId: string) => {
    if (!clientId) {
      return;
    }
    try {
      const response = await fetch(`${getApiUrl()}/get_script_details?client_id=${encodeURIComponent(clientId)}`);
      if (response.ok) {
        const data = await response.json();
        setStockDetails(data.payload.data);
      } else {
        setStockDetails([]);
      }
    } catch (error) {
      console.error('Error fetching stock details:', error);
      setStockDetails([]);
    }
  }, []);

  useEffect(() => {
    const loadInitialData = async () => {
      try {
        const response = await fetch(`${getApiUrl()}/logged_in_clients/`);
        if (response.ok) {
          const data = await response.json();
          setLoggedInClientIDs(data.logged_in_client_ids);
          const defaultClientId = data.logged_in_client_ids[0] || '';
          setClientID(defaultClientId);
          await fetchStockDetails(defaultClientId);
        }
      } catch (error) {
        console.error('Error fetching logged-in client IDs:', error);
      }
    };

    loadInitialData();
  }, [fetchStockDetails]);

  const handleClientChange = async (clientId: string) => {
    setClientID(clientId);
    setScriptName('');
    setSelectedStock(null);
    setPrice('');
    setQty('');
    setLatestLtp(null);
    setQuoteError('');
    setHoldingQty(null);
    setHoldingLabel('');
    setHoldingError('');
    await fetchStockDetails(clientId);
  };

  const handleScriptNameChange = (name: string) => {
    const normalizedName = name.toUpperCase();
    setScriptName(normalizedName);
    const stockDetail = stockDetails.find((stock) => stock.symbol === normalizedName);
    setSelectedStock(stockDetail || null);
    setHoldingQty(null);
    setHoldingLabel('');
    setHoldingError('');
  };

  const handleScriptNameSelect = (option: ScriptOption) => {
    setScriptName(option.symbol);
    const stockDetail = stockDetails.find((stock) => stock.symbol === option.symbol);
    setSelectedStock(stockDetail || null);
    setHoldingQty(null);
    setHoldingLabel('');
    setHoldingError('');
  };

  const loadLatestQuote = useCallback(async (clientId: string, symbol: string) => {
    const normalizedSymbol = symbol.trim().toUpperCase();
    if (!clientId || !normalizedSymbol) {
      setLatestLtp(null);
      setQuoteError('');
      return;
    }

    const requestId = quoteRequestId.current + 1;
    quoteRequestId.current = requestId;
    setQuoteLoading(true);
    setQuoteError('');

    try {
      const params = new URLSearchParams({ client_id: clientId, symbol: normalizedSymbol });
      const response = await fetch(`${getApiUrl()}/stock_quote?${params.toString()}`, {
        headers: { Accept: 'application/json' },
      });
      if (requestId !== quoteRequestId.current) {
        return;
      }
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        setLatestLtp(null);
        setQuoteError(data.detail || data.message || 'Latest LTP is not available.');
        return;
      }

      const data = await response.json();
      if (requestId !== quoteRequestId.current) {
        return;
      }
      const ltp = Number(data?.quote?.ltp ?? 0);
      if (ltp > 0) {
        setLatestLtp(ltp);
        setPrice(String(ltp));
      } else {
        setLatestLtp(null);
        setQuoteError('Latest LTP is not available.');
      }
    } catch {
      if (requestId === quoteRequestId.current) {
        setLatestLtp(null);
        setQuoteError('Failed to load latest LTP.');
      }
    } finally {
      if (requestId === quoteRequestId.current) {
        setQuoteLoading(false);
      }
    }
  }, []);

  const loadSellHolding = useCallback(async (clientId: string, symbol: string) => {
    const normalizedSymbol = symbol.trim().toUpperCase();
    if (!clientId || !normalizedSymbol || orderType !== 'sell') {
      holdingRequestId.current += 1;
      setHoldingQty(null);
      setHoldingLabel('');
      setHoldingError('');
      return;
    }

    const requestId = holdingRequestId.current + 1;
    holdingRequestId.current = requestId;
    setHoldingLoading(true);
    setHoldingError('');
    setHoldingQty(null);
    setHoldingLabel('');

    try {
      const response = await fetch(`${getApiUrl()}/dp_holdings?client_id=${encodeURIComponent(clientId)}`, {
        headers: { Accept: 'application/json' },
      });
      if (requestId !== holdingRequestId.current) {
        return;
      }
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        setHoldingError(data.detail || data.message || 'Could not verify DP holdings for sell order.');
        return;
      }

      const holdings: DPHolding[] = await response.json();
      if (requestId !== holdingRequestId.current) {
        return;
      }
      const match = holdings.find((holding) => {
        const scrip = (holding.scrip || '').trim().toUpperCase();
        const name = (holding.symbolName || '').trim().toUpperCase();
        return scrip === normalizedSymbol || name === normalizedSymbol;
      });

      if (!match || Number(match.currentBalance || 0) <= 0) {
        setHoldingError(`${normalizedSymbol} is not available in this client's DP holdings.`);
        return;
      }

      setHoldingQty(Number(match.currentBalance || 0));
      setHoldingLabel(match.symbolName || match.scrip || normalizedSymbol);
    } catch {
      if (requestId === holdingRequestId.current) {
        setHoldingError('Could not verify DP holdings for sell order.');
      }
    } finally {
      if (requestId === holdingRequestId.current) {
        setHoldingLoading(false);
      }
    }
  }, [orderType]);

  useEffect(() => {
    void loadLatestQuote(clientID, scriptName);
  }, [clientID, scriptName, loadLatestQuote]);

  useEffect(() => {
    void loadSellHolding(clientID, scriptName);
  }, [clientID, scriptName, orderType, loadSellHolding]);

  const fillSellQuantityFromHolding = () => {
    if (!holdingQty || holdingQty <= 0) {
      return;
    }
    setQty(String(holdingQty));
    if (latestLtp && latestLtp > 0) {
      setPrice(String(latestLtp));
    }
  };

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setStatus('idle');
    setStatusMessage('');

    const requestedQty = parseInt(qty, 10);
    const requestedPrice = parseFloat(price);
    if (orderType === 'buy' && buyHighLimit !== null && requestedPrice > buyHighLimit) {
      setStatus('error');
      setStatusMessage(`Buy price cannot exceed today's high (${buyHighLimit}).`);
      return;
    }
    if (orderType === 'sell') {
      if (holdingLoading) {
        setStatus('error');
        setStatusMessage('Still verifying DP holdings. Please wait a moment.');
        return;
      }
      if (!holdingQty || holdingQty <= 0) {
        setStatus('error');
        setStatusMessage(holdingError || `${scriptName} is not available in DP holdings.`);
        return;
      }
      if (requestedQty > holdingQty) {
        setStatus('error');
        setStatusMessage(`Sell quantity cannot exceed DP holding quantity (${holdingQty}).`);
        return;
      }
    }

    setIsSubmitting(true);

    try {
      const response = await fetch(`${getApiUrl()}/add_order/`, {
        method: 'POST',
        headers: {
          Accept: 'application/json',
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          client_id: clientID,
          script_name: scriptName,
          price: requestedPrice,
          qty: requestedQty,
          order_type: orderType,
        }),
      });

      if (response.ok) {
        setStatus('success');
        setStatusMessage(`Order scheduled for ${scriptName} (${orderType.toUpperCase()}).`);
        setPrice('');
        setQty('');
      } else {
        const data = await response.json().catch(() => ({}));
        setStatus('error');
        setStatusMessage(data.detail || data.message || 'Failed to add order.');
      }
    } catch (error) {
      setStatus('error');
      setStatusMessage('Failed to add order. Check your API connection.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="schedule-order-page">
      <ScheduleMonitorBar key="schedule-monitor" />

      <div className="schedule-order-hero panel">
        <div className="schedule-order-hero-content">
          <div className="schedule-order-hero-icon" aria-hidden="true">📅</div>
          <div>
            <h2 className="schedule-order-hero-title">Schedule Order</h2>
            <p className="schedule-order-hero-subtitle">
              Queue buy or sell orders, then start monitoring to execute when price is hit.
            </p>
          </div>
        </div>
        {loggedInClientIDs.length > 0 && (
          <span className="badge badge-success">{loggedInClientIDs.length} client(s) online</span>
        )}
      </div>

      {status === 'success' && <ErrorMessage message={statusMessage} variant="success" />}
      {status === 'error' && <ErrorMessage message={statusMessage} variant="error" persistent />}

      <div className="schedule-order-layout">
        <div className="schedule-order-form-panel panel">
          <h3 className="panel-title">Add Order</h3>
          <p className="panel-subtitle">Select a client, symbol, price, and quantity.</p>

          <form onSubmit={handleSubmit} className="schedule-order-form">
            <div className="schedule-order-form-grid">
              <div className="form-group">
                <label htmlFor="scheduleClientId">Client ID</label>
                <select
                  id="scheduleClientId"
                  className="select"
                  value={clientID}
                  onChange={(e) => handleClientChange(e.target.value)}
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
                  <span className="schedule-order-hint">Log in via TMS Login tab first.</span>
                )}
              </div>

              <div className="form-group schedule-order-script-group">
                <label htmlFor="scheduleScriptName">Script Name</label>
                <ScriptNameAutocomplete
                  id="scheduleScriptName"
                  value={scriptName}
                  options={scriptOptions}
                  placeholder="Type to search — e.g. CREST"
                  disabled={stockDetails.length === 0}
                  required
                  onChange={handleScriptNameChange}
                  onSelect={handleScriptNameSelect}
                />
                {stockDetails.length === 0 && clientID && (
                  <span className="schedule-order-hint">Loading scripts for {clientID}...</span>
                )}
              </div>
            </div>

            <div className="schedule-order-form-grid">
              <div className="form-group">
                <label htmlFor="schedulePrice">Price</label>
                <input
                  id="schedulePrice"
                  type="number"
                  className="input"
                  value={price}
                  onChange={(e) => setPrice(e.target.value)}
                  placeholder="Order price"
                  min="0"
                  max={buyHighLimit ?? undefined}
                  step="0.1"
                  required
                />
                {buyHighLimit !== null && (
                  <span className="schedule-order-hint schedule-order-hint-muted">
                    Max buy price: {buyHighLimit} (today&apos;s high)
                  </span>
                )}
              </div>

              <div className="form-group">
                <label htmlFor="scheduleQty">Quantity</label>
                <input
                  id="scheduleQty"
                  type="number"
                  className="input"
                  value={qty}
                  onChange={(e) => setQty(e.target.value)}
                  placeholder="Number of shares"
                  min="1"
                  max={orderType === 'sell' && holdingQty ? holdingQty : undefined}
                  required
                />
              </div>
            </div>

            <div className="form-group">
              <label>Order Type</label>
              <div className="schedule-order-type-toggle">
                <button
                  type="button"
                  className={`schedule-order-type-btn ${orderType === 'buy' ? 'active-buy' : ''}`}
                  onClick={() => setOrderType('buy')}
                >
                  Buy
                </button>
                <button
                  type="button"
                  className={`schedule-order-type-btn ${orderType === 'sell' ? 'active-sell' : ''}`}
                  onClick={() => setOrderType('sell')}
                >
                  Sell
                </button>
              </div>
            </div>

            <button
              type="submit"
              className="btn btn-primary schedule-order-submit"
              disabled={isSubmitting || loggedInClientIDs.length === 0 || (orderType === 'sell' && holdingLoading)}
            >
              {isSubmitting ? 'Submitting...' : 'Schedule Order'}
            </button>
          </form>
        </div>

        <div className="schedule-order-side-panel panel">
          {selectedStock ? (
            <StockDetails
              stock={selectedStock}
              orderType={orderType}
              latestLtp={latestLtp}
              quoteLoading={quoteLoading}
              quoteError={quoteError}
              holdingQty={holdingQty}
              holdingLabel={holdingLabel}
              holdingLoading={holdingLoading}
              holdingError={holdingError}
              onFillFromHolding={fillSellQuantityFromHolding}
            />
          ) : (
            <div className="schedule-order-empty-side">
              <span style={{ fontSize: '2rem' }} aria-hidden="true">📈</span>
              <p>Select a script name to view live stock details.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default ScheduleOrder;
