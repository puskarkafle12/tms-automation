export const DASHBOARD_BASE = '/dashboard';

export const DASHBOARD_PATHS = {
  orderLogs: `${DASHBOARD_BASE}/order-logs`,
  tmsLogin: `${DASHBOARD_BASE}/tms-login`,
  scheduleOrder: `${DASHBOARD_BASE}/schedule-order`,
  strategyDetails: `${DASHBOARD_BASE}/strategy-details`,
  backtest: `${DASHBOARD_BASE}/backtest`,
  recommendations: `${DASHBOARD_BASE}/recommendations`,
  dpHoldings: `${DASHBOARD_BASE}/dp-holdings`,
  stockTable: `${DASHBOARD_BASE}/stock-table`,
  stockGrabber: `${DASHBOARD_BASE}/stock-grabber`,
  stockAnalysis: `${DASHBOARD_BASE}/stock-analysis`,
  stockScreener: `${DASHBOARD_BASE}/stock-analysis`,
  settings: `${DASHBOARD_BASE}/settings`,
  adminUsers: `${DASHBOARD_BASE}/admin-users`,
} as const;

export const TAB_TO_PATH: Record<string, string> = {
  OrderStatus: DASHBOARD_PATHS.orderLogs,
  Login: DASHBOARD_PATHS.tmsLogin,
  ScheduleOrder: DASHBOARD_PATHS.scheduleOrder,
  StrategyDetails: DASHBOARD_PATHS.strategyDetails,
  Backtest: DASHBOARD_PATHS.backtest,
  Recommendations: DASHBOARD_PATHS.recommendations,
  DPHoldings: DASHBOARD_PATHS.dpHoldings,
  StockTable: DASHBOARD_PATHS.stockTable,
  StockGrabber: DASHBOARD_PATHS.stockGrabber,
  StockAnalysis: DASHBOARD_PATHS.stockAnalysis,
  StockScreener: DASHBOARD_PATHS.stockAnalysis,
  Settings: DASHBOARD_PATHS.settings,
  AdminUsers: DASHBOARD_PATHS.adminUsers,
};

const normalizePath = (pathname: string) => pathname.replace(/\/$/, '').toLowerCase();

export const pathToTab = (pathname: string): string => {
  const path = normalizePath(pathname);

  const mapping: Record<string, string> = {
    [DASHBOARD_BASE]: 'OrderStatus',
    [DASHBOARD_PATHS.orderLogs]: 'OrderStatus',
    [DASHBOARD_PATHS.tmsLogin]: 'Login',
    [DASHBOARD_PATHS.scheduleOrder]: 'ScheduleOrder',
    [DASHBOARD_PATHS.strategyDetails]: 'StrategyDetails',
    [DASHBOARD_PATHS.backtest]: 'Backtest',
    [DASHBOARD_PATHS.recommendations]: 'Recommendations',
    [DASHBOARD_PATHS.dpHoldings]: 'DPHoldings',
    [`${DASHBOARD_BASE}/check-orders`]: 'StockGrabber',
    [DASHBOARD_PATHS.stockTable]: 'StockTable',
    [DASHBOARD_PATHS.stockGrabber]: 'StockGrabber',
    [DASHBOARD_PATHS.stockAnalysis]: 'StockAnalysis',
    [DASHBOARD_PATHS.stockScreener]: 'StockAnalysis',
    [`${DASHBOARD_BASE}/stock-screener`]: 'StockAnalysis',
    [DASHBOARD_PATHS.settings]: 'Settings',
    [DASHBOARD_PATHS.adminUsers]: 'AdminUsers',
    [`${DASHBOARD_BASE}/order-status-logs`]: 'OrderStatus',
    [`${DASHBOARD_BASE}/add-order`]: 'ScheduleOrder',
    [`${DASHBOARD_BASE}/chase-stock`]: 'OrderStatus',
  };

  return mapping[path] || 'OrderStatus';
};
