import React, { useState, useEffect, useRef, useCallback } from 'react';
import './StockGrabber.css';
import ErrorMessage from '../../components/ErrorMessage';
import NepseAlphaSymbolLink from '../../components/NepseAlphaSymbolLink';
import CommonTable from '../../components/table/Table';
import { GrabberControls } from '../../types/monitoring';
import { buildWebSocketUrl, fetchJson } from '../../utils/api';

const getApiUrl = () => localStorage.getItem('apiUrl') || window.location.origin;

interface StockGrabberRequest {
  client_id: string;
  stock_symbol: string;
  order_quantity: number;
  request_per_sec: number;
  scan_mode: 'socket' | 'fixed';
  stop_buy_after_percent: number;
  broker_no: string;
  resume_scan_count?: number;
  resume_previous_ltp?: number;
  resume_stable_rate?: number;
}

interface StockGrabberResponse {
  status?: string;
  symbol?: string;
  fetch_rate?: number;
  total_fetch_count?: number;
  ltp?: number;
  change_percentage?: number;
  delay?: number;
  rate?: number;
  message?: string;
  error?: string;
  fetchDetails?: {
    fetchRate: number;
    totalFetchCount: number;
    ltp: number;
    script: string;
  };
  twoPercentHigh?: number;
  order_status?: string;
  order_response?: { order_id?: string; message?: string };
  order_quantity?: number;
  price?: number;
  total_orders?: number;
  details?: { ltp?: number; changePercentage?: number };
  quote_source?: string;
  socket_status?: string;
  socket_last_received_at?: string;
  socket_message_count?: number;
  topBuy?: QuoteLevel[];
  topSell?: QuoteLevel[];
  volume?: number;
  lastTradedTime?: string;
  delay_details?: OrderDelayDetails;
}

interface NewStockRow {
  symbol: string;
  is_watchlist?: boolean;
  volume?: number;
}

interface OrderDelayDetails {
  symbol?: string;
  market_last_traded_time?: string | null;
  tms_order_time?: string | null;
  delay_seconds?: number | null;
  delay_ms?: number | null;
  delay_display?: string | null;
  exchange_order_id?: string | null;
  order_status?: string | null;
  order_price?: number | string | null;
  order_quantity?: number | string | null;
}

interface OrderDelayRecord extends OrderDelayDetails {
  id: string;
  client_id: string;
  session_id: string | null;
  recorded_at: string;
}

interface QuoteLevel {
  sequenceId?: number;
  quantity?: number;
  price?: number;
  totalOrders?: number;
}

interface ActivityItem {
  id: string;
  type: 'update' | 'order' | 'error' | 'warn' | 'info';
  icon: string;
  text: string;
  time: string;
}

interface LiveStats {
  ltp: number | null;
  changePct: number | null;
  fetchRate: number | null;
  totalFetches: number;
  ordersPlaced: number;
  targetPrice: number | null;
  stableRate: number | null;
  quoteSource: string | null;
  socketStatus: string | null;
  socketLastReceivedAt: string | null;
  socketMessageCount: number | null;
  volume: number | null;
  lastTradedTime: string | null;
  topBuy: QuoteLevel[];
  topSell: QuoteLevel[];
}

interface FetchSpeedTest {
  running: boolean;
  fetches: number;
  errors: number;
  rate: number | null;
  message: string;
}

interface GrabberPersistState {
  sessionId: string | null;
  isRunning: boolean;
  order_quantity: number;
  request_per_sec: number;
  scan_mode: 'socket' | 'fixed';
  stop_buy_after_percent: number;
  scanCount: number;
  stableRate: number | null;
}

interface StockGrabberProps {
  instanceId: string;
  client_id: string;
  stock_symbol: string;
  resumeSessionId?: string | null;
  autoAttach?: boolean;
  resumeScanCount?: number;
  resumeStableRate?: number | null;
  initialOrderQuantity?: number;
  initialRequestPerSec?: number;
  initialStopBuyAfterPercent?: number;
  symbolAlreadyRunning?: boolean;
  onRemove: () => void;
  onRunningChange?: (running: boolean) => void;
  onRegisterControls?: (id: string, controls: GrabberControls) => void;
  onUnregisterControls?: (id: string) => void;
  onStateChange?: (state: GrabberPersistState) => void;
  onFocusCard?: () => void;
}

const TERMINAL_STATUSES = new Set(['stopped', 'completed', 'exit', 'success', 'failed']);

type ConnectionStatus = 'idle' | 'connecting' | 'live' | 'waiting' | 'stopped';

const formatTime = () =>
  new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

const CONNECTION_LABELS: Record<ConnectionStatus, string> = {
  idle: 'Ready to monitor',
  connecting: 'Connecting / restarting…',
  live: 'Live — scanning for +3% target under 15% cap',
  waiting: 'Armed — waiting for market to open',
  stopped: 'Monitor stopped',
};

const ORDER_DELAY_STORAGE_KEY = 'stock_grabber_order_delay_history';

const formatDepthNumber = (value?: number | null) =>
  Number.isFinite(Number(value)) ? Number(value).toLocaleString('en-NP') : '-';

const MiniDepth: React.FC<{ title: string; rows: QuoteLevel[] }> = ({ title, rows }) => (
  <div className="sg-depth-card">
    <span className="sg-depth-title">{title}</span>
    {rows.length > 0 ? (
      rows.slice(0, 3).map((row, index) => (
        <div className="sg-depth-row" key={`${title}-${row.sequenceId ?? index}`}>
          <strong>{formatDepthNumber(row.price)}</strong>
          <span>{formatDepthNumber(row.quantity)}</span>
        </div>
      ))
    ) : (
      <span className="sg-depth-empty">No depth</span>
    )}
  </div>
);

const loadOrderDelayHistory = (): OrderDelayRecord[] => {
  try {
    const raw = localStorage.getItem(ORDER_DELAY_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
};

const saveOrderDelayHistory = (records: OrderDelayRecord[]) => {
  localStorage.setItem(ORDER_DELAY_STORAGE_KEY, JSON.stringify(records.slice(0, 200)));
};

const StockGrabber: React.FC<StockGrabberProps> = ({
  instanceId,
  client_id,
  stock_symbol,
  resumeSessionId = null,
  autoAttach = false,
  resumeScanCount = 0,
  resumeStableRate = null,
  initialOrderQuantity,
  initialRequestPerSec,
  initialStopBuyAfterPercent,
  symbolAlreadyRunning = false,
  onRemove,
  onRunningChange,
  onRegisterControls,
  onUnregisterControls,
  onStateChange,
  onFocusCard,
}) => {
  const [formData, setFormData] = useState<StockGrabberRequest>({
    client_id,
    stock_symbol,
    order_quantity: initialOrderQuantity ?? 10,
    request_per_sec: initialRequestPerSec ?? 3,
    scan_mode: 'socket',
    stop_buy_after_percent: initialStopBuyAfterPercent ?? 15,
    broker_no: '35',
  });
  const [isRunning, setIsRunning] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const [showEvents, setShowEvents] = useState(false);
  const [ltpFlash, setLtpFlash] = useState<'up' | 'down' | null>(null);
  const [priceHistory, setPriceHistory] = useState<number[]>([]);
  const [activity, setActivity] = useState<ActivityItem[]>([]);
  const [fetchSpeedTest, setFetchSpeedTest] = useState<FetchSpeedTest>({
    running: false,
    fetches: 0,
    errors: 0,
    rate: null,
    message: '',
  });
  const [orderDelays, setOrderDelays] = useState<OrderDelayRecord[]>(() =>
    loadOrderDelayHistory().filter((record) =>
      record.client_id === client_id && String(record.symbol || '').toUpperCase() === stock_symbol.toUpperCase(),
    ),
  );
  const [selectedDelay, setSelectedDelay] = useState<OrderDelayRecord | null>(null);
  const [newStocks, setNewStocks] = useState<NewStockRow[]>([]);
  const [newStocksLoading, setNewStocksLoading] = useState(false);
  const [liveStats, setLiveStats] = useState<LiveStats>({
    ltp: null,
    changePct: null,
    fetchRate: null,
    totalFetches: resumeScanCount,
    ordersPlaced: 0,
    targetPrice: null,
    stableRate: resumeStableRate,
    quoteSource: null,
    socketStatus: null,
    socketLastReceivedAt: null,
    socketMessageCount: null,
    volume: null,
    lastTradedTime: null,
    topBuy: [],
    topSell: [],
  });

  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollingInFlightRef = useRef(false);
  const flashTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const startRef = useRef<(force?: boolean) => void>(() => {});
  const stopRef = useRef<() => void>(() => {});
  const formDataRef = useRef(formData);
  const isRunningRef = useRef(false);
  const isStartingRef = useRef(false);
  const sessionIdRef = useRef<string | null>(null);
  const stableLoggedRef = useRef(Boolean(resumeStableRate));
  const didAutoAttachRef = useRef(false);
  const lastActivityTextRef = useRef('');
  const lastScanAtRef = useRef(0);
  const isRestartingRef = useRef(false);
  const connectionStatusRef = useRef<ConnectionStatus>('idle');
  const restartGrabberRef = useRef<() => Promise<void>>(async () => {});
  const liveStatsRef = useRef(liveStats);

  const clearFetchSpeedTest = useCallback(() => {
    setFetchSpeedTest({
      running: false,
      fetches: 0,
      errors: 0,
      rate: null,
      message: '',
    });
  }, []);

  useEffect(() => {
    liveStatsRef.current = liveStats;
  }, [liveStats]);

  useEffect(() => {
    formDataRef.current = formData;
  }, [formData]);

  useEffect(() => {
    connectionStatusRef.current = connectionStatus;
  }, [connectionStatus]);

  const notifyStateChange = useCallback(() => {
    onStateChange?.({
      sessionId: sessionIdRef.current,
      isRunning: isRunningRef.current,
      order_quantity: formDataRef.current.order_quantity,
      request_per_sec: formDataRef.current.request_per_sec,
      scan_mode: formDataRef.current.scan_mode,
      stop_buy_after_percent: formDataRef.current.stop_buy_after_percent,
      scanCount: liveStatsRef.current.totalFetches,
      stableRate: liveStatsRef.current.stableRate,
    });
  }, [onStateChange]);

  const mergeScanCount = useCallback((sessionCount?: number, floor = 0) => {
    if (sessionCount === undefined) {
      return floor;
    }
    return Math.max(floor, sessionCount);
  }, []);

  const addEvent = useCallback((type: ActivityItem['type'], icon: string, text: string) => {
    if (text === lastActivityTextRef.current) {
      return;
    }
    lastActivityTextRef.current = text;
    setActivity((prev) => [
      { id: `${Date.now()}-${Math.random()}`, type, icon, text, time: formatTime() },
      ...prev,
    ].slice(0, 5));
  }, []);

  const updateLtp = useCallback((newLtp: number) => {
    setLiveStats((prev) => {
      if (prev.ltp !== null && newLtp !== prev.ltp) {
        const direction = newLtp > prev.ltp ? 'up' : 'down';
        setLtpFlash(direction);
        if (flashTimeoutRef.current) clearTimeout(flashTimeoutRef.current);
        flashTimeoutRef.current = setTimeout(() => setLtpFlash(null), 600);
      }
      return { ...prev, ltp: newLtp };
    });
    setPriceHistory((prev) => [...prev, newLtp].slice(-20));
  }, []);

  const processUpdate = useCallback((update: StockGrabberResponse) => {
    const status = update.status || '';

    if (status === 'update' || status === 'socket') {
      setConnectionStatus('live');
      if (update.ltp !== undefined) updateLtp(update.ltp);
      setLiveStats((prev) => ({
        ...prev,
        changePct: update.change_percentage ?? prev.changePct,
        fetchRate: update.fetch_rate ?? prev.fetchRate,
        totalFetches: mergeScanCount(update.total_fetch_count, prev.totalFetches),
        quoteSource: update.quote_source ?? prev.quoteSource,
        socketStatus: update.socket_status ?? prev.socketStatus,
        socketLastReceivedAt: update.socket_last_received_at ?? prev.socketLastReceivedAt,
        socketMessageCount: update.socket_message_count ?? prev.socketMessageCount,
        topBuy: update.topBuy ?? prev.topBuy,
        topSell: update.topSell ?? prev.topSell,
        volume: update.volume ?? prev.volume,
        lastTradedTime: update.lastTradedTime ?? prev.lastTradedTime,
      }));
      lastScanAtRef.current = Date.now();
      return false;
    }

    if (status === 'waiting') {
      setConnectionStatus('waiting');
      addEvent('info', '⏸', update.message || 'Waiting for market to open');
      return false;
    }

    if (status === 'stable') {
      setLiveStats((prev) => ({ ...prev, stableRate: update.rate ?? prev.stableRate }));
      if (!stableLoggedRef.current) {
        stableLoggedRef.current = true;
        addEvent('info', '⚡', `Scan rate stabilized at ${update.rate}/s`);
      }
      return false;
    }

    if (status === 'backoff') {
      return false;
    }

    if (status === 'warn') {
      addEvent('warn', '⏳', update.message || 'Retrying scan…');
      return false;
    }

    if (status === 'info') {
      addEvent('info', 'ℹ️', update.message || 'Update');
      return false;
    }

    if (status === 'started' || status === 'scanning') {
      setConnectionStatus('live');
      if (status === 'started' && update.message?.startsWith('Resuming')) {
        addEvent('info', '▶️', update.message);
      }
      if (status === 'scanning') {
        if (update.ltp !== undefined) updateLtp(update.ltp);
        if (update.total_fetch_count !== undefined) {
          setLiveStats((prev) => ({
            ...prev,
            totalFetches: mergeScanCount(update.total_fetch_count, prev.totalFetches),
            quoteSource: update.quote_source ?? prev.quoteSource,
            socketStatus: update.socket_status ?? prev.socketStatus,
            socketLastReceivedAt: update.socket_last_received_at ?? prev.socketLastReceivedAt,
          }));
        }
        lastScanAtRef.current = Date.now();
      }
      return false;
    }

    if (status === 'order') {
      const placed = update.order_status === 'success';
      setLiveStats((prev) => ({
        ...prev,
        ordersPlaced: placed ? prev.ordersPlaced + 1 : prev.ordersPlaced,
      }));
      addEvent(
        placed ? 'order' : 'error',
        placed ? '✅' : '❌',
        placed
          ? `Order placed — ${update.order_quantity} @ Rs. ${update.price}`
          : `Order failed — ${update.order_response?.message || 'unknown error'}`,
      );
      return false;
    }

    if (status === 'order_delay') {
      const details = update.delay_details || {};
      const record: OrderDelayRecord = {
        ...details,
        id: `${Date.now()}-${Math.random()}`,
        client_id: formDataRef.current.client_id,
        symbol: String(details.symbol || formDataRef.current.stock_symbol).toUpperCase(),
        session_id: sessionIdRef.current,
        recorded_at: new Date().toISOString(),
      };
      const allRecords = [record, ...loadOrderDelayHistory()];
      saveOrderDelayHistory(allRecords);
      setOrderDelays((prev) => [record, ...prev].slice(0, 25));
      addEvent('info', '⏱', update.message || `Delayed ${record.delay_display || 'unknown'}`);
      return false;
    }

    if (update.twoPercentHigh) {
      setLiveStats((prev) => ({ ...prev, targetPrice: update.twoPercentHigh ?? prev.targetPrice }));
      if (update.ltp !== undefined) updateLtp(update.ltp);
      addEvent('info', '🎯', `Target price — Rs. ${update.twoPercentHigh}`);
      return false;
    }

    if (update.fetchDetails?.ltp) {
      updateLtp(update.fetchDetails.ltp);
      setLiveStats((prev) => ({
        ...prev,
        fetchRate: update.fetchDetails?.fetchRate ?? prev.fetchRate,
        totalFetches: mergeScanCount(update.fetchDetails?.totalFetchCount, prev.totalFetches),
      }));
    }

    if (TERMINAL_STATUSES.has(status)) {
      if (status === 'stopped') {
        return true;
      }
      if (status === 'completed') {
        const placed = Number(update.total_orders ?? 0);
        if (placed <= 0) {
          addEvent('info', '⏹', update.message || 'Grabber completed without placing an order');
          return true;
        }
        addEvent('order', '🏁', update.message || `Finished — ${placed} order(s) placed`);
        return true;
      }
      if (status === 'failed' || status === 'exit') {
        addEvent('error', '⏹', update.message || update.error || `Grabber stopped: ${status}`);
        return true;
      }
      addEvent('order', '🏁', update.message || `Monitor ${status}`);
      return true;
    }

    return false;
  }, [addEvent, mergeScanCount, updateLtp]);

  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  }, []);

  const setRunning = useCallback((running: boolean) => {
    isRunningRef.current = running;
    setIsRunning(running);
    onRunningChange?.(running);
    notifyStateChange();
  }, [notifyStateChange, onRunningChange]);

  const resetSession = useCallback(() => {
    setRunning(false);
    setConnectionStatus('stopped');
    stopPolling();
    sessionIdRef.current = null;
    isStartingRef.current = false;
    stableLoggedRef.current = false;
    notifyStateChange();
  }, [notifyStateChange, setRunning, stopPolling]);

  const restartGrabber = useCallback(async () => {
    if (isRestartingRef.current || isStartingRef.current) {
      return;
    }
    isRestartingRef.current = true;
    stopPolling();
    const oldSession = sessionIdRef.current;
    sessionIdRef.current = null;
    isRunningRef.current = false;
    isStartingRef.current = false;

    if (oldSession) {
      try {
        await fetch(`${getApiUrl()}/stop_stock_grabber/${oldSession}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        });
      } catch {
        // Old session may already be gone — continue restart.
      }
    }

    const priorScans = liveStatsRef.current.totalFetches;
    addEvent(
      'warn',
      '🔄',
      priorScans > 0
        ? `Scanner stalled — auto-restarting from scan #${priorScans}…`
        : 'Scanner stalled — auto-restarting…',
    );
    setConnectionStatus('connecting');
    setRunning(true);
    isRestartingRef.current = false;
    onFocusCard?.();
    await startRef.current(true);
  }, [addEvent, onFocusCard, setRunning, stopPolling]);

  const beginPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
    }

    pollingRef.current = setInterval(async () => {
      const activeSessionId = sessionIdRef.current;
      if (!activeSessionId || isRestartingRef.current || pollingInFlightRef.current) {
        return;
      }

      pollingInFlightRef.current = true;
      try {
        const pollRes = await fetch(`${getApiUrl()}/get_stock_grabber_updates/${activeSessionId}`);
        if (!pollRes.ok) throw new Error(`Poll failed: ${pollRes.status}`);

        const pollData = await pollRes.json();
        const updates: StockGrabberResponse[] = pollData.updates || [];
        const scannerActive = pollData.scanner_active !== false;

        for (const update of updates) {
          const shouldStop = processUpdate(update);
          if (shouldStop) {
            resetSession();
            if (update.error || update.message) {
              setError(update.error || update.message || null);
            }
            return;
          }
        }

        const staleMs = Date.now() - lastScanAtRef.current;
        if (
          isRunningRef.current
          && connectionStatusRef.current !== 'waiting'
          && lastScanAtRef.current > 0
          && (!scannerActive || staleMs > 12000)
        ) {
          await restartGrabberRef.current();
        }
      } catch (err) {
        console.error('Poll error (will retry):', err);
      } finally {
        pollingInFlightRef.current = false;
      }
    }, 1500);
  }, [processUpdate, resetSession]);

  const attachToSession = useCallback(async (existingSessionId: string) => {
    if (isRunningRef.current || isStartingRef.current) {
      return;
    }

    isStartingRef.current = true;
    setConnectionStatus('connecting');
    setRunning(true);
    onFocusCard?.();

    sessionIdRef.current = existingSessionId;

    try {
      const pollRes = await fetch(`${getApiUrl()}/get_stock_grabber_updates/${existingSessionId}`);
      if (!pollRes.ok) {
        throw new Error(`Session unavailable (${pollRes.status})`);
      }

      const pollData = await pollRes.json();
      if (pollData.scanner_active === false) {
        throw new Error('Scanner is no longer active');
      }

      const updates: StockGrabberResponse[] = pollData.updates || [];
      for (const update of updates) {
        processUpdate(update);
      }

      lastScanAtRef.current = Date.now();
      setConnectionStatus('live');
      isStartingRef.current = false;
      addEvent('info', '🔌', 'Reconnected to running scanner');
      notifyStateChange();
      beginPolling();
    } catch {
      sessionIdRef.current = null;
      isStartingRef.current = false;
      addEvent('warn', '🔄', 'Session lost — restarting scanner…');
      await startRef.current(true);
    }
  }, [addEvent, beginPolling, notifyStateChange, onFocusCard, processUpdate, setRunning]);

  const startStockGrabber = async (force = false) => {
    clearFetchSpeedTest();
    if (!force && (isRunningRef.current || isStartingRef.current)) {
      return;
    }
    if (!formData.client_id || !formData.stock_symbol) {
      setError('Client ID and stock symbol are required.');
      return;
    }
    if (!force && symbolAlreadyRunning) {
      setError(`${formData.stock_symbol} is already being monitored for ${formData.client_id}`);
      return;
    }

    isStartingRef.current = true;
    if (!force) {
      setError(null);
      setActivity([]);
      lastActivityTextRef.current = '';
      stableLoggedRef.current = false;
      setLiveStats({
        ltp: null,
        changePct: null,
        fetchRate: null,
        totalFetches: 0,
        ordersPlaced: 0,
        targetPrice: null,
        stableRate: null,
        quoteSource: null,
        socketStatus: null,
        socketLastReceivedAt: null,
        socketMessageCount: null,
        volume: null,
        lastTradedTime: null,
        topBuy: [],
        topSell: [],
      });
      setPriceHistory([]);
    }
    setConnectionStatus('connecting');
    setRunning(true);

    const payload: StockGrabberRequest = { ...formData };
    if (force) {
      const snapshot = liveStatsRef.current;
      payload.resume_scan_count = snapshot.totalFetches;
      if (snapshot.ltp !== null) {
        payload.resume_previous_ltp = snapshot.ltp;
      }
      if (snapshot.stableRate !== null) {
        payload.resume_stable_rate = snapshot.stableRate;
      }
    }

    try {
      const res = await fetch(`${getApiUrl()}/stock_grabber/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `HTTP ${res.status}`);
      }

      const data = await res.json();
      sessionIdRef.current = data.session_id;
      lastScanAtRef.current = Date.now();
      setConnectionStatus('live');
      isStartingRef.current = false;
      notifyStateChange();
      onFocusCard?.();
      beginPolling();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start monitor');
      resetSession();
      setConnectionStatus('idle');
      addEvent('error', '❌', 'Failed to start monitor');
      isStartingRef.current = false;
    }
  };

  const stopStockGrabber = async () => {
    clearFetchSpeedTest();
    const activeSessionId = sessionIdRef.current;
    if (!activeSessionId) {
      resetSession();
      setConnectionStatus('idle');
      return;
    }

    try {
      await fetch(`${getApiUrl()}/stop_stock_grabber/${activeSessionId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to stop monitor');
    } finally {
      resetSession();
    }
  };

  const testFetchSpeed = async () => {
    if (isRunningRef.current || fetchSpeedTest.running) {
      return;
    }
    if (!formDataRef.current.client_id || !formDataRef.current.stock_symbol) {
      setError('Client ID and stock symbol are required to test fetch speed.');
      return;
    }

    setError(null);
    const scanMode = formDataRef.current.scan_mode;
    const requestPerSec = Math.max(0.2, Number(formDataRef.current.request_per_sec || 0) || 0.2);
    const testLabel = scanMode === 'socket' ? 'socket live stream' : `fixed HTTP polling @ ${requestPerSec.toFixed(1)}/s`;
    setFetchSpeedTest({
      running: true,
      fetches: 0,
      errors: 0,
      rate: null,
      message: `Testing ${testLabel} for 10 seconds...`,
    });

    const startedAt = performance.now();
    let liveUpdates = 0;
    let errors = 0;
    let lastSocketMessageCount = 0;
    let measuredElapsedSeconds: number | null = null;
    let measuredRate: number | null = null;
    let fixedTestHost = '';

    if (scanMode === 'socket') {
      await new Promise<void>((resolve) => {
        const socketUrl = buildWebSocketUrl('/ws/stock_quote', {
          client_id: formDataRef.current.client_id,
          symbol: formDataRef.current.stock_symbol,
        });
        const socket = new WebSocket(socketUrl);
        let finished = false;

        const finish = () => {
          if (finished) {
            return;
          }
          finished = true;
          socket.onopen = null;
          socket.onmessage = null;
          socket.onerror = null;
          socket.onclose = null;
          try {
            socket.close();
          } catch {
            // ignore close errors during test shutdown
          }
          resolve();
        };

        const timer = window.setTimeout(() => finish(), 10000);

        socket.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data as string);
            if (data?.type === 'error') {
              errors += 1;
              return;
            }
            const quote = data?.quote || data?.socket?.quote;
            if (!quote) {
              return;
            }
            const socketState = data?.socket || null;
            const socketMessageCount = Number(socketState?.message_count ?? socketState?.messageCount ?? 0);
            if (socketMessageCount > 0) {
              if (socketMessageCount > lastSocketMessageCount) {
                liveUpdates += socketMessageCount - lastSocketMessageCount;
                lastSocketMessageCount = socketMessageCount;
              }
            } else {
              liveUpdates += 1;
            }
          } catch {
            errors += 1;
          }
          setFetchSpeedTest((prev) => ({ ...prev, fetches: liveUpdates, errors }));
        };

        socket.onerror = () => {
          errors += 1;
          setFetchSpeedTest((prev) => ({ ...prev, fetches: liveUpdates, errors }));
        };

        socket.onclose = () => {
          window.clearTimeout(timer);
          finish();
        };

        socket.onopen = () => {
          setFetchSpeedTest((prev) => ({ ...prev, message: 'Testing socket mode for 10 seconds...' }));
        };
      });
    } else {
      try {
        setFetchSpeedTest((prev) => ({
          ...prev,
          message: `Testing real TMS HTTP API @ ${requestPerSec.toFixed(1)}/s for 10 seconds...`,
        }));
        const response = await fetch(`${getApiUrl()}/stock_grabber/test_fetch_speed`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          cache: 'no-store',
          body: JSON.stringify({
            client_id: formDataRef.current.client_id,
            stock_symbol: formDataRef.current.stock_symbol,
            request_per_sec: requestPerSec,
            duration_seconds: 10,
          }),
        });
        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(errorData.detail || `HTTP ${response.status}`);
        }
        const data = await response.json();
        const testId = data.test_id;
        if (!testId) {
          throw new Error('Fetch test id missing');
        }
        fixedTestHost = data.tms_api_url ? new URL(data.tms_api_url).host : '';

        let current = data;
        while (current && current.done !== true) {
          liveUpdates = Number(current.ok_count || 0);
          errors = Number(current.fail_count || 0);
          measuredElapsedSeconds = Number(current.duration_seconds || 0) || null;
          measuredRate = Number(current.fetch_per_sec || 0) || null;
          setFetchSpeedTest((prev) => ({
            ...prev,
            fetches: liveUpdates,
            errors,
            rate: measuredRate,
            message: `Testing real TMS HTTP API: ${(measuredRate || 0).toFixed(2)} fetch/s from ${fixedTestHost || 'TMS'}...`,
          }));
          await new Promise((resolve) => window.setTimeout(resolve, 350));
          const statusResponse = await fetch(`${getApiUrl()}/stock_grabber/test_fetch_speed/${testId}`, {
            cache: 'no-store',
          });
          if (!statusResponse.ok) {
            throw new Error(`HTTP ${statusResponse.status}`);
          }
          current = await statusResponse.json();
        }

        liveUpdates = Number(current.ok_count || 0);
        errors = Number(current.fail_count || 0);
        measuredElapsedSeconds = Number(current.duration_seconds || 0) || null;
        measuredRate = Number(current.fetch_per_sec || 0) || null;
      } catch {
        errors += 1;
      }
    }

    const elapsedSeconds = measuredElapsedSeconds ?? Math.max(0.1, (performance.now() - startedAt) / 1000);
    const rate = measuredRate ?? liveUpdates / elapsedSeconds;
    const resultLabel = scanMode === 'fixed' ? 'fixed mode' : 'socket mode';
    const resultSource = scanMode === 'fixed'
      ? `fetch/s from ${fixedTestHost || 'TMS'}`
      : 'live socket updates';
    setFetchSpeedTest({
      running: false,
      fetches: liveUpdates,
      errors,
      rate,
      message: `${resultLabel}: ${rate.toFixed(2)} ${resultSource} over ${elapsedSeconds.toFixed(1)}s`,
    });
  };

  useEffect(() => {
    if (connectionStatus !== 'stopped') {
      return undefined;
    }
    const timer = setTimeout(() => setConnectionStatus('idle'), 2500);
    return () => clearTimeout(timer);
  }, [connectionStatus]);

  useEffect(() => {
    restartGrabberRef.current = restartGrabber;
  }, [restartGrabber]);

  useEffect(() => {
    startRef.current = (force?: boolean) => startStockGrabber(force);
    stopRef.current = stopStockGrabber;
  });

  useEffect(() => {
    if (!autoAttach || !resumeSessionId || didAutoAttachRef.current) {
      return undefined;
    }
    didAutoAttachRef.current = true;
    attachToSession(resumeSessionId);
    return undefined;
  }, [attachToSession, autoAttach, resumeSessionId]);

  useEffect(() => {
    if (!onRegisterControls) {
      return undefined;
    }
    onRegisterControls(instanceId, {
      start: () => startRef.current(),
      stop: () => stopRef.current(),
      getIsRunning: () => isRunningRef.current,
    });
    return () => {
      onUnregisterControls?.(instanceId);
    };
  }, [instanceId, onRegisterControls, onUnregisterControls]);

  useEffect(() => () => {
    stopPolling();
    if (flashTimeoutRef.current) clearTimeout(flashTimeoutRef.current);
  }, [stopPolling]);

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const { name, value } = e.target;
    setFormData((prev) => ({
      ...prev,
      [name]: name === 'order_quantity' || name === 'request_per_sec' || name === 'stop_buy_after_percent'
        ? parseFloat(value) || 0
        : name === 'scan_mode'
          ? (value === 'fixed' ? 'fixed' : 'socket')
          : value,
    }));
  };

  const changePositive = (liveStats.changePct ?? 0) >= 0;
  const visibleEvents = showEvents ? activity.slice(0, 3) : activity.slice(0, 1);
  const loadNewStocks = useCallback(async () => {
    setNewStocksLoading(true);
    try {
      const response = await fetchJson<{ symbols?: NewStockRow[] }>('/market_analysis/new_stocks?days=15');
      if (response.ok) {
        setNewStocks(response.data.symbols || []);
      }
    } finally {
      setNewStocksLoading(false);
    }
  }, []);
  useEffect(() => {
    void loadNewStocks();
  }, [loadNewStocks]);
  const activeTopBuy = liveStats.topBuy.filter((row) => Number(row.price || 0) > 0 || Number(row.quantity || 0) > 0);
  const activeTopSell = liveStats.topSell.filter((row) => Number(row.price || 0) > 0 || Number(row.quantity || 0) > 0);

  const buildSparkline = () => {
    if (priceHistory.length < 2) return null;
    const width = 72;
    const height = 32;
    const min = Math.min(...priceHistory);
    const max = Math.max(...priceHistory);
    const range = max - min || 1;
    const points = priceHistory.map((price, i) => {
      const x = (i / (priceHistory.length - 1)) * width;
      const y = height - ((price - min) / range) * (height - 6) - 3;
      return `${x},${y}`;
    });
    const trendUp = priceHistory[priceHistory.length - 1] >= priceHistory[0];
    return (
      <svg className="sg-sparkline" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" aria-hidden="true">
        <polyline
          className={`sg-sparkline-line ${trendUp ? 'up' : 'down'}`}
          points={points.join(' ')}
        />
      </svg>
    );
  };

  return (
    <div className={`sg-monitor ${isRunning ? 'running' : ''} ${connectionStatus}`}>
      <div className="sg-monitor-header">
        <NepseAlphaSymbolLink symbol={formData.stock_symbol} className="sg-symbol-chip" />
        <div className="sg-monitor-meta">
          <span className="sg-monitor-client">{formData.client_id}</span>
          <button
            type="button"
            className={`sg-icon-btn ${showSettings ? 'active' : ''}`}
            onClick={() => {
              setShowSettings((v) => !v);
              if (!showSettings) setShowEvents(false);
            }}
            title="Settings"
            aria-label="Settings"
          >
            ⚙
          </button>
          <span className={`sg-live-badge ${isRunning ? 'live' : 'idle'}`}>
            {isRunning && <span className="sg-live-dot" />}
            {isRunning ? 'Live' : 'Idle'}
          </span>
        </div>
      </div>

      <div className="sg-monitor-body">
        <div className="sg-price-block">
          <div className="sg-price-main">
            <span className="sg-ltp-label">LTP</span>
            <span className={`sg-ltp-value ${ltpFlash ? `flash-${ltpFlash}` : ''}`}>
              {liveStats.ltp !== null ? `Rs. ${liveStats.ltp}` : '—'}
            </span>
            {liveStats.changePct !== null && (
              <span className={`sg-change-badge ${changePositive ? 'positive' : 'negative'}`}>
                {changePositive ? '▲' : '▼'} {changePositive ? '+' : ''}{liveStats.changePct}%
              </span>
            )}
          </div>
          {priceHistory.length >= 2 && (
            <div className="sg-sparkline-wrap">{buildSparkline()}</div>
          )}
        </div>

        <div className="sg-metrics-grid">
          <div className={`sg-metric ${isRunning ? 'active' : ''}`}>
            <span className="sg-metric-label">Scans</span>
            <span className="sg-metric-value">{liveStats.totalFetches.toLocaleString()}</span>
          </div>
          <div className={`sg-metric ${liveStats.ordersPlaced > 0 ? 'highlight' : ''}`}>
            <span className="sg-metric-label">Orders</span>
            <span className="sg-metric-value">{liveStats.ordersPlaced}</span>
          </div>
          <div className="sg-metric">
            <span className="sg-metric-label">Fetch</span>
            <span className="sg-metric-value">
              {liveStats.fetchRate !== null ? `${liveStats.fetchRate.toFixed(1)}/s` : '—'}
            </span>
          </div>
          <div className="sg-metric">
            <span className="sg-metric-label">Stable</span>
            <span className="sg-metric-value">
              {liveStats.stableRate !== null ? `${liveStats.stableRate}/s` : '—'}
            </span>
          </div>
          <div className="sg-metric">
            <span className="sg-metric-label">Source</span>
            <span className="sg-metric-value">{liveStats.quoteSource || '—'}</span>
          </div>
          <div className="sg-metric">
            <span className="sg-metric-label">Socket</span>
            <span className="sg-metric-value">{liveStats.socketStatus || '—'}</span>
          </div>
        </div>

        <div className="sg-depth-grid">
          <MiniDepth title="Top Buy" rows={activeTopBuy} />
          <MiniDepth title="Top Sell" rows={activeTopSell} />
        </div>

        {(liveStats.socketLastReceivedAt || liveStats.volume !== null) && (
          <div className="sg-socket-meta">
            <span>Socket messages: {liveStats.socketMessageCount ?? 0}</span>
            {liveStats.volume !== null && <span>Volume: {liveStats.volume.toLocaleString()}</span>}
            {liveStats.socketLastReceivedAt && <span>Last socket: {new Date(liveStats.socketLastReceivedAt).toLocaleTimeString()}</span>}
          </div>
        )}

        {orderDelays.length > 0 && (
          <div className="sg-delay-strip">
            <button
              type="button"
              className="sg-delay-latest"
              onClick={() => setSelectedDelay(orderDelays[0])}
              title="Show latest order delay details"
            >
              Delayed {orderDelays[0].delay_display || 'unknown'}
            </button>
            <button
              type="button"
              className="sg-delay-count"
              onClick={() => setSelectedDelay(orderDelays[0])}
              title="Show saved delay records"
            >
              {orderDelays.length} record{orderDelays.length === 1 ? '' : 's'}
            </button>
          </div>
        )}

        {liveStats.targetPrice !== null && (
          <div className="sg-target-bar">
            <span>🎯 Target</span>
            <strong>Rs. {liveStats.targetPrice}</strong>
          </div>
        )}

        <div className={`sg-status-strip ${connectionStatus}`}>
          <span className="sg-status-dot" />
          <span>{CONNECTION_LABELS[connectionStatus]}</span>
        </div>

        {activity.length > 0 && (
          <div className="sg-events">
            <button
              type="button"
              className="sg-events-toggle"
              onClick={() => setShowEvents((v) => !v)}
              aria-expanded={showEvents}
            >
              <span>Recent</span>
              <span className="sg-events-count">{activity.length}</span>
              <span className="sg-events-chevron">{showEvents ? '▴' : '▾'}</span>
            </button>
            <ul className={`sg-events-list ${showEvents ? 'expanded' : ''}`}>
              {visibleEvents.map((item) => (
                <li key={item.id} className={`sg-event ${item.type}`}>
                  <span className="sg-event-icon">{item.icon}</span>
                  <span className="sg-event-text">{item.text}</span>
                  <span className="sg-event-time">{item.time}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {showSettings && (
        <div className="sg-settings-panel">
      <div className="sg-settings-grid">
            <div className="form-group">
              <label htmlFor={`scan-mode-${instanceId}`}>Scan Mode</label>
              <select
                id={`scan-mode-${instanceId}`}
                name="scan_mode"
                className="input"
                value={formData.scan_mode}
                onChange={handleInputChange}
                disabled={isRunning}
              >
                <option value="socket">Socket live scan</option>
                <option value="fixed">Fixed interval scan</option>
              </select>
              <span className="sg-settings-hint">
                Socket mode follows the live stream. Fixed mode polls at the interval below.
              </span>
            </div>
            <div className="form-group">
              <label htmlFor={`qty-${instanceId}`}>Order Qty</label>
              <input
                id={`qty-${instanceId}`}
                type="number"
                name="order_quantity"
                className="input"
                value={formData.order_quantity}
                onChange={handleInputChange}
                disabled={isRunning}
                min={1}
              />
            </div>
            <div className="form-group">
              <label htmlFor={`rate-${instanceId}`}>Req / Sec</label>
              <div className="sg-rate-row">
                <input
                  id={`rate-${instanceId}`}
                  type="number"
                  name="request_per_sec"
                className="input"
                value={formData.request_per_sec}
                onChange={handleInputChange}
                disabled={isRunning}
                min={formData.scan_mode === 'fixed' ? 0.2 : 0.5}
                step={0.5}
              />
              <button
                  type="button"
                  className={`sg-test-fetch-btn ${fetchSpeedTest.running ? 'running' : ''}`}
                  onClick={() => { void testFetchSpeed(); }}
                  disabled={isRunning || fetchSpeedTest.running}
                  title="Test fetch speed for 10 seconds"
                >
                  {fetchSpeedTest.running ? 'Testing...' : 'Test 10s'}
                </button>
              </div>
              {(fetchSpeedTest.message || fetchSpeedTest.running) && (
                <span className="sg-fetch-test-result">
                  {fetchSpeedTest.message || 'Testing...'} · {fetchSpeedTest.fetches} ok / {fetchSpeedTest.errors} fail
                </span>
              )}
            </div>
            <div className="form-group">
              <label htmlFor={`broker-${instanceId}`}>Broker</label>
              <input
                id={`broker-${instanceId}`}
                type="text"
                name="broker_no"
                className="input"
                value={formData.broker_no}
                onChange={handleInputChange}
                disabled={isRunning}
              />
            </div>
            <div className="form-group">
              <label htmlFor={`stop-buy-${instanceId}`}>Stop Buy After %</label>
              <input
                id={`stop-buy-${instanceId}`}
                type="number"
                name="stop_buy_after_percent"
                className="input"
                value={formData.stop_buy_after_percent}
                onChange={handleInputChange}
                disabled={isRunning}
                min={0}
                max={15}
                step={0.1}
              />
              <span className="sg-settings-hint">Stops new buys at or above this day change. Max 15%.</span>
            </div>
          </div>
        </div>
      )}

      {error && (
        <div className="sg-error">
          <ErrorMessage message={error} variant="error" persistent />
        </div>
      )}

      <div className="sg-actions">
        <button
          type="button"
          className={`btn btn-success sg-btn-start ${isRunning ? 'active' : ''}`}
          onClick={() => startStockGrabber()}
          disabled={isRunning || symbolAlreadyRunning}
          title={symbolAlreadyRunning ? `${stock_symbol} is already being monitored` : 'Start monitoring'}
        >
          {isRunning ? '● Scanning' : symbolAlreadyRunning ? 'In Use' : '▶ Start'}
        </button>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={stopStockGrabber}
          disabled={!isRunning}
          title="Stop monitoring"
        >
          ■ Stop
        </button>
        <button
          type="button"
          className="btn btn-secondary sg-remove-btn"
          onClick={onRemove}
          disabled={isRunning}
          title={isRunning ? 'Stop first' : 'Remove'}
        >
          ✕
        </button>
      </div>

      {selectedDelay && (
        <div className="sg-delay-modal-backdrop" role="presentation" onClick={() => setSelectedDelay(null)}>
          <div className="sg-delay-modal" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
            <div className="sg-delay-modal-header">
              <div>
                <span className="sg-delay-eyebrow">Order Delay</span>
                <h3>{selectedDelay.symbol || formData.stock_symbol}</h3>
              </div>
              <button type="button" className="sg-icon-btn" onClick={() => setSelectedDelay(null)} aria-label="Close delay details">
                ✕
              </button>
            </div>
            <div className="sg-delay-hero">
              <span>Delayed</span>
              <strong>{selectedDelay.delay_display || 'Unavailable'}</strong>
            </div>
            <div className="sg-delay-detail-grid">
              <div><span>Market Last Trade</span><strong>{selectedDelay.market_last_traded_time || '-'}</strong></div>
              <div><span>Our TMS Order Time</span><strong>{selectedDelay.tms_order_time || '-'}</strong></div>
              <div><span>Delay Milliseconds</span><strong>{selectedDelay.delay_ms != null ? `${selectedDelay.delay_ms} ms` : '-'}</strong></div>
              <div><span>Exchange Order ID</span><strong>{selectedDelay.exchange_order_id || '-'}</strong></div>
              <div><span>Order Price</span><strong>{selectedDelay.order_price || '-'}</strong></div>
              <div><span>Order Qty</span><strong>{selectedDelay.order_quantity || '-'}</strong></div>
              <div><span>Status</span><strong>{selectedDelay.order_status || '-'}</strong></div>
              <div><span>Recorded In Browser</span><strong>{new Date(selectedDelay.recorded_at).toLocaleString()}</strong></div>
            </div>
            {orderDelays.length > 1 && (
              <div className="sg-delay-history">
                {orderDelays.slice(0, 10).map((record) => (
                  <button
                    type="button"
                    key={record.id}
                    className={record.id === selectedDelay.id ? 'active' : ''}
                    onClick={() => setSelectedDelay(record)}
                  >
                    <span>{record.delay_display || 'unknown'}</span>
                    <small>{record.tms_order_time || record.recorded_at}</small>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      <div className="sg-new-stocks-panel">
        <div className="sg-new-stocks-header">
          <div>
            <h3>New / IPO watchlist</h3>
            <p>Filtered New Stocks table with volume for quick grabber checks.</p>
          </div>
          <button type="button" className="sg-refresh-btn" onClick={() => { void loadNewStocks(); }} disabled={newStocksLoading}>
            {newStocksLoading ? 'Refreshing...' : 'Refresh'}
          </button>
        </div>
        {newStocksLoading && newStocks.length === 0 ? (
          <p className="sg-new-stocks-empty">Loading new IPO symbols…</p>
        ) : newStocks.length === 0 ? (
          <p className="sg-new-stocks-empty">No new symbols found.</p>
        ) : (
          <CommonTable
            data={newStocks}
            columns={['symbol', 'volume', 'is_watchlist']}
            columnLabels={{ volume: 'Volume', is_watchlist: 'Watchlist' }}
            columnLinks={{
              symbol: (row) => `https://nepsealpha.com/trading/chart?symbol=${encodeURIComponent(String(row.symbol || ''))}`,
            }}
          />
        )}
      </div>
    </div>
  );
};

export default StockGrabber;
