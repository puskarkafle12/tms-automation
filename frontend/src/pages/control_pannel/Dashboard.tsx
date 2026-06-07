import React, { useCallback, useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import ScheduleOrder from './ScheduleOrder';
import OrderStatus from './OrderLogs';
import Login from './Login';
import './Dashboard.css';
import DPHoldings from './DpHolding';
import StockTable from './StockTable';
import StockGrabberPage from './StockGrabberPage';
import AppShell, { NavItem } from '../../components/layout/AppShell';
import { pathToTab, TAB_TO_PATH } from '../../routes/control_pannel/dashboardPaths';

const NAV_ITEMS: NavItem[] = [
  { id: 'OrderStatus', label: 'Order Logs', icon: '📋' },
  { id: 'Login', label: 'TMS Login', icon: '🔐' },
  { id: 'ScheduleOrder', label: 'Schedule Order', icon: '📅' },
  { id: 'DPHoldings', label: 'DP Holdings', icon: '📊' },
  { id: 'StockTable', label: 'Stock Table', icon: '📈' },
  { id: 'StockGrabber', label: 'Stock Grabber', icon: '⚡' },
];

const PAGE_META: Record<string, { title: string; subtitle: string }> = {
  Login: { title: 'TMS Login', subtitle: 'Connect your broker account to NEPSE TMS' },
  ScheduleOrder: { title: 'Schedule Order', subtitle: 'Queue orders and monitor until price conditions are met' },
  OrderStatus: { title: 'Order Logs', subtitle: 'View order history and status updates' },
  CheckOrders: { title: 'Check Orders', subtitle: 'Monitor and verify pending orders' },
  DPHoldings: { title: 'DP Holdings', subtitle: 'Depository participant holdings overview' },
  StockTable: { title: 'Stock Table', subtitle: 'Live market data and stock quotes' },
  StockGrabber: { title: 'Stock Grabber', subtitle: 'Automated stock monitoring and order placement' },
};

const DashBoardPage: React.FC = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const [activeComponent, setActiveComponent] = useState<string>(() => pathToTab(location.pathname));
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
    const tabClass = (id: string) =>
      `dashboard-tab-panel${activeComponent === id ? ' active' : ''}`;

    return (
      <div className="dashboard-panel">
        <div className={tabClass('Login')}><Login /></div>
        <div className={tabClass('ScheduleOrder')}><ScheduleOrder /></div>
        <div className={tabClass('OrderStatus')}><OrderStatus /></div>
        <div className={tabClass('DPHoldings')}><DPHoldings /></div>
        <div className={tabClass('StockTable')}><StockTable /></div>
        <div className={tabClass('StockGrabber')}><StockGrabberPage /></div>
      </div>
    );
  };

  return (
    <AppShell
      title={pageMeta.title}
      subtitle={pageMeta.subtitle}
      navItems={NAV_ITEMS}
      activeId={activeComponent}
      onNavigate={handleNavigate}
    >
      {renderContent()}
    </AppShell>
  );
};

export default DashBoardPage;
