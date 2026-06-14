import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import './ScheduleOrder.css';
import StockDetails from './StockDetails';
import ErrorMessage from '../../components/ErrorMessage';
import ScriptNameAutocomplete, { ScriptOption } from '../../components/ScriptNameAutocomplete';
import ScheduleMonitorBar from '../../components/ScheduleMonitorBar';
import StrategySellForm, { StrategyPayload } from './StrategySellForm';
import { buildScheduleScriptOptions } from './scheduleOrderHelpers';

const getApiUrl = () => localStorage.getItem('apiUrl') || window.location.origin;

interface DPHolding {
  scrip?: string;
  symbolName?: string;
  currentBalance?: number;
  ltp?: number;
  percentChange?: string;
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
  const [sellHoldings, setSellHoldings] = useState<DPHolding[]>([]);
  const [selectedStock, setSelectedStock] = useState<any | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [latestLtp, setLatestLtp] = useState<number | null>(null);
  const [quote, setQuote] = useState<any | null>(null);
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
    () => buildScheduleScriptOptions(orderType, stockDetails, sellHoldings),
    [orderType, sellHoldings, stockDetails],
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

  const fetchSellHoldings = useCallback(async (clientId: string) => {
    if (!clientId) {
      setSellHoldings([]);
      return;
    }
    try {
      const response = await fetch(`${getApiUrl()}/dp_holdings?client_id=${encodeURIComponent(clientId)}`, {
        headers: { Accept: 'application/json' },
      });
      if (!response.ok) {
        setSellHoldings([]);
        return;
      }
      const holdings: DPHolding[] = await response.json();
      setSellHoldings(holdings);
    } catch {
      setSellHoldings([]);
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
          await Promise.all([fetchStockDetails(defaultClientId), fetchSellHoldings(defaultClientId)]);
        }
      } catch (error) {
        console.error('Error fetching logged-in client IDs:', error);
      }
    };

    loadInitialData();
  }, [fetchSellHoldings, fetchStockDetails]);

  const handleClientChange = async (clientId: string) => {
    setClientID(clientId);
    setQuoteError('');
    setHoldingError('');
    await Promise.all([fetchStockDetails(clientId), fetchSellHoldings(clientId)]);
  };

  const handleScriptNameChange = (name: string) => {
    const normalizedName = name.toUpperCase();
    setScriptName(normalizedName);
    const stockDetail = stockDetails.find((stock) => stock.symbol === normalizedName);
    setSelectedStock(stockDetail || null);
    setHoldingError('');
  };

  const handleScriptNameSelect = (option: ScriptOption) => {
    setScriptName(option.symbol);
    const stockDetail = stockDetails.find((stock) => stock.symbol === option.symbol);
    setSelectedStock(stockDetail || null);
    setHoldingError('');
  };

  useEffect(() => {
    if (!scriptName) {
      setSelectedStock(null);
      return;
    }
    const normalizedName = scriptName.trim().toUpperCase();
    setSelectedStock(stockDetails.find((stock) => stock.symbol === normalizedName) || null);
  }, [scriptName, stockDetails]);

  const loadLatestQuote = useCallback(async (clientId: string, symbol: string) => {
    const normalizedSymbol = symbol.trim().toUpperCase();
    if (!clientId || !normalizedSymbol) {
      setLatestLtp(null);
      setQuote(null);
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
        setQuote(null);
        setQuoteError(data.detail || data.message || 'Latest LTP is not available.');
        return;
      }

      const data = await response.json();
      if (requestId !== quoteRequestId.current) {
        return;
      }
      setQuote(data?.quote || null);
      const ltp = Number(data?.quote?.ltp ?? 0);
      if (ltp > 0) {
        setLatestLtp(ltp);
      } else {
        setLatestLtp(null);
        setQuoteError('Latest LTP is not available.');
      }
    } catch {
      if (requestId === quoteRequestId.current) {
        setLatestLtp(null);
        setQuote(null);
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
      const match = sellHoldings.find((holding) => {
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
  }, [orderType, sellHoldings]);

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

  const submitStrategyOrder = async (strategyPayload: StrategyPayload) => {
    setStatus('idle');
    setStatusMessage('');

    if (!clientID || !scriptName) {
      setStatus('error');
      setStatusMessage(`Select a client and script before scheduling a ${orderType} strategy.`);
      return;
    }
    if (orderType === 'buy' && buyHighLimit !== null && strategyPayload.price > buyHighLimit) {
      setStatus('error');
      setStatusMessage(`Buy price cannot exceed today's high (${buyHighLimit}).`);
      return;
    }
    if (orderType === 'buy' && !selectedStock) {
      setStatus('error');
      setStatusMessage(`${scriptName} is not a valid listed scrip for this client.`);
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
      if (strategyPayload.qty > holdingQty) {
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
          order_type: orderType,
          security_details: selectedStock || {},
          ...strategyPayload,
        }),
      });

      if (response.ok) {
        setStatus('success');
        setStatusMessage(`${strategyPayload.strategy_type} scheduled for ${scriptName}.`);
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

          <div className="schedule-order-form">
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
                  placeholder={orderType === 'sell' ? 'Search owned holding' : 'Type to search — e.g. CREST'}
                  disabled={!clientID || (orderType === 'buy' ? stockDetails.length === 0 : sellHoldings.length === 0)}
                  required
                  onChange={handleScriptNameChange}
                  onSelect={handleScriptNameSelect}
                />
                {stockDetails.length === 0 && clientID && (
                  <span className="schedule-order-hint">Loading scripts for {clientID}...</span>
                )}
                {orderType === 'sell' && sellHoldings.length === 0 && clientID && (
                  <span className="schedule-order-hint">No sellable DP holdings found for {clientID}.</span>
                )}
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

            <div className="schedule-strategy-wrap">
              <StrategySellForm
                key={orderType}
                side={orderType}
                currentLtp={latestLtp}
                availableQty={orderType === 'sell' ? holdingQty : null}
                averageBuyPrice={null}
                topBuyPrice={latestLtp}
                initialQty={qty}
                initialPrice={latestLtp ? String(latestLtp) : price}
                isSubmitting={isSubmitting}
                submitError={orderType === 'sell' ? holdingError || quoteError : quoteError}
                onSubmit={submitStrategyOrder}
              />
            </div>
          </div>
        </div>

        <div className="schedule-order-side-panel panel">
          {selectedStock ? (
            <StockDetails
              stock={selectedStock}
              orderType={orderType}
              latestLtp={latestLtp}
              quoteLoading={quoteLoading}
              quoteError={quoteError}
              topBuy={quote?.topBuy || []}
              topSell={quote?.topSell || []}
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
