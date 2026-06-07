import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import './StockGrabberPage.css';
import StockGrabber from './StockGrabber';
import GrabberMonitorBar from '../../components/GrabberMonitorBar';
import { monitoringStore } from '../../hooks/monitoringStore';
import { GrabberControls } from '../../types/monitoring';
import { fetchJson, getApiUrl } from '../../utils/api';
import {
  ActiveGrabberFromApi,
  dedupeGrabbers,
  findGrabberByKey,
  loadGrabbers,
  makeGrabberKey,
  mergeWithActiveGrabbers,
  saveGrabbers,
  sortGrabbersRunningFirst,
  StockGrabberInstance,
} from '../../utils/grabberPersistence';

export type { StockGrabberInstance };

const StockGrabberPage: React.FC = () => {
  const [grabbers, setGrabbers] = useState<StockGrabberInstance[]>(() => loadGrabbers());
  const [hydrated, setHydrated] = useState(false);
  const [loggedInClientIDs, setLoggedInClientIDs] = useState<string[]>([]);
  const [newClientId, setNewClientId] = useState('');
  const [newStockSymbol, setNewStockSymbol] = useState('CREST');
  const [addError, setAddError] = useState<string | null>(null);
  const grabberControlsRef = useRef<Map<string, GrabberControls>>(new Map());
  const cardRefs = useRef<Map<string, HTMLDivElement>>(new Map());

  const fetchLoggedInClients = useCallback(async () => {
    try {
      const response = await fetch(`${getApiUrl()}/logged_in_clients/`);
      if (response.ok) {
        const data = await response.json();
        setLoggedInClientIDs(data.logged_in_client_ids);
        if (data.logged_in_client_ids.length > 0) {
          setNewClientId(data.logged_in_client_ids[0]);
        }
      }
    } catch (error) {
      console.error('Error fetching logged-in clients:', error);
    }
  }, []);

  const reconcileActiveGrabbers = useCallback(async () => {
    const result = await fetchJson<{ grabbers: ActiveGrabberFromApi[] }>('/active_stock_grabbers/');
    if (!result.ok) {
      return;
    }
    const active = result.data.grabbers || [];
    setGrabbers((prev) => dedupeGrabbers(mergeWithActiveGrabbers(prev, active)));
  }, []);

  useEffect(() => {
    fetchLoggedInClients();
    void reconcileActiveGrabbers().finally(() => setHydrated(true));
    const interval = window.setInterval(() => {
      void reconcileActiveGrabbers();
    }, 10000);
    return () => window.clearInterval(interval);
  }, [fetchLoggedInClients, reconcileActiveGrabbers]);

  useEffect(() => {
    if (!hydrated) {
      return undefined;
    }
    saveGrabbers(grabbers);
    return undefined;
  }, [grabbers, hydrated]);

  useEffect(() => {
    monitoringStore.setGrabberTotal(grabbers.length);
  }, [grabbers.length]);

  useEffect(() => {
    monitoringStore.setGrabberControlsGetter(() => grabberControlsRef.current);
    return () => monitoringStore.setGrabberControlsGetter(null);
  }, []);

  const registerControls = useCallback((id: string, controls: GrabberControls) => {
    grabberControlsRef.current.set(id, controls);
    monitoringStore.syncActiveFromControls();
  }, []);

  const unregisterControls = useCallback((id: string) => {
    grabberControlsRef.current.delete(id);
    monitoringStore.setGrabberRunning(id, false);
    monitoringStore.syncActiveFromControls();
  }, []);

  const handleGrabberStateChange = useCallback((id: string, patch: Partial<StockGrabberInstance>) => {
    setGrabbers((prev) => prev.map((g) => (g.id === id ? { ...g, ...patch } : g)));
  }, []);

  const scrollToGrabber = useCallback((id: string) => {
    requestAnimationFrame(() => {
      cardRefs.current.get(id)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    });
  }, []);

  const addGrabber = () => {
    const clientId = newClientId.trim();
    const stockSymbol = newStockSymbol.trim().toUpperCase();
    if (!clientId || !stockSymbol) {
      return;
    }

    const existing = findGrabberByKey(grabbers, clientId, stockSymbol);
    if (existing) {
      setAddError(`${stockSymbol} is already in the monitor list for ${clientId}`);
      scrollToGrabber(existing.id);
      return;
    }

    setAddError(null);
    const id = `${clientId}-${stockSymbol}-${Date.now()}`;
    setGrabbers((prev) => dedupeGrabbers([
      ...prev,
      { id, client_id: clientId, stock_symbol: stockSymbol },
    ]));
  };

  const removeGrabber = (id: string) => {
    const controls = grabberControlsRef.current.get(id);
    if (controls?.getIsRunning()) {
      controls.stop();
    }
    setGrabbers((prev) => prev.filter((g) => g.id !== id));
    grabberControlsRef.current.delete(id);
    monitoringStore.setGrabberRunning(id, false);
  };

  const sortedGrabbers = useMemo(() => sortGrabbersRunningFirst(grabbers), [grabbers]);

  const runningGrabberKeys = useMemo(
    () => new Set(
      grabbers
        .filter((g) => g.isRunning)
        .map((g) => makeGrabberKey(g.client_id, g.stock_symbol)),
    ),
    [grabbers],
  );

  const liveCount = grabbers.filter((g) => g.isRunning).length;

  return (
    <div className="stock-grabber-page">
      <GrabberMonitorBar />

      <div className="stock-grabber-hero panel">
        <div className="stock-grabber-hero-content">
          <div className="stock-grabber-hero-icon" aria-hidden="true">⚡</div>
          <div>
            <h2 className="stock-grabber-hero-title">Stock Grabber</h2>
            <p className="stock-grabber-hero-subtitle">
              Add symbols below — each grabber scans at 2% high and orders when price changes.
            </p>
          </div>
        </div>
        {loggedInClientIDs.length > 0 && (
          <span className="badge badge-success">{loggedInClientIDs.length} client(s) online</span>
        )}
      </div>

      <div className="stock-grabber-add-panel panel">
        <div className="stock-grabber-add-header">
          <h3 className="panel-title">Add Grabber</h3>
          <p className="panel-subtitle">Configure client and symbol, then use Start in the control panel above.</p>
        </div>
        <div className="stock-grabber-add-form">
          <div className="form-group">
            <label htmlFor="sgClientId">Client ID</label>
            <select
              id="sgClientId"
              className="select"
              value={newClientId}
              onChange={(e) => setNewClientId(e.target.value)}
              disabled={loggedInClientIDs.length === 0}
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
              <span className="stock-grabber-hint">Log in via TMS Login tab first.</span>
            )}
          </div>
          <div className="form-group">
            <label htmlFor="sgSymbol">Stock Symbol</label>
            <input
              id="sgSymbol"
              type="text"
              className="input"
              value={newStockSymbol}
              onChange={(e) => setNewStockSymbol(e.target.value.toUpperCase())}
              placeholder="e.g. CREST"
            />
          </div>
          <button
            type="button"
            className="btn btn-success"
            onClick={addGrabber}
            disabled={
              !newClientId.trim()
              || !newStockSymbol.trim()
              || Boolean(findGrabberByKey(grabbers, newClientId.trim(), newStockSymbol.trim()))
            }
          >
            + Add Grabber
          </button>
        </div>
        {addError && <p className="stock-grabber-hint">{addError}</p>}
      </div>

      {sortedGrabbers.length > 0 && (
        <div className="stock-grabber-summary">
          <span className="stock-grabber-summary-total">
            {sortedGrabbers.length} monitor{sortedGrabbers.length !== 1 ? 's' : ''}
          </span>
          <span className={`stock-grabber-summary-live ${liveCount > 0 ? 'active' : ''}`}>
            {liveCount > 0 ? `● ${liveCount} live` : 'None running'}
          </span>
          <span className="stock-grabber-summary-hint">Click Recent on a card to expand events</span>
        </div>
      )}

      <div className="stock-grabber-list">
        {sortedGrabbers.length === 0 ? (
          <div className="stock-grabber-empty panel">
            <span style={{ fontSize: '2.5rem', opacity: 0.4 }} aria-hidden="true">📡</span>
            <p>No grabbers yet. Add a client and symbol, then press Start in the monitor bar or top nav.</p>
          </div>
        ) : (
          sortedGrabbers.map((grabber) => (
            <div
              key={grabber.id}
              ref={(el) => {
                if (el) {
                  cardRefs.current.set(grabber.id, el);
                } else {
                  cardRefs.current.delete(grabber.id);
                }
              }}
              className={`stock-grabber-card${grabber.isRunning ? ' running' : ''}`}
            >
              <StockGrabber
                instanceId={grabber.id}
                client_id={grabber.client_id}
                stock_symbol={grabber.stock_symbol}
                symbolAlreadyRunning={
                  runningGrabberKeys.has(makeGrabberKey(grabber.client_id, grabber.stock_symbol))
                  && !grabber.isRunning
                }
                resumeSessionId={grabber.sessionId}
                autoAttach={Boolean(grabber.isRunning && grabber.sessionId)}
                resumeScanCount={grabber.scanCount}
                resumeStableRate={grabber.stableRate}
                initialOrderQuantity={grabber.order_quantity}
                initialRequestPerSec={grabber.request_per_sec}
                onRemove={() => removeGrabber(grabber.id)}
                onRegisterControls={registerControls}
                onUnregisterControls={unregisterControls}
                onStateChange={(state) => handleGrabberStateChange(grabber.id, state)}
                onFocusCard={() => scrollToGrabber(grabber.id)}
              />
            </div>
          ))
        )}
      </div>
    </div>
  );
};

export default StockGrabberPage;
