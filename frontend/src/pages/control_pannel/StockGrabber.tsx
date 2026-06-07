import React, { useState, useEffect, useRef, useCallback } from 'react';
import './StockGrabber.css';
import ErrorMessage from '../../components/ErrorMessage';
import { GrabberControls } from '../../types/monitoring';
import { monitoringStore } from '../../hooks/monitoringStore';

const getApiUrl = () => localStorage.getItem('apiUrl') || window.location.origin;

interface StockGrabberRequest {
  client_id: string;
  stock_symbol: string;
  order_quantity: number;
  request_per_sec: number;
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
}

interface GrabberPersistState {
  sessionId: string | null;
  isRunning: boolean;
  order_quantity: number;
  request_per_sec: number;
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
  symbolAlreadyRunning?: boolean;
  onRemove: () => void;
  onRunningChange?: (running: boolean) => void;
  onRegisterControls?: (id: string, controls: GrabberControls) => void;
  onUnregisterControls?: (id: string) => void;
  onStateChange?: (state: GrabberPersistState) => void;
  onFocusCard?: () => void;
}

const TERMINAL_STATUSES = new Set(['stopped', 'completed', 'exit', 'success', 'failed']);

type ConnectionStatus = 'idle' | 'connecting' | 'live' | 'stopped';

const formatTime = () =>
  new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

const CONNECTION_LABELS: Record<ConnectionStatus, string> = {
  idle: 'Ready to monitor',
  connecting: 'Connecting / restarting…',
  live: 'Live — scanning for +2% high price',
  stopped: 'Monitor stopped',
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
    broker_no: '35',
  });
  const [isRunning, setIsRunning] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>('idle');
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const [showEvents, setShowEvents] = useState(false);
  const [ltpFlash, setLtpFlash] = useState<'up' | 'down' | null>(null);
  const [priceHistory, setPriceHistory] = useState<number[]>([]);
  const [activity, setActivity] = useState<ActivityItem[]>([]);
  const [liveStats, setLiveStats] = useState<LiveStats>({
    ltp: null,
    changePct: null,
    fetchRate: null,
    totalFetches: resumeScanCount,
    ordersPlaced: 0,
    targetPrice: null,
    stableRate: resumeStableRate,
  });

  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
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
  const restartGrabberRef = useRef<() => Promise<void>>(async () => {});
  const liveStatsRef = useRef(liveStats);

  useEffect(() => {
    liveStatsRef.current = liveStats;
  }, [liveStats]);

  useEffect(() => {
    formDataRef.current = formData;
  }, [formData]);

  const notifyStateChange = useCallback(() => {
    onStateChange?.({
      sessionId: sessionIdRef.current,
      isRunning: isRunningRef.current,
      order_quantity: formDataRef.current.order_quantity,
      request_per_sec: formDataRef.current.request_per_sec,
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

    if (status === 'update') {
      if (update.ltp !== undefined) updateLtp(update.ltp);
      setLiveStats((prev) => ({
        ...prev,
        changePct: update.change_percentage ?? prev.changePct,
        fetchRate: update.fetch_rate ?? prev.fetchRate,
        totalFetches: mergeScanCount(update.total_fetch_count, prev.totalFetches),
      }));
      lastScanAtRef.current = Date.now();
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
      if (status === 'started' && update.message?.startsWith('Resuming')) {
        addEvent('info', '▶️', update.message);
      }
      if (status === 'scanning') {
        if (update.ltp !== undefined) updateLtp(update.ltp);
        if (update.total_fetch_count !== undefined) {
          setLiveStats((prev) => ({
            ...prev,
            totalFetches: mergeScanCount(update.total_fetch_count, prev.totalFetches),
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
          return false;
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
    monitoringStore.setGrabberRunning(instanceId, running);
    onRunningChange?.(running);
    notifyStateChange();
  }, [instanceId, notifyStateChange, onRunningChange]);

  const resetSession = useCallback(() => {
    setRunning(false);
    setConnectionStatus('stopped');
    stopPolling();
    setSessionId(null);
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
    setSessionId(null);
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
      if (!activeSessionId || isRestartingRef.current) {
        return;
      }

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
          && lastScanAtRef.current > 0
          && (!scannerActive || staleMs > 12000)
        ) {
          await restartGrabberRef.current();
        }
      } catch (err) {
        console.error('Poll error (will retry):', err);
      }
    }, 800);
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
    setSessionId(existingSessionId);

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
      setSessionId(null);
      isStartingRef.current = false;
      addEvent('warn', '🔄', 'Session lost — restarting scanner…');
      await startRef.current(true);
    }
  }, [addEvent, beginPolling, notifyStateChange, onFocusCard, processUpdate, setRunning]);

  const startStockGrabber = async (force = false) => {
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
      setSessionId(data.session_id);
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
      monitoringStore.setGrabberRunning(instanceId, false);
      onUnregisterControls?.(instanceId);
    };
  }, [instanceId, onRegisterControls, onUnregisterControls]);

  useEffect(() => () => {
    stopPolling();
    if (flashTimeoutRef.current) clearTimeout(flashTimeoutRef.current);
  }, [stopPolling]);

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target;
    setFormData((prev) => ({
      ...prev,
      [name]: name === 'order_quantity' || name === 'request_per_sec' ? parseFloat(value) || 0 : value,
    }));
  };

  const changePositive = (liveStats.changePct ?? 0) >= 0;
  const visibleEvents = showEvents ? activity.slice(0, 3) : activity.slice(0, 1);

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
        <div className="sg-symbol-chip">{formData.stock_symbol}</div>
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
        </div>

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
              <input
                id={`rate-${instanceId}`}
                type="number"
                name="request_per_sec"
                className="input"
                value={formData.request_per_sec}
                onChange={handleInputChange}
                disabled={isRunning}
                min={0.5}
                step={0.5}
              />
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
    </div>
  );
};

export default StockGrabber;
