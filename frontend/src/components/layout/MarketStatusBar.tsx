import React, { useCallback, useEffect, useRef, useState } from 'react';
import './MarketStatusBar.css';
import { fetchMarketStatus, MarketStatus } from '../../api/market.api';
import { serverUtcToMs } from '../../api/time.api';
import { formatNepalClockFromUtcMs, setServerTodayNpt } from '../../utils/nepalTime';
import { readUiPortalSettings, subscribeUiPortalSettings } from '../../lib/uiPortalSettings';

const CLOCK_TICK_MS = 1000;

const buildStatusTitle = (status: MarketStatus | null) => {
  if (!status) {
    return 'Market status unavailable';
  }

  const dnaStatus = status.dna_status === 'LOGGED_IN'
    ? 'DNA logged in'
    : status.dna_status === 'LOGGED_OFF'
      ? 'DNA logged off'
      : status.tms_session_active
        ? 'DNA session active'
        : 'DNA session inactive';

  const parts = [
    dnaStatus,
    status.tms_session_message,
    `DNA market check: Sun–Fri 11:00 AM–3:00 PM NPT`,
  ];

  if (status.market_phase === 'open') {
    parts.push('DNA status is SUCCESS');
  } else if (status.market_phase === 'pre_open') {
    parts.push('Pre-open session');
  } else if (status.market_phase === 'checking') {
    parts.push('Checking the shared TMS market session');
  } else if (!status.market_polling_window) {
    parts.push('Outside the Sun–Fri market polling window');
  }

  if (status.client_id) {
    parts.push(`Checked via ${status.client_id}`);
  }

  parts.push('DNA SUCCESS is the sole market-live signal');

  return parts.filter(Boolean).join(' · ');
};

const MarketStatusBar: React.FC = () => {
  const [status, setStatus] = useState<MarketStatus | null>(null);
  const [, setClockTick] = useState(0);
  const [statusPollMs, setStatusPollMs] = useState(() => readUiPortalSettings().marketStatusPollSeconds * 1000);
  const serverUtcRef = useRef<number | null>(null);
  const anchorMsRef = useRef<number>(Date.now());

  useEffect(() => subscribeUiPortalSettings((settings) => {
    setStatusPollMs(settings.marketStatusPollSeconds * 1000);
  }), []);

  const syncClockAnchor = useCallback((data: MarketStatus) => {
    const utcMs = serverUtcToMs(data.server_time);
    if (utcMs == null) {
      return;
    }
    serverUtcRef.current = utcMs;
    anchorMsRef.current = Date.now();
  }, []);

  const loadStatus = useCallback(async () => {
    try {
      const data = await fetchMarketStatus();
      setStatus(data);
      syncClockAnchor(data);
      if (data.today_npt) {
        setServerTodayNpt(data.today_npt);
      }
    } catch {
      setStatus(null);
    }
  }, [syncClockAnchor]);

  useEffect(() => {
    void loadStatus();
    const poll = window.setInterval(() => {
      void loadStatus();
    }, statusPollMs);
    return () => window.clearInterval(poll);
  }, [loadStatus, statusPollMs]);

  useEffect(() => {
    const tick = window.setInterval(() => {
      setClockTick((value) => value + 1);
    }, CLOCK_TICK_MS);
    return () => window.clearInterval(tick);
  }, []);

  const liveUtcMs = serverUtcRef.current == null
    ? null
    : serverUtcRef.current + (Date.now() - anchorMsRef.current);
  const liveClock = liveUtcMs == null ? null : formatNepalClockFromUtcMs(liveUtcMs);

  const isMarketOpen = status?.market_phase === 'open';
  const isPreOpen = status?.market_phase === 'pre_open';
  const isChecking = status?.market_phase === 'checking';
  const statusClass = isMarketOpen ? 'live' : isPreOpen ? 'pre-open' : 'closed';
  const statusLabel = isMarketOpen
    ? 'Market Open'
    : isPreOpen
      ? 'Pre Open'
      : isChecking
        ? 'Checking Market'
        : 'Market Closed';
  const pillTitle = buildStatusTitle(status);
  const clockTime = liveClock?.time || status?.nepal_time_formatted || status?.server_time?.time || '--:--:--';
  const clockDate = liveClock?.date || status?.nepal_date_formatted || status?.server_time?.date || '';
  const clockTitle = liveClock?.display || status?.nepal_time_display || 'Nepal Time (NPT)';

  return (
    <div className="market-status-bar">
      <div className="market-status-clock">
        <span className="market-status-time" title={clockTitle}>
          {clockTime} NPT
        </span>
        <span className="market-status-date">{clockDate}</span>
      </div>
      <span
        className={`market-status-pill ${statusClass}`}
        title={pillTitle}
      >
        <span className="market-status-dot" />
        {statusLabel}
      </span>
    </div>
  );
};

export default MarketStatusBar;
