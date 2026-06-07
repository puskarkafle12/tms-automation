import React, { useCallback, useEffect, useRef, useState } from 'react';
import './StockGrabberPage.css';
import StockGrabber from './StockGrabber';
import GrabberMonitorBar from '../../components/GrabberMonitorBar';
import { monitoringStore } from '../../hooks/monitoringStore';
import { GrabberControls } from '../../types/monitoring';

export interface StockGrabberInstance {
  id: string;
  client_id: string;
  stock_symbol: string;
}

const getApiUrl = () => localStorage.getItem('apiUrl') || 'http://localhost:8000';

const StockGrabberPage: React.FC = () => {
  const [grabbers, setGrabbers] = useState<StockGrabberInstance[]>([]);
  const [loggedInClientIDs, setLoggedInClientIDs] = useState<string[]>([]);
  const [newClientId, setNewClientId] = useState('');
  const [newStockSymbol, setNewStockSymbol] = useState('CREST');
  const grabberControlsRef = useRef<Map<string, GrabberControls>>(new Map());

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

  useEffect(() => {
    fetchLoggedInClients();
  }, [fetchLoggedInClients]);

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

  const addGrabber = () => {
    if (!newClientId.trim() || !newStockSymbol.trim()) {
      return;
    }
    const id = `${newClientId}-${newStockSymbol}-${Date.now()}`;
    setGrabbers((prev) => [
      ...prev,
      { id, client_id: newClientId.trim(), stock_symbol: newStockSymbol.trim().toUpperCase() },
    ]);
  };

  const removeGrabber = (id: string) => {
    setGrabbers((prev) => prev.filter((g) => g.id !== id));
    grabberControlsRef.current.delete(id);
    monitoringStore.setGrabberRunning(id, false);
  };

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
            disabled={!newClientId.trim() || !newStockSymbol.trim()}
          >
            + Add Grabber
          </button>
        </div>
      </div>

      <div className="stock-grabber-list">
        {grabbers.length === 0 ? (
          <div className="stock-grabber-empty panel">
            <span style={{ fontSize: '2.5rem', opacity: 0.4 }} aria-hidden="true">📡</span>
            <p>No grabbers yet. Add a client and symbol, then press Start in the monitor bar or top nav.</p>
          </div>
        ) : (
          grabbers.map((grabber) => (
            <StockGrabber
              key={grabber.id}
              instanceId={grabber.id}
              client_id={grabber.client_id}
              stock_symbol={grabber.stock_symbol}
              onRemove={() => removeGrabber(grabber.id)}
              onRegisterControls={registerControls}
              onUnregisterControls={unregisterControls}
            />
          ))
        )}
      </div>
    </div>
  );
};

export default StockGrabberPage;
