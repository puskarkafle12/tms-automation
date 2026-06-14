import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import ScheduleOrder from './ScheduleOrder';
import OrderStatus from './OrderLogs';
import Login from './Login';
import './Dashboard.css';
import DPHoldings from './DpHolding';
import StockTable from './StockTable';
import StockGrabberPage from './StockGrabberPage';
import StrategyDetails from './StrategyDetails';
import AppShell, { NavItem } from '../../components/layout/AppShell';
import { pathToTab, TAB_TO_PATH } from '../../routes/control_pannel/dashboardPaths';

const NAV_ITEMS: NavItem[] = [
  { id: 'OrderStatus', label: 'Order Logs', icon: '📋' },
  { id: 'ScheduleOrder', label: 'Schedule Order', icon: '📅' },
  { id: 'DPHoldings', label: 'DP Holdings', icon: '📊' },
  { id: 'Login', label: 'TMS Login', icon: '🔐' },
  { id: 'StockGrabber', label: 'Stock Grabber', icon: '⚡' },
  { id: 'StrategyDetails', label: 'Strategy Details', icon: '🧭' },
  { id: 'StockTable', label: 'Stock Table', icon: '📈' },
];

const PAGE_META: Record<string, { title: string; subtitle: string }> = {
  Login: { title: 'TMS Login', subtitle: 'Connect your broker account to NEPSE TMS' },
  ScheduleOrder: { title: 'Schedule Order', subtitle: 'Queue orders and monitor until price conditions are met' },
  StrategyDetails: { title: 'Strategy Details', subtitle: 'Simple guide for buy and sell strategy logic' },
  OrderStatus: { title: 'Order Logs', subtitle: 'View order history and status updates' },
  CheckOrders: { title: 'Check Orders', subtitle: 'Monitor and verify pending orders' },
  DPHoldings: { title: 'DP Holdings', subtitle: 'Depository participant holdings overview' },
  StockTable: { title: 'Stock Table', subtitle: 'Live market data and stock quotes' },
  StockGrabber: { title: 'Stock Grabber', subtitle: 'Automated stock monitoring and order placement' },
};

type TabUsageStats = Record<string, { visits: number; timeMs: number; lastOpenedAt?: number }>;

const TAB_USAGE_KEY = 'dashboard_tab_usage_stats';

const loadTabUsageStats = (): TabUsageStats => {
  try {
    const raw = localStorage.getItem(TAB_USAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
};

const saveTabUsageStats = (stats: TabUsageStats) => {
  localStorage.setItem(TAB_USAGE_KEY, JSON.stringify(stats));
};

const tabUsageScore = (stats: TabUsageStats, id: string) => {
  const item = stats[id];
  if (!item) return 0;
  return item.visits * 60000 + item.timeMs;
};

const DashBoardPage: React.FC = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const [activeComponent, setActiveComponent] = useState<string>(() => pathToTab(location.pathname));
  const [tabUsageStats, setTabUsageStats] = useState<TabUsageStats>(() => loadTabUsageStats());
  const activeStartedAt = useRef(Date.now());
  const activeComponentRef = useRef(activeComponent);
  const fetchLoggedInClients = useCallback(async () => {
    try {
      const response = await fetch(`${localStorage.getItem('apiUrl') || ''}/logged_in_clients/`);
      if (!response.ok) {
        throw new Error('Failed to fetch logged-in clients');
      }
      const data = await response.json();
      localStorage.setItem('client_ids', JSON.stringify(data.logged_in_client_ids));
    } catch (error) {
      console.error('Error fetching logged-in clients:', error);
    }
  }, []);

  useEffect(() => {
    fetchLoggedInClients();
  }, [fetchLoggedInClients]);

  useEffect(() => {
    setActiveComponent(pathToTab(location.pathname));
  }, [location.pathname]);

  useEffect(() => {
    const nextActive = activeComponent;
    const now = Date.now();
    const previousActive = activeComponentRef.current;
    const elapsed = Math.max(0, now - activeStartedAt.current);

    setTabUsageStats((prev) => {
      const next = {
        ...prev,
        [previousActive]: {
          visits: prev[previousActive]?.visits || 0,
          timeMs: (prev[previousActive]?.timeMs || 0) + elapsed,
          lastOpenedAt: prev[previousActive]?.lastOpenedAt,
        },
        [nextActive]: {
          visits: (prev[nextActive]?.visits || 0) + 1,
          timeMs: prev[nextActive]?.timeMs || 0,
          lastOpenedAt: now,
        },
      };
      saveTabUsageStats(next);
      return next;
    });

    activeComponentRef.current = nextActive;
    activeStartedAt.current = now;
  }, [activeComponent]);

  useEffect(() => {
    const saveCurrentTabTime = () => {
      const now = Date.now();
      const active = activeComponentRef.current;
      const elapsed = Math.max(0, now - activeStartedAt.current);
      const currentStats = loadTabUsageStats();
      saveTabUsageStats({
        ...currentStats,
        [active]: {
          visits: currentStats[active]?.visits || 0,
          timeMs: (currentStats[active]?.timeMs || 0) + elapsed,
          lastOpenedAt: currentStats[active]?.lastOpenedAt,
        },
      });
      activeStartedAt.current = now;
    };

    window.addEventListener('beforeunload', saveCurrentTabTime);
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'hidden') {
        saveCurrentTabTime();
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      saveCurrentTabTime();
      window.removeEventListener('beforeunload', saveCurrentTabTime);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, []);

  const sortedNavItems = useMemo(
    () =>
      [...NAV_ITEMS].sort((a, b) => {
        const scoreDiff = tabUsageScore(tabUsageStats, b.id) - tabUsageScore(tabUsageStats, a.id);
        if (scoreDiff !== 0) return scoreDiff;
        return NAV_ITEMS.findIndex((item) => item.id === a.id) - NAV_ITEMS.findIndex((item) => item.id === b.id);
      }),
    [tabUsageStats],
  );

  const handleNavigate = (id: string) => {
    const nextPath = TAB_TO_PATH[id];
    if (!nextPath) {
      setActiveComponent(id);
      return;
    }

    const currentPath = location.pathname.replace(/\/$/, '').toLowerCase();
    const targetPath = nextPath.replace(/\/$/, '').toLowerCase();
    if (currentPath !== targetPath) {
      navigate(nextPath);
    }
    setActiveComponent(id);
  };

  const pageMeta = PAGE_META[activeComponent] || PAGE_META.OrderStatus;

  const renderContent = () => {
    switch (activeComponent) {
      case 'Login':
        return <Login />;
      case 'ScheduleOrder':
        return <ScheduleOrder />;
      case 'StrategyDetails':
        return <StrategyDetails />;
      case 'OrderStatus':
        return <OrderStatus />;
      case 'DPHoldings':
        return <DPHoldings />;
      case 'StockTable':
        return <StockTable />;
      case 'StockGrabber':
        return <StockGrabberPage />;
      default:
        return <OrderStatus />;
    }
  };

  return (
    <AppShell
      title={pageMeta.title}
      subtitle={pageMeta.subtitle}
      navItems={sortedNavItems}
      activeId={activeComponent}
      onNavigate={handleNavigate}
    >
      <div className="dashboard-panel">{renderContent()}</div>
    </AppShell>
  );
};

export default DashBoardPage;
