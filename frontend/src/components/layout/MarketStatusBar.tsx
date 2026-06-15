import React, { useCallback, useEffect, useState } from 'react';
import './MarketStatusBar.css';
import { fetchMarketStatus, MarketStatus } from '../../api/market.api';

const POLL_INTERVAL_MS = 5000;

const formatNepalClock = () => {
  const now = new Date();
  const time = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Kathmandu',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
  }).format(now);

  const date = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Kathmandu',
    weekday: 'short',
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  }).format(now);

  return { time, date };
};

const buildStatusTitle = (status: MarketStatus | null) => {
  if (!status) {
    return 'Market status unavailable';
  }

  const parts = [
    status.tms_session_message,
    `Pre-open: Sun–Fri 10:30 AM–10:45 AM NPT`,
    `Trading hours: Sun–Fri 11:00 AM–3:00 PM NPT`,
  ];

  if (!status.is_trading_day) {
    parts.push('Weekend / non-trading day');
  } else if (status.market_phase === 'pre_open') {
    parts.push('Pre-open session');
  } else if (!status.market_hours_open) {
    parts.push('Outside market hours');
  }

  if (status.client_id) {
    parts.push(`Checked via ${status.client_id}`);
  }

  return parts.filter(Boolean).join(' · ');
};

const MarketStatusBar: React.FC = () => {
  const [clock, setClock] = useState(formatNepalClock);
  const [status, setStatus] = useState<MarketStatus | null>(null);

  const loadStatus = useCallback(async () => {
    try {
      const data = await fetchMarketStatus();
      setStatus(data);
    } catch {
      setStatus(null);
    }
  }, []);

  useEffect(() => {
    const timer = setInterval(() => setClock(formatNepalClock()), 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    void loadStatus();
    const poll = window.setInterval(() => {
      void loadStatus();
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(poll);
  }, [loadStatus]);

  const isMarketOpen = status?.market_live ?? false;
  const isPreOpen = status?.market_phase === 'pre_open';
  const statusClass = isMarketOpen ? 'live' : isPreOpen ? 'pre-open' : 'closed';
  const statusLabel = isMarketOpen ? 'Market Open' : isPreOpen ? 'Pre Open' : 'Market Closed';

  return (
    <div className="market-status-bar">
      <div className="market-status-clock">
        <span className="market-status-time" title="Nepal Time (NPT)">
          {clock.time} NPT
        </span>
        <span className="market-status-date">{clock.date}</span>
      </div>
      <span
        className={`market-status-pill ${statusClass}`}
        title={buildStatusTitle(status)}
      >
        <span className="market-status-dot" />
        {statusLabel}
      </span>
    </div>
  );
};

export default MarketStatusBar;
