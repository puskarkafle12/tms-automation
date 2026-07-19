import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import './ScheduleOrder.css';
import StockDetails from './StockDetails';
import ScriptNameAutocomplete, { ScriptOption } from '../../components/ScriptNameAutocomplete';
import ScheduleMonitorBar from '../../components/ScheduleMonitorBar';
import StrategySellForm, { STRATEGY_HELP } from './StrategySellForm';
import type { StrategyPayload, StrategyType } from './StrategySellForm';
import { buildScheduleScriptOptions, mergeQuoteIntoStockDetail, mergeUniqueStockDetails, formatApiErrorDetail, notifyScheduledOrdersChanged } from './scheduleOrderHelpers';
import { buildWebSocketUrl, fetchJson } from '../../utils/api';
import {
  extractSymbolsFromCompiledPlan,
  extractPlanSide,
  holdingsMapFromRows,
  isBuySymbolAllowedForSchedule,
  isCustomQueryStrategy,
  isRuleBasedStrategy,
  planUsesReference,
} from '../../lib/strategies/rulePlanHelpers';
import {
  getBuyScripCacheKey,
  getCachedScripSuggestions,
  getSellScripCacheKey,
  isCacheValid,
  setCachedScripSuggestions,
} from './scriptSuggestionCache';
import NepseAlphaSymbolLink from '../../components/NepseAlphaSymbolLink';
import TradeLightweightChart, { type TradeChartCandle } from '../../components/TradeLightweightChart';
import ScreenerDropConfirmModal from '../../components/ScreenerDropConfirmModal';
import {
  mapExpiryActionLabel,
  ScreenerDropScheduleInput,
} from '../../api/screenerDrop.api';

const getApiUrl = () => localStorage.getItem('apiUrl') || window.location.origin;
const SCHEDULE_ORDER_DRAFT_KEY = 'tms-schedule-order-draft-v1';

const ScheduleOrderChart: React.FC<{ symbol: string }> = ({ symbol }) => {
  const [candles, setCandles] = useState<TradeChartCandle[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError('');
    setCandles([]);
    void fetchJson<{ symbol: string; candles: TradeChartCandle[] }>(`/api/market/ohlcv/${encodeURIComponent(symbol)}?limit=2000`).then((response) => {
      if (cancelled) return;
      if (response.ok) {
        setCandles(response.data.candles || []);
        setError('');
      } else {
        setCandles([]);
        setError(response.error || 'Could not load price history.');
      }
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, [symbol]);
  return (
    <TradeLightweightChart
      symbol={symbol}
      candles={candles}
      loading={loading}
      error={error}
      emptyMessage={`No cached OHLCV candles are available for ${symbol}.`}
      loadingMessage={`Loading ${symbol} daily price history…`}
    />
  );
};

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
  const [submitProgress, setSubmitProgress] = useState('');
  const [latestLtp, setLatestLtp] = useState<number | null>(null);
  const [quote, setQuote] = useState<any | null>(null);
  const [quoteSocketQuoteTime, setQuoteSocketQuoteTime] = useState<string | null>(null);
  const quoteSocketQuoteTimeRef = useRef<string | null>(null);
  const quoteSocketRef = useRef<WebSocket | null>(null);
  const [quoteLoading, setQuoteLoading] = useState(false);
  const [quoteError, setQuoteError] = useState('');
  const [holdingQty, setHoldingQty] = useState<number | null>(null);
  const [holdingLabel, setHoldingLabel] = useState('');
  const [holdingLoading, setHoldingLoading] = useState(false);
  const [holdingError, setHoldingError] = useState('');
  const quoteRequestId = useRef(0);
  const holdingRequestId = useRef(0);
  const buyScripRequestId = useRef(0);
  const sellScripRequestId = useRef(0);
  const stockDetailsRef = useRef<any[]>([]);
  const [baselineModalOpen, setBaselineModalOpen] = useState(false);
  const [baselineScheduleInput, setBaselineScheduleInput] = useState<ScreenerDropScheduleInput | null>(null);
  const draftRestoredRef = useRef(false);
  const recommendationHandoffShownRef = useRef(false);
  const feedbackQueryKeyRef = useRef('');
  const recommendationHandoff = useMemo(() => new URLSearchParams(window.location.search).get('source') === 'backtest-recommendation', []);

  const bindSubmitFeedbackToQuery = useCallback((
    queryText: string,
    nextStatus: 'success' | 'error',
    message: string,
  ) => {
    feedbackQueryKeyRef.current = queryText.trim();
    setStatus(nextStatus);
    setStatusMessage(message);
  }, []);

  const clearSubmitFeedbackIfQueryChanged = useCallback((queryText: string) => {
    const key = queryText.trim();
    if (feedbackQueryKeyRef.current && key !== feedbackQueryKeyRef.current) {
      feedbackQueryKeyRef.current = '';
      setStatus('idle');
      setStatusMessage('');
    }
  }, []);

  const customQueryFeedbackKey = useCallback((strategyPayload: StrategyPayload) => (
    String(strategyPayload.strategy_config?.query_text || '').trim()
  ), []);

  useEffect(() => {
    if (draftRestoredRef.current) {
      return;
    }
    draftRestoredRef.current = true;
    try {
      const raw = localStorage.getItem(SCHEDULE_ORDER_DRAFT_KEY);
      if (!raw) {
        return;
      }
      const draft = JSON.parse(raw) as Partial<{
        clientID: string;
        scriptName: string;
        selectedScriptSymbol: string;
        price: string;
        qty: string;
        orderType: 'buy' | 'sell';
        selectedStrategy: StrategyType;
      }>;
      if (draft.clientID) setClientID(draft.clientID);
      if (draft.scriptName) setScriptName(draft.scriptName);
      if (draft.selectedScriptSymbol) setSelectedScriptSymbol(draft.selectedScriptSymbol);
      if (draft.price != null) setPrice(String(draft.price));
      if (draft.qty != null) setQty(String(draft.qty));
      if (draft.orderType === 'buy' || draft.orderType === 'sell') setOrderType(draft.orderType);
      if (draft.selectedStrategy) setSelectedStrategy(draft.selectedStrategy);
    } catch {
      localStorage.removeItem(SCHEDULE_ORDER_DRAFT_KEY);
    }
  }, []);

  useEffect(() => {
    if (!recommendationHandoff || recommendationHandoffShownRef.current) return;
    recommendationHandoffShownRef.current = true;
    try {
      const source = JSON.parse(localStorage.getItem('tms-strategy-source-v1:schedule-order') || '{}') as Record<string, unknown>;
      if (String(source.query_text || '').trim()) {
        setStatus('success');
        setStatusMessage(`Exact ${String(source.side || 'buy').toUpperCase()} backtest strategy loaded for ${String(source.symbol || 'the selected stock').toUpperCase()}. Review the account, live preview and risk settings, then confirm scheduling.`);
      } else {
        setStatus('error');
        setStatusMessage('The recommendation handoff did not contain a strategy query. Return to Recommendations and choose Schedule again.');
      }
    } catch {
      setStatus('error');
      setStatusMessage('The recommendation strategy handoff could not be read. Return to Recommendations and choose Schedule again.');
    }
  }, [recommendationHandoff]);

  useEffect(() => {
    if (!draftRestoredRef.current) {
      return;
    }
    localStorage.setItem(SCHEDULE_ORDER_DRAFT_KEY, JSON.stringify({
      clientID,
      scriptName,
      selectedScriptSymbol,
      price,
      qty,
      orderType,
      selectedStrategy,
    }));
  }, [clientID, orderType, price, qty, scriptName, selectedScriptSymbol, selectedStrategy]);

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
  const holdingsBySymbol = useMemo(
    () => holdingsMapFromRows(sellHoldings),
    [sellHoldings],
  );
  const isCustomQuerySelected = useMemo(
    () => isCustomQueryStrategy(selectedStrategy),
    [selectedStrategy],
  );
  const customQuerySideClass = isCustomQuerySelected
    ? `custom-query-${orderType === 'sell' ? 'sell' : 'buy'}`
    : '';

  const handleStrategyChange = (nextStrategy: StrategyType) => {
    setSelectedStrategy(isCustomQueryStrategy(nextStrategy) ? 'Custom Query' : nextStrategy);
    if (isCustomQueryStrategy(nextStrategy)) {
      setScriptName('');
      setSelectedStock(null);
      setPrice('');
      setLatestLtp(null);
      setQuote(null);
    }
  };

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
      const params = new URLSearchParams({
        client_id: clientId,
        force_refresh: String(forceRefresh),
      });
      const response = await fetch(`${getApiUrl()}/get_script_details?${params.toString()}`);
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
      const params = new URLSearchParams({
        client_id: clientId,
        force_refresh: String(forceRefresh),
      });
      const response = await fetch(`${getApiUrl()}/dp_holdings?${params.toString()}`, {
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
          const savedClientId = (() => {
            try {
              const raw = localStorage.getItem(SCHEDULE_ORDER_DRAFT_KEY);
              return raw ? String(JSON.parse(raw)?.clientID || '') : '';
            } catch {
              return '';
            }
          })();
          const defaultClientId = savedClientId || sessions[0]?.client_id || '';
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

  const applyQuotePayload = useCallback((data: any, normalizedSymbol: string, options?: { silent?: boolean }) => {
    const quoteData = data?.quote
      ? { ...data.quote, __socket: data.socket || null, __quote_source: data.quote_source || null }
      : null;
    setQuote(quoteData);
    const socketQuoteTime = quoteData?.lastTradedTime
      || quoteData?.lastTradedAt
      || quoteData?.lastTraded
      || data?.socket?.quote?.lastTradedTime
      || null;
    if (socketQuoteTime && socketQuoteTime !== quoteSocketQuoteTimeRef.current) {
      quoteSocketQuoteTimeRef.current = socketQuoteTime;
      setQuoteSocketQuoteTime(socketQuoteTime);
    }
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
  }, []);

  const loadLatestQuote = useCallback(async (clientId: string, symbol: string, options?: { silent?: boolean }) => {
    const normalizedSymbol = symbol.trim().toUpperCase();
    if (!clientId || !normalizedSymbol) {
      setLatestLtp(null);
      setQuote(null);
      setQuoteError('');
      return;
    }

    const silent = Boolean(options?.silent);
    let requestId = quoteRequestId.current;
    if (!silent) {
      requestId = quoteRequestId.current + 1;
      quoteRequestId.current = requestId;
      setQuoteLoading(true);
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
      applyQuotePayload(data, normalizedSymbol, options);
    } catch {
      if (requestId === quoteRequestId.current) {
        if (!options?.silent) {
          setLatestLtp(null);
          setQuote(null);
          setQuoteError('Failed to load latest LTP.');
        }
      }
    } finally {
      if (!silent && requestId === quoteRequestId.current) {
        setQuoteLoading(false);
      }
    }
  }, [applyQuotePayload]);

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
    void loadLatestQuote(clientID, selectedScriptSymbol);
  }, [clientID, selectedScriptSymbol, loadLatestQuote]);

  useEffect(() => {
    quoteSocketQuoteTimeRef.current = null;
    setQuoteSocketQuoteTime(null);
  }, [selectedScriptSymbol]);

  useEffect(() => {
    const normalizedSymbol = selectedScriptSymbol.trim().toUpperCase();
    if (!clientID || !normalizedSymbol) {
      quoteSocketRef.current?.close();
      quoteSocketRef.current = null;
      setQuoteLoading(false);
      return undefined;
    }
    const socketUrl = buildWebSocketUrl('/ws/stock_quote', {
      client_id: clientID,
      symbol: normalizedSymbol,
    });
    const socket = new WebSocket(socketUrl);
    quoteSocketRef.current = socket;
    setQuoteLoading(true);

    socket.onopen = () => {
      setQuoteLoading(false);
      setQuoteError('');
    };

    socket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data?.type === 'error') {
          setQuoteError(String(data.message || 'Live socket unavailable.'));
          return;
        }
        if (data?.type === 'heartbeat') {
          const socketState = data.socket || null;
          const quoteTime = socketState?.quote?.lastTradedTime || null;
          if (quoteTime && quoteTime !== quoteSocketQuoteTimeRef.current) {
            quoteSocketQuoteTimeRef.current = quoteTime;
            setQuoteSocketQuoteTime(quoteTime);
          }
          return;
        }
        applyQuotePayload(data, normalizedSymbol, { silent: true });
      } catch {
        setQuoteError('Received an invalid live quote update.');
      }
    };

    socket.onerror = () => {
      setQuoteLoading(false);
      setQuoteError('Live socket connection failed.');
    };

    socket.onclose = () => {
      setQuoteLoading(false);
    };

    return () => {
      socket.onopen = null;
      socket.onmessage = null;
      socket.onerror = null;
      socket.onclose = null;
      if (quoteSocketRef.current === socket) {
        quoteSocketRef.current = null;
      }
      socket.close();
    };
  }, [applyQuotePayload, clientID, selectedScriptSymbol]);

  useEffect(() => {
    void loadSellHolding(clientID, selectedScriptSymbol);
  }, [clientID, selectedScriptSymbol, orderType, loadSellHolding]);

  const fillSellQuantityFromHolding = () => {
    if (!holdingQty || holdingQty <= 0) {
      return;
    }
    setQty(String(holdingQty));
  };

  const resolveSecurityDetails = useCallback((symbol: string) => {
    const normalizedSymbol = symbol.trim().toUpperCase();
    const stockDetail = stockDetails.find((stock) => stock.symbol === normalizedSymbol);
    if (stockDetail) {
      return stockDetail;
    }
    if (orderType === 'sell') {
      const holding = sellHoldings.find((item) => {
        const scrip = (item.scrip || '').trim().toUpperCase();
        const name = (item.symbolName || '').trim().toUpperCase();
        return scrip === normalizedSymbol || name === normalizedSymbol;
      });
      if (holding) {
        return holding;
      }
    }
    return { symbol: normalizedSymbol };
  }, [orderType, sellHoldings, stockDetails]);

  const submitStrategyOrder = async (strategyPayload: StrategyPayload) => {
    const customQuery = isCustomQueryStrategy(strategyPayload.strategy_type);
    if (customQuery) {
      try {
        const source = JSON.parse(localStorage.getItem('tms-strategy-source-v1:schedule-order') || '{}') as Record<string, unknown>;
        const sourceQuery = String(source.query_text || '').trim();
        const payloadQuery = String(strategyPayload.strategy_config?.query_text || '').trim();
        if (sourceQuery && sourceQuery === payloadQuery) {
          const compiledSource = (source.compiled_plan || {}) as Record<string, any>;
          const backtestConfig = (compiledSource.backtest || {}) as Record<string, unknown>;
          const lifecycleConfig = (compiledSource.position_lifecycle || {}) as Record<string, unknown>;
          strategyPayload.strategy_config = {
            ...(strategyPayload.strategy_config || {}),
            source_backtest_result_id: source.source_backtest_result_id,
            source_backtest_run_id: source.source_backtest_run_id,
            source_backtest_symbol: source.symbol,
            source_backtest_side: source.side,
            linear_position_cycle: true,
            min_holding_days: Number(lifecycleConfig.min_holding_days ?? backtestConfig.min_holding_days ?? 5),
            max_holding_days: Number(lifecycleConfig.max_holding_days ?? backtestConfig.max_holding_days ?? 90),
            live_charge_policy: source.live_charge_policy || {
              charge_model: 'nepse_equity_v2024_05_14',
              investor_type: 'individual',
              apply_cgt: true,
              dp_charge: 25,
            },
            paired_sell_query_text: source.paired_sell_query_text,
            paired_sell_compiled_plan: source.paired_sell_compiled_plan,
            activation_requires_filled_buy: true,
            activation_requires_holding: true,
          };
        }
      } catch {
        localStorage.removeItem('tms-strategy-source-v1:schedule-order');
      }
    }
    if (!customQuery) {
      setStatus('idle');
      setStatusMessage('');
    }

    if (!clientID) {
      setStatus('error');
      setStatusMessage(`Select a client before scheduling a ${orderType} strategy.`);
      return;
    }

    const ruleBased = isRuleBasedStrategy(strategyPayload.strategy_type);
    const compiledPlan = strategyPayload.strategy_config?.compiled_plan as Record<string, unknown> | undefined;
    const effectiveOrderType = customQuery
      ? (extractPlanSide(compiledPlan) || orderType)
      : orderType;
    const scheduleSymbols = ruleBased
      ? extractSymbolsFromCompiledPlan(compiledPlan)
      : [scriptName.trim().toUpperCase()].filter(Boolean);

    if (!scheduleSymbols.length) {
      setStatus('error');
      setStatusMessage(ruleBased ? 'Rule plan must include at least one symbol.' : `Select a script before scheduling a ${orderType} strategy.`);
      return;
    }

    if (!ruleBased && !scriptName) {
      setStatus('error');
      setStatusMessage(`Select a client and script before scheduling a ${orderType} strategy.`);
      return;
    }
    if (!ruleBased && orderType === 'buy' && buyHighLimit !== null && strategyPayload.price > buyHighLimit) {
      setStatus('error');
      setStatusMessage(`Buy price cannot exceed today's high (${buyHighLimit}).`);
      return;
    }
    if (!customQuery && ruleBased && (!strategyPayload.price || strategyPayload.price <= 0)) {
      setStatus('error');
      setStatusMessage('Reference price is required. It is prefilled from LTP — adjust if needed.');
      return;
    }

    const symbolErrors: string[] = [];
    const serverPreflightApproved = customQuery
      && Boolean(strategyPayload.strategy_config?.schedule_preflight_ready);
    const knownBuySymbols = new Set(
      stockDetails.map((item) => String(item.symbol || '').trim().toUpperCase()),
    );
    for (const symbol of scheduleSymbols) {
      if (effectiveOrderType === 'buy') {
        if (!isBuySymbolAllowedForSchedule(symbol, knownBuySymbols, serverPreflightApproved)) {
          symbolErrors.push(`${symbol} is not a valid listed scrip for this client.`);
        }
      } else {
        const heldQty = holdingsBySymbol[symbol] ?? 0;
        if (heldQty <= 0) {
          symbolErrors.push(`${symbol} is not available in DP holdings.`);
        }
      }
    }
    if (customQuery && symbolErrors.length > 0) {
      setStatus('error');
      setStatusMessage(symbolErrors.join(' '));
      return;
    }
    if (symbolErrors.length === scheduleSymbols.length) {
      setStatus('error');
      setStatusMessage(symbolErrors.join(' '));
      return;
    }

    const baselineEnabled = Boolean(strategyPayload.strategy_config?.capture_reference_ltp)
      && !planUsesReference(
        compiledPlan,
        String(strategyPayload.strategy_config?.query_text || ''),
      );
    if (baselineEnabled && orderType === 'buy') {
      const config = strategyPayload.strategy_config || {};
      const fixedSymbols = Array.isArray(config.fixed_symbols) && config.fixed_symbols.length
        ? (config.fixed_symbols as string[])
        : scheduleSymbols;
      const expiration = (config.expiration || {}) as Record<string, unknown>;
      const expiryTimeLocal = String(config.baseline_expiry_time_local || '');
      if (!expiryTimeLocal) {
        setStatus('error');
        setStatusMessage('Expiration date/time is required for fixed baseline scheduling.');
        return;
      }
      setBaselineScheduleInput({
        clientId: clientID,
        queryText: String(config.query_text || ''),
        symbols: fixedSymbols.slice(0, 10),
        dropPercent: Number(config.drop_percent) || 10,
        expiryTimeLocal,
        expirationAction: mapExpiryActionLabel(String(strategyPayload.expiry_action || 'Cancel strategy')),
        maxSlippagePercent: strategyPayload.max_allowed_slippage_percent,
        marketClosedPolicy: (expiration.market_closed_policy as ScreenerDropScheduleInput['marketClosedPolicy'])
          || 'CANCEL_IF_MARKET_CLOSED',
        strategyType: String(strategyPayload.strategy_type || 'Custom Query Buy'),
        defaultQty: strategyPayload.qty,
        oddLotAllowed: Boolean(strategyPayload.odd_lot_allowed),
        securityDetailsBySymbol: Object.fromEntries(
          fixedSymbols.slice(0, 10).map((symbol) => [symbol, resolveSecurityDetails(symbol)]),
        ),
      });
      setBaselineModalOpen(true);
      return;
    }

    if (!ruleBased && orderType === 'buy' && !selectedStock) {
      setStatus('error');
      setStatusMessage(`${scriptName} is not a valid listed scrip for this client.`);
      return;
    }
    if (!ruleBased && orderType === 'sell') {
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

    if (ruleBased && scheduleSymbols.length > 1) {
      const eligibleSymbols = scheduleSymbols.filter(
        (symbol) => !symbolErrors.some((message) => message.startsWith(`${symbol} `)),
      );
      if (!eligibleSymbols.length) {
        setStatus('error');
        setStatusMessage(symbolErrors.join(' '));
        return;
      }
      const canReusePreflight = Boolean(strategyPayload.strategy_config?.schedule_preflight_ready);
      if (customQuery && !canReusePreflight) {
        setStatus('error');
        setStatusMessage('Schedule preflight is not complete. Wait for validation to finish before scheduling.');
        return;
      }
      const batchTimeoutMs = canReusePreflight
        ? Math.min(120000, Math.max(20000, eligibleSymbols.length * 2500))
        : Math.min(300000, Math.max(60000, eligibleSymbols.length * 8000));
      setIsSubmitting(true);
      setSubmitProgress(
        canReusePreflight
          ? `Scheduling ${eligibleSymbols.length} order(s)…`
          : `Preparing ${eligibleSymbols.length} symbol(s) for scheduling…`,
      );
      try {
        const batch = await fetchJson<{
          status: string;
          scheduled: Array<{ order_id: number; symbol: string }>;
          failed: Array<{ symbol: string; message?: string; error?: string }>;
          ready: boolean;
        }>('/api/strategy-plans/schedule-batch/wait', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            client_id: clientID,
            symbols: eligibleSymbols,
            order_type: orderType,
            order_fields: {
              ...strategyPayload,
              order_type: orderType,
              price: customQuery ? 0 : strategyPayload.price,
            },
            security_details_by_symbol: Object.fromEntries(
              eligibleSymbols.map((symbol) => [symbol, resolveSecurityDetails(symbol)]),
            ),
            holdings_by_symbol: orderType === 'sell' ? holdingsBySymbol : undefined,
            skip_preflight: canReusePreflight,
          }),
        }, batchTimeoutMs);
        if (!batch.ok) {
          const timedOut = batch.status === 408 || /timed out|aborted/i.test(batch.error || '');
          if (timedOut) {
            notifyScheduledOrdersChanged();
          }
          setStatus('error');
          setStatusMessage(
            timedOut
              ? `${batch.error} Refresh Order Logs to confirm which orders were created.`
              : (batch.error || 'Batch scheduling failed.'),
          );
          return;
        }
        if (batch.data.scheduled?.length) {
          notifyScheduledOrdersChanged();
        }
        const scheduledSymbols = batch.data.scheduled?.map((item) => item.symbol).filter(Boolean) || [];
        const failedSymbols = batch.data.failed || [];
        const rejectedSummary = failedSymbols
          .map((item) => `${item.symbol} (${item.message || item.error || 'Rejected during validation'})`)
          .join('; ');
        if (batch.data.status === 'preflight_failed') {
          setStatus('error');
          setStatusMessage(
            rejectedSummary
              ? `Cannot schedule yet. Rejected: ${rejectedSummary}`
              : 'Cannot schedule yet. Some symbols failed validation.',
          );
          return;
        }
        if (failedSymbols.length) {
          setStatus('error');
          setStatusMessage(
            [
              scheduledSymbols.length ? `Scheduled: ${scheduledSymbols.join(', ')}` : '',
              `Rejected: ${rejectedSummary}`,
            ].filter(Boolean).join(' · '),
          );
        } else {
          bindSubmitFeedbackToQuery(
            customQueryFeedbackKey(strategyPayload),
            'success',
            scheduledSymbols.length
              ? `Scheduled ${scheduledSymbols.length} order(s): ${scheduledSymbols.join(', ')}.`
              : 'No orders were scheduled.',
          );
        }
        if (!customQuery) {
          setPrice('');
          setQty('');
        }
      } catch {
        setStatus('error');
        setStatusMessage('Failed to start batch scheduling. Check your API connection.');
      } finally {
        setIsSubmitting(false);
        setSubmitProgress('');
      }
      return;
    }

    if (ruleBased) {
      setIsSubmitting(true);
      const canReusePreflight = Boolean(strategyPayload.strategy_config?.schedule_preflight_ready);
      if (!(customQuery && canReusePreflight)) {
        setSubmitProgress('Starting preflight checks…');
        const preflightResults = await Promise.all(
          scheduleSymbols.map(async (symbol) => {
            const preflight = await fetchJson<{
              ready: boolean;
              message?: string;
              status?: string;
              errors?: Array<{ message: string }>;
              warnings?: Array<{ message: string }>;
            }>('/api/strategy-plans/preflight', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                query_text: String(strategyPayload.strategy_config?.query_text || ''),
                compiled_plan: compiledPlan,
                strategy_type: strategyPayload.strategy_type,
                side: orderType,
                form_symbol: symbol,
                client_id: clientID,
                capture_reference_ltp: Boolean(strategyPayload.strategy_config?.capture_reference_ltp),
                drop_percent: Number(strategyPayload.strategy_config?.drop_percent) || 10,
                fixed_symbols: strategyPayload.strategy_config?.fixed_symbols,
              }),
            }, 120000);
            return { symbol, preflight };
          }),
        );
        const failedPreflight = preflightResults.find(({ preflight }) => !preflight.ok || !preflight.data.ready);
        if (failedPreflight) {
          const { symbol, preflight } = failedPreflight;
          if (!preflight.ok) {
            setStatus('error');
            setStatusMessage(preflight.error || `Preflight check failed for ${symbol}.`);
          } else {
            const detail = preflight.data.errors?.[0]?.message || preflight.data.message || `Cannot schedule ${symbol}.`;
            setStatus('error');
            setStatusMessage(detail);
          }
          setIsSubmitting(false);
          setSubmitProgress('');
          return;
        }
      }
    } else {
      setIsSubmitting(true);
    }

    try {
      const scheduled: string[] = [];
      const failures: string[] = [];
      const skipped: string[] = [];

      for (let index = 0; index < scheduleSymbols.length; index += 1) {
        const symbol = scheduleSymbols[index];
        setSubmitProgress(`Scheduling ${symbol} (${index + 1}/${scheduleSymbols.length})…`);
        const precheckError = symbolErrors.find((message) => message.startsWith(`${symbol} `));
        if (precheckError) {
          failures.push(precheckError);
          continue;
        }
        const securityDetails = resolveSecurityDetails(symbol);
        const orderPayload = {
          ...strategyPayload,
          price: customQuery ? 0 : strategyPayload.price,
        };
        const response = await fetch(`${getApiUrl()}/add_order/`, {
          method: 'POST',
          headers: {
            Accept: 'application/json',
            'Content-Type': 'application/json',
          },
          keepalive: true,
          body: JSON.stringify({
            client_id: clientID,
            script_name: symbol,
            order_type: orderType,
            security_details: securityDetails,
            ...orderPayload,
          }),
        });

        if (response.ok) {
          const data = await response.json().catch(() => ({} as { skipped?: boolean; message?: string }));
          if (data?.skipped) {
            skipped.push(`${symbol}: ${data.message || 'Skipped duplicate order.'}`);
          } else {
            scheduled.push(symbol);
          }
        } else {
          const data = await response.json().catch(() => ({}));
          failures.push(`${symbol}: ${formatApiErrorDetail(data.detail, data.message || 'Failed')}`);
        }
      }

      if (scheduled.length) {
        notifyScheduledOrdersChanged();
        bindSubmitFeedbackToQuery(
          customQueryFeedbackKey(strategyPayload),
          failures.length ? 'error' : 'success',
          [
            scheduled.length ? `Scheduled ${strategyPayload.strategy_type} for ${scheduled.join(', ')}.` : '',
            skipped.length ? `Skipped duplicates: ${skipped.join('; ')}` : '',
            failures.length ? `Failed: ${failures.join('; ')}` : '',
          ].filter(Boolean).join(' '),
        );
        if (!failures.length) {
          setPrice('');
          setQty('');
        }
      } else {
        if (skipped.length && !failures.length) {
          setStatus('success');
          setStatusMessage(skipped.join('; '));
        } else {
          setStatus('error');
          setStatusMessage(skipped.length ? skipped.join('; ') : failures.join('; ') || 'Failed to add order.');
        }
      }
    } catch (error) {
      setStatus('error');
      setStatusMessage('Failed to add order. Check your API connection.');
    } finally {
      setIsSubmitting(false);
      setSubmitProgress('');
    }
  };

  return (
    <div className="schedule-order-page">
      <ScheduleMonitorBar key="schedule-monitor" />

      <div className="schedule-order-layout">
        <div className={`schedule-order-form-panel panel ${customQuerySideClass}`}>
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

              {!isCustomQuerySelected && (
              <div className="form-group schedule-order-script-group">
                <label htmlFor="scheduleScriptName">Script Name</label>
                <ScriptNameAutocomplete
                  id="scheduleScriptName"
                  value={scriptName}
                  options={scriptOptions}
                  placeholder={orderType === 'sell' ? 'Search holding' : 'Search e.g. CREST'}
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
              )}
            </div>

            <div className="schedule-strategy-wrap">
              <StrategySellForm
                key={isCustomQuerySelected ? 'custom-query' : orderType}
                scriptName={isCustomQuerySelected ? undefined : scriptName}
                sideControl={!isCustomQuerySelected ? (
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
                ) : null}
                side={orderType}
                currentLtp={latestLtp}
                availableQty={orderType === 'sell' && !isCustomQuerySelected ? holdingQty : null}
                averageBuyPrice={orderType === 'sell' && !isCustomQuerySelected ? averageBuyPrice : null}
                topBuyPrice={quote?.topBuy?.find((row: any) => Number(row.price || 0) > 0)?.price || null}
                topSellPrice={quote?.topSell?.find((row: any) => Number(row.price || 0) > 0)?.price || null}
                initialQty={qty}
                initialPrice={isCustomQuerySelected ? '' : (latestLtp && latestLtp > 0 ? String(Math.round(latestLtp)) : price)}
                securityDetails={selectedStock || quote?.security || null}
                isSubmitting={isSubmitting}
                submitProgress={submitProgress}
                submitError={orderType === 'sell' && !isCustomQuerySelected ? holdingError || quoteError : quoteError}
                submitStatus={status}
                submitStatusMessage={statusMessage}
                clientId={clientID}
                holdingsBySymbol={holdingsBySymbol}
                initialStrategy={selectedStrategy}
                draftKey="schedule-order"
                aiPortalTargetId="custom-query-ai-side-panel"
                onCustomQuerySideChange={(nextSide) => setOrderType(nextSide)}
                onCustomQueryTextChange={clearSubmitFeedbackIfQueryChanged}
                onStrategyChange={handleStrategyChange}
                onSubmit={submitStrategyOrder}
              />
            </div>
          </div>
        </div>

        <div className={`schedule-order-side-panel panel ${customQuerySideClass}`}>
          {selectedStock ? (
            <>
            <StockDetails
              stock={selectedStock}
              orderType={orderType}
              latestLtp={latestLtp}
              quoteLoading={quoteLoading}
              quoteError={quoteError}
              topBuy={quote?.topBuy || []}
              topSell={quote?.topSell || []}
              socketStatus={quote?.__socket?.status || null}
              socketQuoteTime={quoteSocketQuoteTime || quote?.lastTradedTime || quote?.__socket?.quote?.lastTradedTime || null}
              quoteSource={quote?.__quote_source || null}
              holdingQty={holdingQty}
              holdingLabel={holdingLabel}
              holdingLoading={holdingLoading}
              holdingError={holdingError}
              onFillFromHolding={fillSellQuantityFromHolding}
            />
            {isCustomQuerySelected && <div className="schedule-order-ai-side" id="custom-query-ai-side-panel" />}
            </>
          ) : !isCustomQuerySelected ? (
            <div className="schedule-order-empty-side">
              <span style={{ fontSize: '2rem' }} aria-hidden="true">📈</span>
              <p>Select a script name to view live stock details.</p>
            </div>
          ) : (
            <div className="schedule-order-ai-side" id="custom-query-ai-side-panel" />
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
            <ScheduleOrderChart symbol={chartSymbol} />
          </div>
        </div>
      )}
      <ScreenerDropConfirmModal
        open={baselineModalOpen}
        input={baselineScheduleInput}
        onClose={() => {
          setBaselineModalOpen(false);
          setBaselineScheduleInput(null);
        }}
        onCommitted={({ scheduled, failed }) => {
          if (scheduled.length) {
            notifyScheduledOrdersChanged();
          }
          setStatus(failed.length ? 'error' : 'success');
          setStatusMessage(
            failed.length
              ? `Scheduled baseline orders for ${scheduled.join(', ')}. Failed: ${failed.join('; ')}`
              : `Baseline schedule created for ${scheduled.join(', ')}.`,
          );
          if (!failed.length) {
            setScriptName('');
            setSelectedScriptSymbol('');
            setPrice('');
            setQty('');
          }
        }}
      />
    </div>
  );
};

export default ScheduleOrder;
