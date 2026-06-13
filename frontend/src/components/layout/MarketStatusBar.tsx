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
    `Trading hours: Sun–Fri 9:00 AM–3:00 PM NPT`,
  ];

  if (!status.is_trading_day) {
    parts.push('Weekend / non-trading day');
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
  const statusLabel = isMarketOpen ? 'Market Open' : 'Market Closed';

  const displayTime = status?.nepal_time_formatted || clock.time;
  const displayDate = status?.nepal_date_formatted || clock.date;

  return (
    <div className="market-status-bar">
      <div className="market-status-clock">
        <span className="market-status-time" title="Nepal Time (NPT)">
          {displayTime} NPT
        </span>
        <span className="market-status-date">{displayDate}</span>
      </div>
      <span
        className={`market-status-pill ${isMarketOpen ? 'live' : 'closed'}`}
        title={buildStatusTitle(status)}
      >
        <span className="market-status-dot" />
        {statusLabel}
      </span>
    </div>
  );
};

export default MarketStatusBar;
