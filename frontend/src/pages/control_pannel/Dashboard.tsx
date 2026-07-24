import React, { useCallback, useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import ScheduleOrder from './ScheduleOrder';
import OrderStatus from './OrderLogs';
import Login from './Login';
import './Dashboard.css';
import DPHoldings from './DpHolding';
import StockTable from './StockTable';
import StockGrabberPage from './StockGrabberPage';
import StockAnalysis from './StockAnalysis';
import StrategyDetails from './StrategyDetails';
import Settings from './Settings';
import Backtest from './Backtest';
import BacktestV2 from './BacktestV2';
import Recommendations from './Recommendations';
import AdminUsers from './AdminUsers';
import { AuthUser, authService } from '../../services/authService';
import AppShell, { NavItem } from '../../components/layout/AppShell';
import { pathToTab, TAB_TO_PATH } from '../../routes/control_pannel/dashboardPaths';

const EDIS_URL = 'https://bulk-ipo.onrender.com/#edis';

const NAV_ITEMS: NavItem[] = [
  { id: 'OrderStatus', label: 'Order Logs', icon: '📋' },
  { id: 'ScheduleOrder', label: 'Schedule Order', icon: '📅' },
  { id: 'DPHoldings', label: 'Portfolio', icon: '📊' },
  { id: 'StockAnalysis', label: 'Market Analysis', icon: '🔎' },
  { id: 'StockGrabber', label: 'Stock Grabber', icon: '⚡' },
  { id: 'StrategyDetails', label: 'Strategy Details', icon: '🧭' },
  { id: 'Backtest', label: 'Backtest Lab', icon: '🧪' },
  { id: 'Recommendations', label: 'Recommendations', icon: '🎯' },
  { id: 'StockTable', label: 'Stock Table', icon: '📈' },
  { id: 'EDIS', label: 'EDIS', icon: '📝' },
  { id: 'Settings', label: 'Settings', icon: '⚙️' },
  { id: 'Login', label: 'TMS Login', icon: '🔐' },
  { id: 'AdminUsers', label: 'User Access', icon: '👥' },
  { id: 'SignOut', label: 'Sign Out', icon: '↪' },
];
const NAV_PERMISSION: Record<string,string>={OrderStatus:'order_logs',ScheduleOrder:'schedule_orders',DPHoldings:'portfolio',StockAnalysis:'market_analysis',StockGrabber:'stock_grabber',StrategyDetails:'strategy_details',Backtest:'backtest',Recommendations:'recommendations',StockTable:'stock_table',EDIS:'edis',Settings:'settings',Login:'tms_login',AdminUsers:'admin_users'};

const PAGE_META: Record<string, { title: string; subtitle: string }> = {
  Login: { title: 'TMS Login', subtitle: 'Connect your broker account to NEPSE TMS' },
  ScheduleOrder: { title: 'Schedule Order', subtitle: 'Queue orders and monitor until price conditions are met' },
  StrategyDetails: { title: 'Strategy Details', subtitle: 'Simple guide for buy and sell strategy logic' },
  Backtest: { title: 'Strategy Backtest', subtitle: 'Test custom queries on historical NEPSE market data' },
  Recommendations: { title: 'Recommendations', subtitle: 'Fresh signals powered by Market Analysis and backtesting' },
  OrderStatus: { title: 'Order Logs', subtitle: 'View order history and status updates' },
  CheckOrders: { title: 'Check Orders', subtitle: 'Monitor and verify pending orders' },
  DPHoldings: { title: 'Portfolio', subtitle: 'Holdings, buy cost, and profit/loss overview' },
  StockTable: { title: 'Stock Table', subtitle: 'Live market data and stock quotes' },
  StockAnalysis: { title: 'Market Analysis', subtitle: '' },
  StockGrabber: { title: 'Stock Grabber', subtitle: 'Automated stock monitoring and order placement' },
  Settings: { title: 'Settings', subtitle: 'Monitoring speed, defaults, and portal refresh behavior' },
  AdminUsers: { title: 'User Access', subtitle: 'Assign roles, tabs, and account access' },
};

const DashBoardPage: React.FC = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const [activeComponent, setActiveComponent] = useState<string>(() => pathToTab(location.pathname));
  const [authUser,setAuthUser]=useState<AuthUser|null>(()=>authService.storedUser());
  useEffect(()=>{void authService.me().then(setAuthUser).catch(()=>navigate('/'));},[navigate]);
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
  useEffect(()=>{
    if(!authUser)return;
    const required=NAV_PERMISSION[activeComponent];
    if(!required||authUser.permissions.includes(required))return;
    const fallback=NAV_ITEMS.find((item)=>NAV_PERMISSION[item.id]&&authUser.permissions.includes(NAV_PERMISSION[item.id])&&TAB_TO_PATH[item.id]);
    navigate(fallback?TAB_TO_PATH[fallback.id]:'/',{replace:true});
  },[activeComponent,authUser,navigate]);

  const handleNavigate = (id: string) => {
    if (id === 'SignOut') { void authService.logout().finally(()=>navigate('/')); return; }
    if (id === 'EDIS') {
      window.open(EDIS_URL, '_blank', 'noopener,noreferrer');
      return;
    }

    const nextPath = TAB_TO_PATH[id];
    if (!nextPath) {
      setActiveComponent(id);
      return;
    }

    const currentPath = location.pathname.replace(/\/$/, '').toLowerCase();
    const targetPath = nextPath.replace(/\/$/, '').toLowerCase();
    const reopenBacktestLab = id === 'Backtest' && currentPath === targetPath && Boolean(location.search);
    if (currentPath !== targetPath || reopenBacktestLab) {
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
      case 'Backtest':
        return new URLSearchParams(location.search).get('legacy') === '1'
          ? <Backtest key={location.search} />
          : <BacktestV2 key={location.search} />;
      case 'Recommendations':
        return <Recommendations />;
      case 'OrderStatus':
        return <OrderStatus />;
      case 'DPHoldings':
        return <DPHoldings />;
      case 'StockTable':
        return <StockTable />;
      case 'StockGrabber':
        return <StockGrabberPage />;
      case 'StockAnalysis':
        return <StockAnalysis />;
      case 'Settings':
        return <Settings />;
      case 'AdminUsers':
        return <AdminUsers />;
      default:
        return <OrderStatus />;
    }
  };

  return (
    <AppShell
      title={pageMeta.title}
      subtitle={pageMeta.subtitle}
      navItems={NAV_ITEMS.filter((item)=>item.id==='SignOut'||!NAV_PERMISSION[item.id]||authUser?.permissions.includes(NAV_PERMISSION[item.id]))}
      activeId={activeComponent}
      onNavigate={handleNavigate}
      canSchedule={Boolean(authUser?.permissions.includes('schedule_orders'))}
      canUseGrabber={Boolean(authUser?.permissions.includes('stock_grabber'))}
    >
      <div className="dashboard-panel">{renderContent()}</div>
    </AppShell>
  );
};

export default DashBoardPage;
