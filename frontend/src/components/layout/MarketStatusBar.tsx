import React, { useCallback, useEffect, useState } from 'react';
import './MarketStatusBar.css';
import { fetchMarketStatus, MarketStatus } from '../../api/market.api';

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
    loadStatus();
    const poll = setInterval(loadStatus, 30000);
    return () => clearInterval(poll);
  }, [loadStatus]);

  const isMarketLive = status?.market_live ?? false;

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
        className={`market-status-pill ${isMarketLive ? 'live' : 'closed'}`}
        title={isMarketLive ? 'DNA logged in — market is live' : 'DNA logged off — market is closed'}
      >
        <span className="market-status-dot" />
        {isMarketLive ? 'Market Live' : 'Market Closed'}
      </span>
    </div>
  );
};

export default MarketStatusBar;
