import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import './ScheduleOrder.css';
import StockDetails from './StockDetails';
import ErrorMessage from '../../components/ErrorMessage';
import ScriptNameAutocomplete, { ScriptOption } from '../../components/ScriptNameAutocomplete';
import ScheduleMonitorBar from '../../components/ScheduleMonitorBar';
import StrategySellForm, { STRATEGY_HELP } from './StrategySellForm';
import type { StrategyPayload, StrategyType } from './StrategySellForm';
import { buildScheduleScriptOptions, mergeQuoteIntoStockDetail, mergeUniqueStockDetails } from './scheduleOrderHelpers';
import { fetchJson } from '../../utils/api';
import {
  getBuyScripCacheKey,
  getCachedScripSuggestions,
  getSellScripCacheKey,
  isCacheValid,
  setCachedScripSuggestions,
} from './scriptSuggestionCache';
import { buildNepseAlphaChartUrl } from '../../lib/nepseAlpha';
import NepseAlphaSymbolLink from '../../components/NepseAlphaSymbolLink';

const getApiUrl = () => localStorage.getItem('apiUrl') || window.location.origin;

interface DPHolding {
  scrip?: string;
  symbolName?: string;
  currentBalance?: number;
  valueAsOfPreviousClosePrice?: number;
  ltp?: number;
  percentChange?: string;
}

interface ClientSession {
  client_id: string;
  display_name?: string | null;
  broker_no: string;
}

const clientLabel = (client: ClientSession) => {
  const name = client.display_name?.trim() || client.client_id;
  return client.broker_no ? `${name}[${client.broker_no}]` : name;
};

const ScheduleOrder: React.FC = () => {
  const [clientID, setClientID] = useState('');
  const [scriptName, setScriptName] = useState('');
  const [selectedScriptSymbol, setSelectedScriptSymbol] = useState('');
  const [price, setPrice] = useState('');
  const [qty, setQty] = useState('');
  const [status, setStatus] = useState<'idle' | 'success' | 'error'>('idle');
  const [statusMessage, setStatusMessage] = useState('');
  const [loggedInClients, setLoggedInClients] = useState<ClientSession[]>([]);
  const [orderType, setOrderType] = useState<'buy' | 'sell'>('buy');
  const [selectedStrategy, setSelectedStrategy] = useState<StrategyType>('Fixed Price Buy');
  const [stockDetails, setStockDetails] = useState<any[]>([]);
  const [sellHoldings, setSellHoldings] = useState<DPHolding[]>([]);
  const [buyScripLoading, setBuyScripLoading] = useState(false);
  const [sellScripLoading, setSellScripLoading] = useState(false);
  const [buyScriptRefreshMessage, setBuyScriptRefreshMessage] = useState('');
  const [sellScriptRefreshMessage, setSellScriptRefreshMessage] = useState('');
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
  const [quoteRefreshMs, setQuoteRefreshMs] = useState(5000);
  const quoteRequestId = useRef(0);
  const holdingRequestId = useRef(0);
  const buyScripRequestId = useRef(0);
  const sellScripRequestId = useRef(0);
  const stockDetailsRef = useRef<any[]>([]);

  useEffect(() => {
    stockDetailsRef.current = stockDetails;
  }, [stockDetails]);

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

  const selectedClientLabel = useMemo(() => {
    const selectedClient = loggedInClients.find((client) => client.client_id === clientID);
    return selectedClient ? clientLabel(selectedClient) : clientID;
  }, [clientID, loggedInClients]);

  const selectedSellHolding = useMemo(() => {
    const normalizedSymbol = scriptName.trim().toUpperCase();
    if (!normalizedSymbol || orderType !== 'sell') {
      return null;
    }
    return sellHoldings.find((holding) => {
      const scrip = (holding.scrip || '').trim().toUpperCase();
      const name = (holding.symbolName || '').trim().toUpperCase();
      return scrip === normalizedSymbol || name === normalizedSymbol;
    }) || null;
  }, [orderType, scriptName, sellHoldings]);

  const averageBuyPrice = useMemo(() => {
    const holdingValue = Number(selectedSellHolding?.valueAsOfPreviousClosePrice || 0);
    const holdingBalance = Number(selectedSellHolding?.currentBalance || 0);
    return holdingValue > 0 && holdingBalance > 0 ? holdingValue / holdingBalance : null;
  }, [selectedSellHolding]);

  const activeScriptLoading = orderType === 'buy' ? buyScripLoading : sellScripLoading;
  const hasActiveScriptCache = orderType === 'buy' ? stockDetails.length > 0 : sellHoldings.length > 0;
  const activeScriptRefreshMessage =
    orderType === 'buy' ? buyScriptRefreshMessage : sellScriptRefreshMessage;
  const chartSymbol = scriptName.trim().toUpperCase();
  const selectedStrategyDescription =
    selectedStrategy === 'Fixed Price Buy' || selectedStrategy === 'Fixed Price Sell'
      ? ''
      : STRATEGY_HELP[selectedStrategy]?.helper || '';

  const changeOrderSide = (nextSide: 'buy' | 'sell') => {
    setOrderType(nextSide);
    setSelectedStrategy(nextSide === 'buy' ? 'Fixed Price Buy' : 'Fixed Price Sell');
  };

  const fetchStockDetails = useCallback(async (clientId: string, forceRefresh = false) => {
    if (!clientId) {
      setStockDetails([]);
      return;
    }

    const cacheKey = getBuyScripCacheKey(null, true);
    const cached = getCachedScripSuggestions<any[]>(cacheKey);
    if (!forceRefresh && cached) {
      setStockDetails(cached.data);
      if (isCacheValid(cached)) {
        setBuyScripLoading(false);
        setBuyScriptRefreshMessage('');
        return;
      }
      setBuyScriptRefreshMessage('Refreshing scrip list...');
    } else {
      if (!forceRefresh) {
        setStockDetails([]);
      }
      setBuyScripLoading(true);
      setBuyScriptRefreshMessage('');
    }

    const requestId = buyScripRequestId.current + 1;
    buyScripRequestId.current = requestId;
    try {
      const response = await fetch(`${getApiUrl()}/get_script_details?client_id=${encodeURIComponent(clientId)}`);
      if (requestId !== buyScripRequestId.current) {
        return;
      }
      if (response.ok) {
        const data = await response.json();
        const responseStockDetails = Array.isArray(data?.payload?.data) ? data.payload.data : [];
        const nextStockDetails = mergeUniqueStockDetails(cached?.data || stockDetailsRef.current, responseStockDetails);
        setStockDetails(nextStockDetails);
        setCachedScripSuggestions(cacheKey, nextStockDetails, {
          orderSide: 'buy',
          clientId: 'all',
        });
        setBuyScriptRefreshMessage('');
      } else {
        if (cached) {
          setBuyScriptRefreshMessage('Using cached scrip list. Refresh failed.');
        } else {
          setStockDetails([]);
        }
      }
    } catch (error) {
      console.error('Error fetching stock details:', error);
      if (cached) {
        setBuyScriptRefreshMessage('Using cached scrip list. Refresh failed.');
      } else {
        setStockDetails([]);
      }
    } finally {
      if (requestId === buyScripRequestId.current) {
        setBuyScripLoading(false);
      }
    }
  }, []);

  const fetchSellHoldings = useCallback(async (clientId: string, forceRefresh = false) => {
    if (!clientId) {
      setSellHoldings([]);
      return;
    }
    const cacheKey = getSellScripCacheKey(clientId);
    const cached = getCachedScripSuggestions<DPHolding[]>(cacheKey);
    if (!forceRefresh && cached) {
      setSellHoldings(cached.data);
      if (isCacheValid(cached)) {
        setSellScripLoading(false);
        setSellScriptRefreshMessage('');
        return;
      }
      setSellScriptRefreshMessage('Refreshing scrip list...');
    } else {
      if (!forceRefresh) {
        setSellHoldings([]);
      }
      setSellScripLoading(true);
      setSellScriptRefreshMessage('');
    }

    const requestId = sellScripRequestId.current + 1;
    sellScripRequestId.current = requestId;
    try {
      const response = await fetch(`${getApiUrl()}/dp_holdings?client_id=${encodeURIComponent(clientId)}`, {
        headers: { Accept: 'application/json' },
      });
      if (requestId !== sellScripRequestId.current) {
        return;
      }
      if (!response.ok) {
        if (cached) {
          setSellScriptRefreshMessage('Using cached scrip list. Refresh failed.');
        } else {
          setSellHoldings([]);
        }
        return;
      }
      const holdings: DPHolding[] = await response.json();
      setSellHoldings(holdings);
      setCachedScripSuggestions(cacheKey, holdings, {
        orderSide: 'sell',
        clientId,
      });
      setSellScriptRefreshMessage('');
    } catch {
      if (cached) {
        setSellScriptRefreshMessage('Using cached scrip list. Refresh failed.');
      } else {
        setSellHoldings([]);
      }
    } finally {
      if (requestId === sellScripRequestId.current) {
        setSellScripLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    const loadInitialData = async () => {
      try {
        const response = await fetch(`${getApiUrl()}/logged_in_clients/`);
        if (response.ok) {
          const data = await response.json();
          const sessions: ClientSession[] = data.sessions || (data.logged_in_client_ids || []).map((id: string) => ({
            client_id: id,
            broker_no: '',
          }));
          setLoggedInClients(sessions);
          const defaultClientId = sessions[0]?.client_id || '';
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

  const refreshScriptSuggestions = () => {
    if (!clientID) {
      return;
    }
    if (orderType === 'buy') {
      void fetchStockDetails(clientID, true);
      return;
    }
    void fetchSellHoldings(clientID, true);
  };

  const handleScriptNameChange = (name: string) => {
    const normalizedName = name.toUpperCase();
    setScriptName(normalizedName);
    setSelectedScriptSymbol('');
    quoteRequestId.current += 1;
    holdingRequestId.current += 1;
    setLatestLtp(null);
    setQuote(null);
    const stockDetail = stockDetails.find((stock) => stock.symbol === normalizedName);
    setSelectedStock(stockDetail || null);
    setHoldingError('');
  };

  const handleScriptNameSelect = (option: ScriptOption) => {
    setScriptName(option.symbol);
    setSelectedScriptSymbol(option.symbol);
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

  const loadLatestQuote = useCallback(async (clientId: string, symbol: string, options?: { silent?: boolean }) => {
    const normalizedSymbol = symbol.trim().toUpperCase();
    if (!clientId || !normalizedSymbol) {
      setLatestLtp(null);
      setQuote(null);
      setQuoteError('');
      return;
    }

    const requestId = quoteRequestId.current + 1;
    quoteRequestId.current = requestId;
    if (!options?.silent) {
      setQuoteLoading(true);
    }
    if (!options?.silent) {
      setQuoteError('');
    }

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
        if (!options?.silent) {
          setLatestLtp(null);
          setQuote(null);
          setQuoteError(data.detail || data.message || 'Latest LTP is not available.');
        }
        return;
      }

      const data = await response.json();
      if (requestId !== quoteRequestId.current) {
        return;
      }
      const quoteData = data?.quote || null;
      setQuote(quoteData);
      const ltp = Number(quoteData?.ltp ?? 0);
      if (ltp > 0) {
        setLatestLtp(ltp);
      } else if (!options?.silent) {
        setLatestLtp(null);
        setQuoteError('Latest LTP is not available.');
      }

      if (quoteData) {
        setSelectedStock((previous: any) => {
          if (!previous || String(previous.symbol || '').trim().toUpperCase() !== normalizedSymbol) {
            return previous;
          }
          return mergeQuoteIntoStockDetail(previous, quoteData);
        });
        setStockDetails((previous: any[]) =>
          previous.map((stock) =>
            String(stock.symbol || '').trim().toUpperCase() === normalizedSymbol
              ? mergeQuoteIntoStockDetail(stock, quoteData)
              : stock,
          ),
        );
      }
    } catch {
      if (requestId === quoteRequestId.current) {
        if (!options?.silent) {
          setLatestLtp(null);
          setQuote(null);
          setQuoteError('Failed to load latest LTP.');
        }
      }
    } finally {
      if (requestId === quoteRequestId.current) {
        setQuoteLoading(false);
      }
    }
  }, []);

  const loadSellHolding = useCallback(async (clientId: string, symbol: string, options?: { silent?: boolean }) => {
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
    if (!options?.silent) {
      setHoldingLoading(true);
      setHoldingError('');
      setHoldingQty(null);
      setHoldingLabel('');
    }

    try {
      const match = sellHoldings.find((holding) => {
        const scrip = (holding.scrip || '').trim().toUpperCase();
        const name = (holding.symbolName || '').trim().toUpperCase();
        return scrip === normalizedSymbol || name === normalizedSymbol;
      });

      if (!match || Number(match.currentBalance || 0) <= 0) {
        if (!options?.silent) {
          setHoldingError(`${normalizedSymbol} is not available in this client's DP holdings.`);
        }
        return;
      }

      setHoldingQty(Number(match.currentBalance || 0));
      setHoldingLabel(match.symbolName || match.scrip || normalizedSymbol);
    } catch {
      if (requestId === holdingRequestId.current) {
        if (!options?.silent) {
          setHoldingError('Could not verify DP holdings for sell order.');
        }
      }
    } finally {
      if (requestId === holdingRequestId.current) {
        setHoldingLoading(false);
      }
    }
  }, [orderType, sellHoldings]);

  useEffect(() => {
    const loadInterval = async () => {
      const result = await fetchJson<{ monitor_interval: number }>('/get_monitor_interval');
      if (result.ok && result.data.monitor_interval > 0) {
        setQuoteRefreshMs(result.data.monitor_interval * 1000);
      }
    };
    void loadInterval();
  }, []);

  useEffect(() => {
    void loadLatestQuote(clientID, selectedScriptSymbol);
  }, [clientID, selectedScriptSymbol, loadLatestQuote]);

  useEffect(() => {
    const normalizedSymbol = selectedScriptSymbol.trim().toUpperCase();
    if (!clientID || !normalizedSymbol) {
      return undefined;
    }
    const interval = window.setInterval(() => {
      void loadLatestQuote(clientID, normalizedSymbol, { silent: true });
      if (orderType === 'sell') {
        void loadSellHolding(clientID, normalizedSymbol, { silent: true });
      }
    }, quoteRefreshMs);
    return () => window.clearInterval(interval);
  }, [clientID, loadLatestQuote, loadSellHolding, orderType, quoteRefreshMs, selectedScriptSymbol]);

  useEffect(() => {
    void loadSellHolding(clientID, selectedScriptSymbol);
  }, [clientID, selectedScriptSymbol, orderType, loadSellHolding]);

  const fillSellQuantityFromHolding = () => {
    if (!holdingQty || holdingQty <= 0) {
      return;
    }
    setQty(String(holdingQty));
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

      {status === 'success' && <ErrorMessage message={statusMessage} variant="success" />}
      {status === 'error' && <ErrorMessage message={statusMessage} variant="error" persistent />}

      <div className="schedule-order-layout">
        <div className="schedule-order-form-panel panel">
          <h3 className="panel-title">Add Order</h3>
          {selectedStrategyDescription && (
            <p className="schedule-strategy-description">{selectedStrategyDescription}</p>
          )}

          <div className="schedule-order-form">
            <div className="schedule-order-form-grid">
              <div className="form-group">
                <label htmlFor="scheduleClientId">Client</label>
                <select
                  id="scheduleClientId"
                  className="select"
                  value={clientID}
                  onChange={(e) => handleClientChange(e.target.value)}
                  disabled={loggedInClients.length === 0}
                  required
                >
                  {loggedInClients.length === 0 ? (
                    <option value="">No logged-in clients</option>
                  ) : (
                    loggedInClients.map((client) => (
                      <option key={client.client_id} value={client.client_id}>{clientLabel(client)}</option>
                    ))
                  )}
                </select>
                {loggedInClients.length === 0 && (
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
                  disabled={!clientID || (activeScriptLoading && !hasActiveScriptCache)}
                  required
                  maxResults={Math.max(scriptOptions.length, 10)}
                  actionTitle="Refresh scrip suggestions"
                  actionLoading={activeScriptLoading}
                  onAction={refreshScriptSuggestions}
                  onChange={handleScriptNameChange}
                  onSelect={handleScriptNameSelect}
                />
                {activeScriptLoading && !hasActiveScriptCache && clientID && (
                  <span className="schedule-order-hint">Loading scripts for {selectedClientLabel}...</span>
                )}
                {activeScriptRefreshMessage && (
                  <span className="schedule-order-hint schedule-order-hint-muted">{activeScriptRefreshMessage}</span>
                )}
                {orderType === 'sell' && !sellScripLoading && sellHoldings.length === 0 && clientID && (
                  <span className="schedule-order-hint">No sellable DP holdings found for {selectedClientLabel}.</span>
                )}
              </div>
            </div>

            <div className="schedule-strategy-wrap">
              <StrategySellForm
                key={orderType}
                scriptName={scriptName}
                sideControl={(
                  <div className="form-group schedule-side-field">
                    <label>Side</label>
                    <div className="schedule-order-type-toggle">
                      <button
                        type="button"
                        className={`schedule-order-type-btn ${orderType === 'buy' ? 'active-buy' : ''}`}
                        onClick={() => changeOrderSide('buy')}
                      >
                        Buy
                      </button>
                      <button
                        type="button"
                        className={`schedule-order-type-btn ${orderType === 'sell' ? 'active-sell' : ''}`}
                        onClick={() => changeOrderSide('sell')}
                      >
                        Sell
                      </button>
                    </div>
                  </div>
                )}
                side={orderType}
                currentLtp={latestLtp}
                availableQty={orderType === 'sell' ? holdingQty : null}
                averageBuyPrice={orderType === 'sell' ? averageBuyPrice : null}
                topBuyPrice={quote?.topBuy?.find((row: any) => Number(row.price || 0) > 0)?.price || null}
                topSellPrice={quote?.topSell?.find((row: any) => Number(row.price || 0) > 0)?.price || null}
                initialQty={qty}
                initialPrice={orderType === 'sell' && latestLtp ? String(latestLtp) : price}
                securityDetails={selectedStock || quote?.security || null}
                isSubmitting={isSubmitting}
                submitError={orderType === 'sell' ? holdingError || quoteError : quoteError}
                onStrategyChange={setSelectedStrategy}
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

      {chartSymbol && (
        <div className="schedule-order-chart-panel panel">
          <div className="schedule-order-chart-header">
            <div>
              <h3 className="panel-title">
                <NepseAlphaSymbolLink symbol={chartSymbol} /> Chart
              </h3>
            </div>
          </div>
          <div className="schedule-order-chart-box">
            <iframe
              title={`${chartSymbol} NEPSE chart`}
              src={buildNepseAlphaChartUrl(chartSymbol) || ''}
            />
          </div>
        </div>
      )}
    </div>
  );
};

export default ScheduleOrder;
