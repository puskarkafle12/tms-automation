import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import './OrderLogs.css';
import CommonTable from '../../components/table/Table';
import DialogBox from '../../components/dialog_box/DialogBox';
import ErrorMessage from '../../components/ErrorMessage';
import 'react-datepicker/dist/react-datepicker.css';
import DatePicker from 'react-datepicker';
import { syncMonitoringStatus } from '../../hooks/monitoringSync';
import {
  dateFromNepalDateString,
  formatNepalDateTime,
  nepalDateStringFromDate,
  offsetNepalDate,
  todayNepalDate,
} from '../../utils/nepalTime';
import {
  FOREVER_FROM_DATE,
  historyRangeLabel,
  HistoryRangePreset,
  resolveHistoryDateRange,
} from '../../utils/orderHistoryRange';
import { formatStrategyLabel } from '../../lib/strategies';
import EditScheduledOrderModal from './EditScheduledOrderModal';
import NepseAlphaSymbolLink from '../../components/NepseAlphaSymbolLink';
import StrategyCatalogModal from '../../components/StrategyCatalogModal';

type OrderTab = 'logs' | 'scheduled' | 'book' | 'history';

const CACHE_TTL_MS = 20 * 60 * 1000;
const CORE_CACHE_STORAGE_KEY = 'tms-order-logs-core-v1';
const TRADE_BOOK_CACHE_STORAGE_KEY = 'tms-order-logs-trade-book-v1';
const HISTORY_CACHE_STORAGE_KEY = 'tms-order-logs-history-v1';

const HISTORY_RANGE_OPTIONS: { id: HistoryRangePreset; label: string }[] = [
  { id: 'week', label: '1 Week' },
  { id: 'month', label: '1 Month' },
  { id: 'custom', label: 'Custom' },
  { id: 'forever', label: 'All Time' },
];

interface ScheduledOrderRow {
  order_id: number;
  client_id: string;
  script_name: string;
  price: number;
  qty: number;
  status: string;
  order_type: string;
  created_at?: string | null;
  strategy_type?: string;
  side?: string;
  stop_loss_price?: number | null;
  stop_limit_price?: number | null;
  book_profit_price?: number | null;
  profit_target_price?: number | null;
  trailing_drop_percent?: number | null;
  stable_band_percent?: number | null;
  minimum_wait_minutes?: number | null;
  consecutive_drop_checks?: number | null;
  activation_price?: number | null;
  average_buy_price?: number | null;
  highest_tracked_price?: number | null;
  target_reached_at?: string | null;
  execution_price?: number | null;
  execution_price_source?: string | null;
  execution_reason?: string | null;
  requested_price?: number | null;
  expiry_time?: string | null;
  expiry_action?: string | null;
  max_allowed_slippage_percent?: number | null;
  scanning_count?: number;
  current_price?: number | null;
  live_status?: string;
  actionRequired?: boolean;
  editable?: boolean;
  executed_at?: string | null;
  partial_legs?: Array<{ id?: string; targetPrice?: number; sellPercent?: number }>;
  strategy_config?: Record<string, unknown>;
  security_details?: Record<string, unknown>;
}

interface ClientSession {
  client_id: string;
  display_name?: string | null;
  broker_no?: string | null;
}

const formatClientLabel = (session?: ClientSession | null, fallbackClientId = '') => {
  if (!session) {
    return fallbackClientId;
  }
  const name = session.display_name?.trim() || session.client_id || fallbackClientId;
  const broker = session.broker_no?.trim();
  return broker ? `${name}[${broker}]` : name;
};

const StockClientCell: React.FC<{ symbol: string; clientLabel: string }> = ({ symbol, clientLabel }) => (
  <div className="order-log-stock-cell">
    <strong>
      {symbol ? <NepseAlphaSymbolLink symbol={symbol} /> : '-'}
    </strong>
    {clientLabel && <span>{clientLabel}</span>}
  </div>
);

const formatScanCount = (value: number | null | undefined): number => {
  return Math.max(0, Math.round(Number(value) || 0));
};

const formatLiveScanStatus = (order: ScheduledOrderRow): string => {
  if (order.live_status) {
    return order.live_status;
  }
  return order.status || 'pending';
};

const isRealValue = (value: unknown): boolean => {
  if (value == null) return false;
  if (typeof value === 'string') return value.trim() !== '';
  return true;
};

const getVisibleColumns = (rows: any[], baseColumns: string[], optionalColumns: string[] = []) => [
  ...baseColumns,
  ...optionalColumns.filter((column) => rows.some((row) => isRealValue(row[column]))),
];

const getOrderSide = (order: Partial<ScheduledOrderRow> | any): 'BUY' | 'SELL' | 'UNKNOWN' => {
  const side = String(order.side || order.order_type || '').toUpperCase();
  if (side === 'BUY' || side === 'SELL') return side;
  return 'UNKNOWN';
};

const formatStrategyType = (strategy: unknown, sideValue: unknown): string => {
  const side = String(sideValue || '').toLowerCase();
  return formatStrategyLabel(String(strategy || ''), side);
};

const formatDateTime = (value: string | null | undefined) => {
  return formatNepalDateTime(value);
};

const formatCurrency = (value: number | string | null | undefined) => {
  if (value == null || value === '' || Number.isNaN(Number(value))) return '';
  return `Rs. ${Number(value).toLocaleString('en-NP', { maximumFractionDigits: 2 })}`;
};

const formatTradeAmount = (value: number | string | null | undefined) => {
  if (value == null || value === '' || Number.isNaN(Number(value))) return '-';
  return Number(value).toLocaleString('en-NP', { maximumFractionDigits: 2 });
};

const formatTradeSide = (value: unknown) => {
  const side = Number(value);
  if (side === 1) return 'BUY';
  if (side === 2) return 'SELL';
  return value != null && value !== '' ? String(value) : '-';
};

const isCacheFresh = (fetchedAt: number | null | undefined) =>
  fetchedAt != null && Date.now() - fetchedAt < CACHE_TTL_MS;

const tradeBookClientKey = (clientIds: string[]) => [...clientIds].sort().join(',');

const isScheduledOrderEditable = (order: ScheduledOrderRow) => {
  if (order.editable === false || order.executed_at) {
    return false;
  }
  const status = String(order.status || '').trim().toLowerCase();
  return ![
    'completed',
    'complete',
    'executed',
    'cancelled',
    'canceled',
    'failed',
    'expired',
    'order_placed',
    'order placed',
    'partially executed',
  ].includes(status);
};

const formatPercent = (value: number | null | undefined) => {
  if (value == null || Number.isNaN(Number(value))) return '';
  return `${value}%`;
};

const addDetail = (items: Array<{ label: string; value: string }>, label: string, value: unknown, formatter?: (value: any) => string) => {
  if (!isRealValue(value)) return;
  const formatted = formatter ? formatter(value) : String(value);
  if (isRealValue(formatted)) {
    items.push({ label, value: formatted });
  }
};

const getStrategyDetails = (order: ScheduledOrderRow) => {
  const side = getOrderSide(order);
  const strategy = formatStrategyType(order.strategy_type, side);
  const details: Array<{ label: string; value: string }> = [];

  addDetail(details, 'Strategy', strategy);
  addDetail(details, 'Side', side);
  addDetail(details, 'Stock', order.script_name);
  addDetail(details, 'Quantity', order.qty);
  addDetail(details, 'Status', order.status || order.live_status);
  addDetail(details, 'Created At', order.created_at, formatDateTime);

  if (strategy === 'Fixed Price Buy') {
    addDetail(details, 'Buy Price', order.price, formatCurrency);
  } else if (strategy === 'Fixed Price Sell') {
    addDetail(details, 'Sell Price', order.price, formatCurrency);
  } else if (strategy === 'Smart Pullback Buy' || strategy === 'Confirmed Breakout Buy') {
    addDetail(details, 'Trigger Buy Price', order.price, formatCurrency);
  } else if (strategy === 'Quality Pullback Recovery Buy' || strategy === 'Mean Reversion Bounce Buy' || strategy === 'Order Book Strength Buy') {
    addDetail(details, 'Reference Price', order.price, formatCurrency);
    addDetail(details, 'Min Buy Score', (order as any).strategy_config?.min_buy_score);
  } else if (strategy === 'Time-Based Buy') {
    addDetail(details, 'Buy Price', order.price, formatCurrency);
    addDetail(details, 'Wrapped Strategy', (order as any).strategy_config?.wrapped_strategy_type);
    addDetail(details, 'Expiry Time', order.expiry_time, formatDateTime);
    addDetail(details, 'Expiry Action', order.expiry_action);
  } else if (strategy === 'Capital Protection Sell') {
    addDetail(details, 'Scheduled Price', order.requested_price ?? order.price, formatCurrency);
    addDetail(details, 'Stop Loss Price', order.stop_loss_price, formatCurrency);
    addDetail(details, 'Highest Tracked Price', order.highest_tracked_price, formatCurrency);
    addDetail(details, 'Trailing Stop %', order.trailing_drop_percent, formatPercent);
    addDetail(details, 'Average Buy Price', order.average_buy_price, formatCurrency);
    addDetail(details, 'Break-even Trigger %', (order as any).strategy_config?.break_even_trigger_pct, formatPercent);
    addDetail(details, 'Max Allowed Slippage', order.max_allowed_slippage_percent, formatPercent);
  } else if (strategy === 'Trailing Runner Sell') {
    addDetail(details, 'Activation Price', order.activation_price, formatCurrency);
    addDetail(details, 'Highest Tracked Price', order.highest_tracked_price, formatCurrency);
    addDetail(details, 'Trailing Drop', order.trailing_drop_percent, formatPercent);
  } else if (strategy === 'Profit Ladder Sell') {
    addDetail(details, 'Profit Target', order.profit_target_price, formatCurrency);
    addDetail(details, 'Highest Tracked Price', order.highest_tracked_price, formatCurrency);
    addDetail(details, 'Trailing Drop', order.trailing_drop_percent, formatPercent);
  } else if (strategy === 'Technical Weakness Sell') {
    addDetail(details, 'Execution Rule', 'Sell when Nepse Alpha technicals and live price both weaken.');
  } else if (strategy === 'Time-Based Exit') {
    addDetail(details, 'Stop Loss Price', order.stop_loss_price, formatCurrency);
    addDetail(details, 'Expiry Time', order.expiry_time, formatDateTime);
    addDetail(details, 'Expiry Action', order.expiry_action);
  } else if (strategy === 'Emergency Exit by Top Buyer') {
    addDetail(details, 'Execution Rule', 'Sell immediately using Top Buy if available.');
    addDetail(details, 'Max Allowed Slippage', order.max_allowed_slippage_percent, formatPercent);
  }

  addDetail(details, 'Execution Price', order.execution_price, formatCurrency);
  addDetail(details, 'Execution Price Source', order.execution_price_source);
  addDetail(details, 'Execution Reason', order.execution_reason);
  return details;
};

const TABS: { id: OrderTab; label: string; icon: string }[] = [
  { id: 'scheduled', label: 'Scheduled', icon: '📅' },
  { id: 'logs', label: 'Order Logs', icon: '📋' },
  { id: 'book', label: 'Trade Book', icon: '📖' },
  { id: 'history', label: 'History', icon: '🕐' },
];

const OPEN_TRADE_COLUMNS = [
  'stock',
  'buyOrSell',
  'orderQuantity',
  'orderPrice',
  'orderTime',
  'activeStatus',
  'remainingOrderQuantity',
  'exchangeOrderId',
];

const DAILY_TRADE_COLUMNS = [
  'stock',
  'buyOrSell',
  'orderQuantity',
  'orderPrice',
  'orderTime',
  'activeStatus',
  'totalTradedQuantity',
  'exchangeOrderId',
];

const COMPLETED_STATUS_RANK = new Set([
  'completed',
  'complete',
  'executed',
  'partially executed',
  'order_placed',
  'order placed',
  'placed',
]);

const orderTimestamp = (order: any) => {
  const timestamp = new Date(order?.timestamp || order?.created_at || 0).getTime();
  return Number.isFinite(timestamp) ? timestamp : 0;
};

const isCompletedStatus = (status: unknown) => {
  const normalized = String(status || '').trim().toLowerCase();
  return COMPLETED_STATUS_RANK.has(normalized);
};

const GetOrderStatus: React.FC = () => {
  const [orderedDate, setOrderedDate] = useState<string>(todayNepalDate);
  const [selectedClientId, setSelectedClientId] = useState('');
  const [scriptName, setScriptName] = useState('');
  const scriptNameRef = useRef(scriptName);
  useEffect(() => {
    scriptNameRef.current = scriptName;
  }, [scriptName]);
  const [orderLogs, setOrderLogs] = useState<any[]>([]);
  const [scheduledOrders, setScheduledOrders] = useState<ScheduledOrderRow[]>([]);
  const [orderBook, setOrderBook] = useState<any[]>([]);
  const [dailyOrderBook, setDailyOrderBook] = useState<any[]>([]);
  const [orderHistory, setOrderHistory] = useState<any[]>([]);
  const [historyRangePreset, setHistoryRangePreset] = useState<HistoryRangePreset>('week');
  const [historyFromDate, setHistoryFromDate] = useState(() => offsetNepalDate(todayNepalDate(), { days: 7 }));
  const [historyToDate, setHistoryToDate] = useState(() => todayNepalDate());
  const [isLoading, setIsLoading] = useState(true);
  const [isHistoryLoading, setIsHistoryLoading] = useState(false);
  const [isTradeBookLoading, setIsTradeBookLoading] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [hasLoaded, setHasLoaded] = useState(false);
  const [tradeBookLoaded, setTradeBookLoaded] = useState(false);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const coreCacheRef = useRef<number | null>(null);
  const tradeBookCacheRef = useRef<{ clientKey: string; fetchedAt: number } | null>(null);
  const historyCacheRef = useRef<{ key: string; rows: any[]; fetchedAt: number } | null>(null);
  const historyRequestIdRef = useRef(0);
  const [loggedInClientIDs, setLoggedInClientIDs] = useState<string[]>([]);
  const [clientSessions, setClientSessions] = useState<ClientSession[]>([]);
  const [activeTab, setActiveTab] = useState<OrderTab>('scheduled');
  const [dialogVisible, setDialogVisible] = useState(false);
  const [dialogMessage, setDialogMessage] = useState('');
  const [dialogAction, setDialogAction] = useState<() => void>(() => {});
  const [strategyDetailsOrder, setStrategyDetailsOrder] = useState<ScheduledOrderRow | null>(null);
  const [strategyCatalogGuide, setStrategyCatalogGuide] = useState<{ name: string; side: 'buy' | 'sell' } | null>(null);
  const [editingOrderId, setEditingOrderId] = useState<number | null>(null);
  const [errorMessage, setErrorMessage] = useState('');
  const [successMessage, setSuccessMessage] = useState('');
  const [clientsFetched, setClientsFetched] = useState(false);
  const apiUrl = localStorage.getItem('apiUrl') || window.location.origin;

  const fetchLoggedInClientIDs = useCallback(async () => {
    try {
      const response = await fetch(`${apiUrl}/logged_in_clients/`);
      if (response.ok) {
        const data = await response.json();
        const sessions: ClientSession[] = Array.isArray(data.sessions)
          ? data.sessions
          : (data.logged_in_client_ids || []).map((id: string) => ({ client_id: id }));
        setClientSessions(sessions);
        setLoggedInClientIDs(sessions.map((session) => session.client_id));
      } else {
        setClientSessions([]);
        setLoggedInClientIDs([]);
        setErrorMessage('Failed to fetch logged-in client IDs');
      }
    } catch (error: any) {
      setClientSessions([]);
      setLoggedInClientIDs([]);
      setErrorMessage(`Error fetching logged-in client IDs: ${error.message}`);
    } finally {
      setClientsFetched(true);
    }
  }, [apiUrl]);

  useEffect(() => {
    fetchLoggedInClientIDs();
  }, [fetchLoggedInClientIDs]);

  const handleDateChange = (date: Date | null) => {
    setOrderedDate(nepalDateStringFromDate(date));
  };

  const clientLabelMap = useMemo(() => {
    const labels = new Map<string, string>();
    clientSessions.forEach((session) => {
      labels.set(session.client_id, formatClientLabel(session, session.client_id));
    });
    return labels;
  }, [clientSessions]);

  const getClientLabel = useCallback(
    (clientId: string) => clientLabelMap.get(clientId) || clientId,
    [clientLabelMap],
  );

  const activeClientIds = useMemo(
    () => (selectedClientId ? [selectedClientId] : loggedInClientIDs),
    [loggedInClientIDs, selectedClientId],
  );

  const buildHistoryCacheKey = useCallback(
    (clientIds: string[], preset: HistoryRangePreset = historyRangePreset) => {
      const { fromDate, toDate } = resolveHistoryDateRange(
        preset,
        historyFromDate,
        historyToDate,
      );
      return `${clientIds.join(',')}|${fromDate}|${toDate}`;
    },
    [historyFromDate, historyRangePreset, historyToDate],
  );

  const fetchOrderBook = useCallback(async (selectedClientId: string) => {
    if (!selectedClientId) {
      return [];
    }
    const response = await fetch(`${apiUrl}/get_order_book?client_id=${selectedClientId}`);
    if (response.ok) {
      const rows = await response.json();
      return Array.isArray(rows)
        ? rows.map((row) => ({ ...row, client_id: selectedClientId }))
        : [];
    }
    return [];
  }, [apiUrl]);

  const fetchDailyOrderBook = useCallback(async (selectedClientId: string) => {
    if (!selectedClientId) {
      return [];
    }
    const response = await fetch(`${apiUrl}/get_daily_order_book?client_id=${selectedClientId}`);
    if (response.ok) {
      const rows = await response.json();
      return Array.isArray(rows)
        ? rows.map((row) => ({ ...row, client_id: selectedClientId }))
        : [];
    }
    return [];
  }, [apiUrl]);

  const fetchOrderStatusLogs = useCallback(
    async (options?: { silent?: boolean }) => {
      const params = new URLSearchParams();
      const filterScript = scriptNameRef.current.trim();
      if (filterScript) {
        params.set('script_name', filterScript);
      }
      if (selectedClientId) {
        params.set('client_id', selectedClientId);
      }
      if (orderedDate) {
        params.set('ordered_date', orderedDate);
      }
      const response = await fetch(`${apiUrl}/order_status_logs/?${params.toString()}`, {
        headers: { Accept: 'application/json' },
        cache: 'no-store',
      });
      if (response.ok) {
        const data = await response.json();
        const nextOrderLogs = data.order_logs || [];
        const nextScheduledOrders = (data.scheduled_orders || []).map((order: ScheduledOrderRow) => ({
          ...order,
          actionRequired: true,
        }));
        setOrderLogs(nextOrderLogs);
        setScheduledOrders(nextScheduledOrders);
        void syncMonitoringStatus();
        return { orderLogs: nextOrderLogs, scheduledOrders: nextScheduledOrders };
      }
      setOrderLogs([]);
      setScheduledOrders([]);
      if (!options?.silent) {
        throw new Error('Failed to fetch order logs');
      }
      return { orderLogs: [], scheduledOrders: [] };
    },
    [apiUrl, orderedDate, selectedClientId],
  );

  const fetchTradebookHistory = useCallback(
    async (selectedClientId: string, fromDate: string, toDate: string) => {
      if (!selectedClientId) {
        return [];
      }
      const params = new URLSearchParams({
        client_id: selectedClientId,
        from_date: fromDate,
        to_date: toDate,
      });
      const response = await fetch(`${apiUrl}/tradebook_history?${params.toString()}`);
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || `Trade history request failed (${response.status})`);
      }
      const rows = await response.json();
      return Array.isArray(rows)
        ? rows.map((row) => ({ ...row, client_id: selectedClientId }))
        : [];
    },
    [apiUrl],
  );

  const persistTradeBookCache = useCallback((open: any[], daily: any[], clientIds: string[]) => {
    try {
      sessionStorage.setItem(
        TRADE_BOOK_CACHE_STORAGE_KEY,
        JSON.stringify({
          open,
          daily,
          clientKey: tradeBookClientKey(clientIds),
          fetchedAt: Date.now(),
        }),
      );
    } catch {
      // Ignore storage quota or private-mode errors.
    }
  }, []);

  const persistHistoryCache = useCallback((payload: { key: string; rows: any[] }) => {
    try {
      sessionStorage.setItem(
        HISTORY_CACHE_STORAGE_KEY,
        JSON.stringify({ ...payload, fetchedAt: Date.now() }),
      );
    } catch {
      // Ignore storage quota or private-mode errors.
    }
  }, []);

  const loadTradeBooks = useCallback(
    async (clientIds: string[], force = false) => {
      const clientKey = tradeBookClientKey(clientIds);
      const cached = tradeBookCacheRef.current;
      if (
        !force
        && tradeBookLoaded
        && cached?.clientKey === clientKey
        && isCacheFresh(cached.fetchedAt)
      ) {
        return { open: orderBook, daily: dailyOrderBook };
      }

      if (clientIds.length === 0) {
        setOrderBook([]);
        setDailyOrderBook([]);
        setTradeBookLoaded(true);
        tradeBookCacheRef.current = { clientKey, fetchedAt: Date.now() };
        persistTradeBookCache([], [], clientIds);
        return { open: [], daily: [] };
      }

      setIsTradeBookLoading(true);
      try {
        const pairs = await Promise.all(
          clientIds.map(async (id) => {
            const [open, daily] = await Promise.all([
              fetchOrderBook(id).catch(() => []),
              fetchDailyOrderBook(id).catch(() => []),
            ]);
            return { open, daily };
          }),
        );
        const open = pairs.flatMap((pair) => pair.open);
        const daily = pairs
          .flatMap((pair) => pair.daily)
          .sort((left, right) => {
            const leftTime = new Date(left.orderTime || 0).getTime();
            const rightTime = new Date(right.orderTime || 0).getTime();
            return rightTime - leftTime;
          });

        setOrderBook(open);
        setDailyOrderBook(daily);
        setTradeBookLoaded(true);
        tradeBookCacheRef.current = { clientKey, fetchedAt: Date.now() };
        persistTradeBookCache(open, daily, clientIds);
        return { open, daily };
      } finally {
        setIsTradeBookLoading(false);
      }
    },
    [
      dailyOrderBook,
      fetchDailyOrderBook,
      fetchOrderBook,
      orderBook,
      persistTradeBookCache,
      tradeBookLoaded,
    ],
  );

  const persistCoreCache = useCallback((payload: {
    orderLogs: any[];
    scheduledOrders: ScheduledOrderRow[];
  }) => {
    try {
      sessionStorage.setItem(
        CORE_CACHE_STORAGE_KEY,
        JSON.stringify({ ...payload, fetchedAt: Date.now() }),
      );
    } catch {
      // Ignore storage quota or private-mode errors.
    }
  }, []);

  useEffect(() => {
    try {
      const raw = sessionStorage.getItem(TRADE_BOOK_CACHE_STORAGE_KEY);
      if (!raw) {
        return;
      }
      const cached = JSON.parse(raw) as {
        fetchedAt?: number;
        clientKey?: string;
        open?: any[];
        daily?: any[];
      };
      if (!isCacheFresh(cached.fetchedAt)) {
        return;
      }
      setOrderBook(cached.open || []);
      setDailyOrderBook(cached.daily || []);
      tradeBookCacheRef.current = {
        clientKey: cached.clientKey || '',
        fetchedAt: cached.fetchedAt || Date.now(),
      };
      setTradeBookLoaded(true);
    } catch {
      // Ignore malformed cache payloads.
    }
  }, []);

  useEffect(() => {
    try {
      const raw = sessionStorage.getItem(HISTORY_CACHE_STORAGE_KEY);
      if (!raw) {
        return;
      }
      const cached = JSON.parse(raw) as {
        fetchedAt?: number;
        key?: string;
        rows?: any[];
      };
      if (!isCacheFresh(cached.fetchedAt) || !cached.key) {
        return;
      }
      historyCacheRef.current = {
        key: cached.key,
        rows: cached.rows || [],
        fetchedAt: cached.fetchedAt || Date.now(),
      };
      setOrderHistory(cached.rows || []);
      setHistoryLoaded(true);
    } catch {
      // Ignore malformed cache payloads.
    }
  }, []);

  useEffect(() => {
    try {
      const raw = sessionStorage.getItem(CORE_CACHE_STORAGE_KEY);
      if (!raw) {
        return;
      }
      const cached = JSON.parse(raw) as {
        fetchedAt?: number;
        orderLogs?: any[];
        scheduledOrders?: ScheduledOrderRow[];
      };
      if (!isCacheFresh(cached.fetchedAt)) {
        return;
      }
      setOrderLogs(cached.orderLogs || []);
      setScheduledOrders(cached.scheduledOrders || []);
      coreCacheRef.current = cached.fetchedAt || Date.now();
      setHasLoaded(true);
      setIsLoading(false);
    } catch {
      // Ignore malformed cache payloads.
    }
  }, []);

  const loadCoreData = useCallback(
    async (force = false) => {
      if (!force && isCacheFresh(coreCacheRef.current) && hasLoaded) {
        setIsLoading(false);
        return;
      }

      const hasVisibleData = orderLogs.length > 0 || scheduledOrders.length > 0;
      const showBlockingLoader = !hasLoaded && !hasVisibleData;
      if (showBlockingLoader) {
        setIsLoading(true);
      }

      try {
        const logsResult = await Promise.allSettled([
          fetchOrderStatusLogs({ silent: true }),
        ]).then((results) => results[0]);

        const nextOrderLogs = logsResult.status === 'fulfilled'
          ? logsResult.value.orderLogs
          : orderLogs;
        const nextScheduledOrders = logsResult.status === 'fulfilled'
          ? logsResult.value.scheduledOrders
          : scheduledOrders;

        if (logsResult.status === 'rejected' && !hasVisibleData) {
          throw logsResult.reason;
        }

        coreCacheRef.current = Date.now();
        setHasLoaded(true);
        persistCoreCache({
          orderLogs: nextOrderLogs,
          scheduledOrders: nextScheduledOrders,
        });
      } catch {
        if (!hasLoaded && !hasVisibleData) {
          setErrorMessage('Failed to load order data.');
        } else {
          setErrorMessage('Failed to refresh order data.');
        }
        throw new Error('core load failed');
      } finally {
        if (showBlockingLoader) {
          setIsLoading(false);
        }
      }
    },
    [
      fetchOrderStatusLogs,
      hasLoaded,
      orderLogs,
      persistCoreCache,
      scheduledOrders,
    ],
  );

  const loadHistoryData = useCallback(
    async (force = false, presetOverride?: HistoryRangePreset) => {
      const preset = presetOverride ?? historyRangePreset;
      const cacheKey = buildHistoryCacheKey(activeClientIds, preset);
      const cached = historyCacheRef.current;

      if (!force && cached?.key === cacheKey && isCacheFresh(cached.fetchedAt)) {
        setOrderHistory(cached.rows);
        setHistoryLoaded(true);
        return;
      }

      if (activeClientIds.length === 0) {
        setOrderHistory([]);
        setHistoryLoaded(true);
        return;
      }

      const requestId = ++historyRequestIdRef.current;
      setIsHistoryLoading(true);
      const { fromDate, toDate } = resolveHistoryDateRange(
        preset,
        historyFromDate,
        historyToDate,
      );

      try {
        const historyResults = await Promise.all(
          activeClientIds.map((id) => fetchTradebookHistory(id, fromDate, toDate)),
        );
        if (requestId !== historyRequestIdRef.current) {
          return;
        }
        const rows = historyResults.flat().sort((left, right) => {
          const leftTime = new Date(left.tradeTime || 0).getTime();
          const rightTime = new Date(right.tradeTime || 0).getTime();
          return rightTime - leftTime;
        });
        historyCacheRef.current = { key: cacheKey, rows, fetchedAt: Date.now() };
        setOrderHistory(rows);
        setHistoryLoaded(true);
        persistHistoryCache({ key: cacheKey, rows });
      } catch {
        if (requestId !== historyRequestIdRef.current) {
          return;
        }
        setErrorMessage('Failed to load trade history.');
      } finally {
        if (requestId === historyRequestIdRef.current) {
          setIsHistoryLoading(false);
        }
      }
    },
    [
      activeClientIds,
      buildHistoryCacheKey,
      fetchTradebookHistory,
      historyFromDate,
      historyRangePreset,
      historyToDate,
      persistHistoryCache,
    ],
  );

  useEffect(() => {
    if (!clientsFetched) {
      return;
    }
    void loadCoreData(false);
    void loadTradeBooks(activeClientIds, false);
    if (historyRangePreset !== 'custom') {
      void loadHistoryData(false);
    }
  }, [
    activeClientIds,
    clientsFetched,
    historyRangePreset,
    loadCoreData,
    loadHistoryData,
    loadTradeBooks,
  ]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      void loadCoreData(true);
      void loadTradeBooks(activeClientIds, true);
      if (historyRangePreset !== 'custom') {
        void loadHistoryData(true);
      }
    }, CACHE_TTL_MS);
    return () => window.clearInterval(interval);
  }, [activeClientIds, historyRangePreset, loadCoreData, loadHistoryData, loadTradeBooks]);

  const handleRefresh = async (e?: React.FormEvent) => {
    e?.preventDefault();
    setErrorMessage('');
    setSuccessMessage('');
    setIsRefreshing(true);
    coreCacheRef.current = null;
    historyCacheRef.current = null;
    tradeBookCacheRef.current = null;
    try {
      sessionStorage.removeItem(CORE_CACHE_STORAGE_KEY);
      sessionStorage.removeItem(TRADE_BOOK_CACHE_STORAGE_KEY);
      sessionStorage.removeItem(HISTORY_CACHE_STORAGE_KEY);
    } catch {
      // Ignore storage errors.
    }

    try {
      await loadCoreData(true);
      await loadTradeBooks(activeClientIds, true);
      if (historyRangePreset !== 'custom') {
        await loadHistoryData(true);
      }
      setSuccessMessage('Data refreshed');
    } catch {
      setErrorMessage('Failed to refresh order data.');
    } finally {
      setIsRefreshing(false);
    }
  };

  const handleTabChange = (tab: OrderTab) => {
    setActiveTab(tab);
  };

  const handleHistoryPresetChange = (preset: HistoryRangePreset) => {
    historyCacheRef.current = null;
    historyRequestIdRef.current += 1;
    try {
      sessionStorage.removeItem(HISTORY_CACHE_STORAGE_KEY);
    } catch {
      // Ignore storage errors.
    }
    setHistoryRangePreset(preset);
    const today = todayNepalDate();
    if (preset === 'week') {
      setHistoryFromDate(offsetNepalDate(today, { days: 7 }));
      setHistoryToDate(today);
    } else if (preset === 'month') {
      setHistoryFromDate(offsetNepalDate(today, { months: 1 }));
      setHistoryToDate(today);
    } else if (preset === 'forever') {
      setHistoryFromDate(FOREVER_FROM_DATE);
      setHistoryToDate(today);
    }
    if (preset !== 'custom') {
      void loadHistoryData(true, preset);
    }
  };

  const handleHistoryRangeApply = () => {
    historyCacheRef.current = null;
    historyRequestIdRef.current += 1;
    try {
      sessionStorage.removeItem(HISTORY_CACHE_STORAGE_KEY);
    } catch {
      // Ignore storage errors.
    }
    void loadHistoryData(true);
  };

  const handleCancelOrder = async (clientId: string, exchangeSecurityID: number) => {
    if (!clientId) {
      setErrorMessage('Cannot cancel order because client ID is missing.');
      return;
    }
    try {
      const response = await fetch(
        `${apiUrl}/cancel_order/?client_id=${clientId}&exchange_order_id=${exchangeSecurityID}`,
        { method: 'DELETE' },
      );
      if (response.ok) {
        setSuccessMessage('Order cancelled successfully');
        tradeBookCacheRef.current = null;
        await loadTradeBooks(activeClientIds, true);
      } else {
        setErrorMessage('Failed to cancel order');
      }
    } catch {
      setErrorMessage('Error cancelling order');
    }
  };

  const handleAction = async (row: any, actionType: string) => {
    if (actionType === 'Edit') {
      setEditingOrderId(Number(row.order_id));
      return;
    }
    if (actionType === 'Delete') {
      setDialogMessage('Are you sure you want to delete this scheduled order?');
      setDialogAction(() => async () => {
        try {
          const response = await fetch(`${apiUrl}/delete_scheduled_order/?order_id=${row.order_id}`, {
            method: 'DELETE',
          });
          if (response.ok) {
            setScheduledOrders((prev) => prev.filter((order) => order.order_id !== row.order_id));
            setSuccessMessage('Scheduled order deleted');
          } else {
            setErrorMessage('Failed to delete scheduled order');
          }
        } catch {
          setErrorMessage('Error deleting scheduled order');
        } finally {
          setDialogVisible(false);
        }
      });
      setDialogVisible(true);
    } else if (actionType === 'Cancel') {
      setDialogMessage('Are you sure you want to cancel this order?');
      setDialogAction(() => () => {
        handleCancelOrder(row.client_id, row.exchangeOrderId);
        setDialogVisible(false);
      });
      setDialogVisible(true);
    }
  };

  const scheduledRows = useMemo(
    () =>
      scheduledOrders.map((order) => {
        const side = getOrderSide(order);
        const strategyLabel = formatStrategyType(order.strategy_type, side);
        return {
          ...order,
          canEdit: isScheduledOrderEditable(order),
          stock: <StockClientCell symbol={order.script_name} clientLabel={getClientLabel(order.client_id)} />,
          order_type: side,
          strategy_type: (
            <button
              type="button"
              className={`strategy-chip ${side === 'BUY' ? 'buy' : side === 'SELL' ? 'sell' : ''}`}
              onClick={() => setStrategyDetailsOrder(order)}
              title="Show details"
              aria-label={`Show details for ${strategyLabel}`}
            >
              <span className="strategy-chip-label">{strategyLabel}</span>
              <span className="strategy-chip-action">Show details</span>
            </button>
          ),
          created_at: formatDateTime(order.created_at || order.target_reached_at || ''),
          qty: formatScanCount(order.qty),
          status: formatLiveScanStatus(order),
        };
      }),
    [getClientLabel, scheduledOrders],
  );

  const orderLogRows = useMemo(
    () =>
      [...orderLogs]
        .sort((left, right) => {
          const leftCompleted = isCompletedStatus(left.status);
          const rightCompleted = isCompletedStatus(right.status);
          if (leftCompleted !== rightCompleted) {
            return leftCompleted ? -1 : 1;
          }
          return orderTimestamp(right) - orderTimestamp(left);
        })
        .map((order) => {
          const side = getOrderSide(order);
          const strategyLabel = formatStrategyType(order.strategy_type, side);
          const detailOrder: ScheduledOrderRow = {
            order_id: order.order_id || 0,
            client_id: order.client_id || '',
            script_name: order.script_name || '',
            price: Number(order.requested_price ?? order.price ?? 0),
            qty: Number(order.qty || 0),
            status: order.status || '',
            order_type: String(order.order_type || side).toLowerCase(),
            strategy_type: order.strategy_type || strategyLabel,
            side,
            created_at: order.timestamp,
            requested_price: order.requested_price ?? order.price,
            stop_loss_price: order.stop_loss_price,
            average_buy_price: order.average_buy_price,
            highest_tracked_price: order.highest_tracked_price,
            trailing_drop_percent: order.trailing_drop_percent,
            max_allowed_slippage_percent: order.max_allowed_slippage_percent,
            execution_price: order.execution_price ?? order.price,
            execution_price_source: order.execution_price_source,
            execution_reason: order.execution_reason || order.status,
          };
          return {
            timestamp: formatDateTime(order.timestamp),
            stock: <StockClientCell symbol={order.script_name} clientLabel={getClientLabel(order.client_id || '')} />,
            order_type: side,
            qty: formatScanCount(order.qty),
            strategy_type: (
              <button
                type="button"
                className={`strategy-chip ${side === 'BUY' ? 'buy' : side === 'SELL' ? 'sell' : ''}`}
                onClick={() => setStrategyDetailsOrder(detailOrder)}
                title="Show details"
                aria-label={`Show details for ${strategyLabel}`}
              >
                <span className="strategy-chip-label">{strategyLabel}</span>
                <span className="strategy-chip-action">Show details</span>
              </button>
            ),
            status: order.status,
            price: formatCurrency(order.execution_price ?? order.price),
          };
        }),
    [getClientLabel, orderLogs],
  );

  const decorateTmsRows = useCallback(
    (rows: any[]) =>
      rows.map((row) => {
        const symbol =
          row.symbol ||
          row.script_name ||
          row.securitySymbol ||
          row.security?.symbol ||
          '';
        const clientId = row.client_id || '';
        return {
          ...row,
          stock: <StockClientCell symbol={symbol} clientLabel={getClientLabel(clientId)} />,
        };
      }),
    [getClientLabel],
  );

  const historyDateRangeLabel = useMemo(
    () => historyRangeLabel(historyRangePreset, historyFromDate, historyToDate),
    [historyFromDate, historyRangePreset, historyToDate],
  );

  const formatTradeBookRows = useCallback(
    (rows: any[]) =>
      decorateTmsRows(rows).map((row) => ({
        ...row,
        buyOrSell: formatTradeSide(row.buyOrSell),
        orderPrice: formatCurrency(row.orderPrice),
        activeStatus: row.displayActiveStatus || row.activeStatus || '-',
      })),
    [decorateTmsRows],
  );

  const openTradeRows = useMemo(() => formatTradeBookRows(orderBook), [formatTradeBookRows, orderBook]);
  const dailyTradeRows = useMemo(() => formatTradeBookRows(dailyOrderBook), [dailyOrderBook, formatTradeBookRows]);

  const tradeBookCount = orderBook.length + dailyOrderBook.length;

  const orderHistoryRows = useMemo(
    () =>
      orderHistory.map((row) => {
        const symbol = row.symbol || row.script_name || '';
        const clientId = row.client_id || '';
        return {
          tradeTime: row.tradeTime || '-',
          stock: <StockClientCell symbol={symbol} clientLabel={getClientLabel(clientId)} />,
          buyOrSell: formatTradeSide(row.buyOrSell),
          tradePrice: formatTradeAmount(row.tradePrice),
          tradedQuantity: row.tradedQuantity ?? '-',
          exchangeOrderId: row.exchangeOrderId || '-',
          exchangeTradeId: row.exchangeTradeId || '',
        };
      }),
    [getClientLabel, orderHistory],
  );

  const tabData: Record<OrderTab, { count: number; columns: string[]; rows: any[]; empty: string }> = {
    logs: {
      count: orderLogs.length,
      columns: getVisibleColumns(
        orderLogRows,
        ['timestamp', 'stock', 'order_type', 'qty', 'strategy_type', 'status'],
        ['price'],
      ),
      rows: orderLogRows,
      empty: hasLoaded
        ? 'No order logs found for today.'
        : 'Loading order logs...',
    },
    scheduled: {
      count: scheduledOrders.length,
      columns: ['stock', 'order_type', 'qty', 'strategy_type', 'status', 'created_at'],
      rows: scheduledRows,
      empty: hasLoaded
        ? 'No scheduled orders found.'
        : 'Loading scheduled orders...',
    },
    book: {
      count: tradeBookCount,
      columns: OPEN_TRADE_COLUMNS,
      rows: openTradeRows,
      empty: tradeBookLoaded
        ? 'No open or daily orders found for the selected client(s).'
        : 'Loading trade book from TMS...',
    },
    history: {
      count: orderHistory.length,
      columns: getVisibleColumns(
        orderHistoryRows,
        ['tradeTime', 'stock', 'buyOrSell', 'tradePrice', 'tradedQuantity', 'exchangeOrderId'],
        ['exchangeTradeId', 'displayName', 'clientMemberCode'],
      ),
      rows: orderHistoryRows,
      empty: isHistoryLoading || !historyLoaded
        ? 'Loading trade history...'
        : 'No trade history found for the selected date range.',
    },
  };

  const current = tabData[activeTab];

  return (
    <div className="order-logs-page">
      <div className="order-logs-filters panel">
        <div className="order-logs-filters-header">
          <div>
            <h2 className="panel-title">Order Logs</h2>
            <p className="panel-subtitle">
              All sections load on open and stay cached in your browser for 20 minutes. Use Refresh to fetch now.
            </p>
          </div>
          <div className="order-logs-header-actions">
            {loggedInClientIDs.length > 0 && (
              <span className="badge badge-success">{loggedInClientIDs.length} client(s) online</span>
            )}
            <button
              type="button"
              className={`order-logs-refresh-btn ${isRefreshing ? 'spinning' : ''}`}
              onClick={() => void handleRefresh()}
              disabled={isRefreshing}
              aria-label="Refresh order data"
              title="Refresh all sections"
            >
              <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path
                  d="M21 12a9 9 0 1 1-2.64-6.36"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                />
                <path
                  d="M21 3v6h-6"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </button>
          </div>
        </div>

        {successMessage && <ErrorMessage message={successMessage} variant="success" />}
        {errorMessage && <ErrorMessage message={errorMessage} variant="error" />}

        <form onSubmit={handleRefresh} className="order-logs-form">
          <div className="order-logs-form-grid">
            <div className="form-group">
              <label htmlFor="clientFilter">Client</label>
              <select
                id="clientFilter"
                className="select"
                value={selectedClientId}
                onChange={(e) => setSelectedClientId(e.target.value)}
              >
                <option value="">All clients</option>
                {clientSessions.map((session) => (
                  <option key={session.client_id} value={session.client_id}>
                    {formatClientLabel(session, session.client_id)}
                  </option>
                ))}
              </select>
            </div>

            <div className="form-group">
              <label htmlFor="scriptName">Script Name</label>
              <input
                id="scriptName"
                type="text"
                className="input"
                value={scriptName}
                onChange={(e) => setScriptName(e.target.value)}
                placeholder="Optional — filter by symbol"
              />
            </div>

            <div className="form-group">
              <label htmlFor="orderedDate">Ordered Date</label>
              <DatePicker
                id="orderedDate"
                selected={dateFromNepalDateString(orderedDate)}
                onChange={handleDateChange}
                dateFormat="yyyy-MM-dd"
                placeholderText="Select a date"
                className="input order-logs-datepicker"
                wrapperClassName="order-logs-datepicker-wrap"
                isClearable
              />
            </div>
          </div>
        </form>
      </div>

      <div className="order-logs-stats">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={`order-logs-stat-card ${activeTab === tab.id ? 'active' : ''}`}
            onClick={() => handleTabChange(tab.id)}
          >
            <span className="order-logs-stat-icon">{tab.icon}</span>
            <div>
              <span className="order-logs-stat-label">{tab.label}</span>
              <span className="order-logs-stat-value">{tabData[tab.id].count}</span>
            </div>
          </button>
        ))}
      </div>

      <div className="order-logs-content panel">
        <div className="order-logs-content-header">
          <h3 className="order-logs-section-title">
            {TABS.find((t) => t.id === activeTab)?.icon}{' '}
            {TABS.find((t) => t.id === activeTab)?.label}
            {activeTab === 'history' && (
              <span className="order-logs-section-range">{historyDateRangeLabel}</span>
            )}
          </h3>
          <span className="badge badge-muted">{current.count} record(s)</span>
        </div>

        {activeTab === 'history' && (
          <div className="order-logs-history-toolbar">
            <div className="order-logs-history-toolbar-head">
              <span className="order-logs-history-label">Date range</span>
              <span className="order-logs-history-range-badge">{historyDateRangeLabel}</span>
            </div>
            <div className="order-logs-history-presets">
              {HISTORY_RANGE_OPTIONS.map((option) => (
                <button
                  key={option.id}
                  type="button"
                  className={`order-logs-preset-btn ${historyRangePreset === option.id ? 'active' : ''}`}
                  onClick={() => handleHistoryPresetChange(option.id)}
                >
                  {option.label}
                </button>
              ))}
            </div>
            {historyRangePreset === 'custom' && (
              <div className="order-logs-history-custom">
                <div className="form-group">
                  <label htmlFor="historyFromDate">From</label>
                  <DatePicker
                    id="historyFromDate"
                    selected={dateFromNepalDateString(historyFromDate)}
                    onChange={(date) => setHistoryFromDate(nepalDateStringFromDate(date))}
                    dateFormat="yyyy-MM-dd"
                    maxDate={dateFromNepalDateString(historyToDate) || undefined}
                    className="input order-logs-datepicker"
                    wrapperClassName="order-logs-datepicker-wrap"
                  />
                </div>
                <div className="form-group">
                  <label htmlFor="historyToDate">To</label>
                  <DatePicker
                    id="historyToDate"
                    selected={dateFromNepalDateString(historyToDate)}
                    onChange={(date) => setHistoryToDate(nepalDateStringFromDate(date))}
                    dateFormat="yyyy-MM-dd"
                    minDate={dateFromNepalDateString(historyFromDate) || undefined}
                    maxDate={dateFromNepalDateString(todayNepalDate()) || undefined}
                    className="input order-logs-datepicker"
                    wrapperClassName="order-logs-datepicker-wrap"
                  />
                </div>
              </div>
            )}
            <div className="order-logs-history-toolbar-actions">
              <p className="order-logs-history-hint">
                Cached for 20 minutes. Use Apply or the refresh icon to fetch now.
              </p>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={handleHistoryRangeApply}
                disabled={isHistoryLoading}
              >
                {isHistoryLoading ? 'Loading...' : 'Apply range'}
              </button>
            </div>
          </div>
        )}

        {(isLoading && !hasLoaded && orderLogs.length === 0 && scheduledOrders.length === 0)
          || (activeTab === 'history' && isHistoryLoading && !historyLoaded && orderHistory.length === 0)
          || (activeTab === 'book' && isTradeBookLoading && !tradeBookLoaded && openTradeRows.length === 0 && dailyTradeRows.length === 0) ? (
          <div className="order-logs-loading">
            <div className="order-logs-spinner" />
            <p>Fetching order data from TMS...</p>
          </div>
        ) : activeTab === 'book' ? (
          <div className="order-logs-trade-book">
            <section className="order-logs-trade-section">
              <div className="order-logs-trade-section-header">
                <h4>Open Trades</h4>
                <span className="badge badge-muted">{openTradeRows.length} record(s)</span>
              </div>
              <CommonTable
                data={openTradeRows}
                onAction={handleAction}
                columns={OPEN_TRADE_COLUMNS}
                emptyMessage={tradeBookLoaded ? 'No open orders.' : 'Loading open trades...'}
              />
            </section>
            <section className="order-logs-trade-section">
              <div className="order-logs-trade-section-header">
                <h4>Daily Order Book</h4>
                <span className="badge badge-muted">{dailyTradeRows.length} record(s)</span>
              </div>
              <CommonTable
                data={dailyTradeRows}
                columns={DAILY_TRADE_COLUMNS}
                emptyMessage={tradeBookLoaded ? 'No completed, cancelled, or rejected orders today.' : 'Loading daily orders...'}
              />
            </section>
          </div>
        ) : (
          <CommonTable
            data={current.rows}
            onAction={activeTab === 'scheduled' ? handleAction : undefined}
            columns={current.columns}
            emptyMessage={current.empty}
          />
        )}
      </div>

      {dialogVisible && (
        <DialogBox
          message={dialogMessage}
          onConfirm={dialogAction}
          onCancel={() => setDialogVisible(false)}
        />
      )}

      {strategyDetailsOrder && (
        <div className="strategy-details-backdrop" role="presentation" onClick={() => setStrategyDetailsOrder(null)}>
          <div className="strategy-details-modal" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
            <div className="strategy-details-header">
              <div>
                <h3>Strategy Details</h3>
                <p>
                  <NepseAlphaSymbolLink symbol={strategyDetailsOrder.script_name} />
                </p>
              </div>
              <button type="button" className="strategy-details-close" onClick={() => setStrategyDetailsOrder(null)} aria-label="Close strategy details">
                ×
              </button>
            </div>
            <dl className="strategy-details-list">
              {getStrategyDetails(strategyDetailsOrder).map((item) => (
                <div key={item.label} className="strategy-details-row">
                  <dt>{item.label}</dt>
                  <dd>{item.value}</dd>
                </div>
              ))}
            </dl>
            <div className="strategy-details-footer">
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => {
                  const side = getOrderSide(strategyDetailsOrder) === 'BUY' ? 'buy' : 'sell';
                  setStrategyCatalogGuide({
                    name: strategyDetailsOrder.strategy_type || formatStrategyLabel(strategyDetailsOrder.strategy_type || '', side),
                    side,
                  });
                }}
              >
                Strategy behaviour guide
              </button>
            </div>
          </div>
        </div>
      )}

      {strategyCatalogGuide && (
        <StrategyCatalogModal
          strategyName={strategyCatalogGuide.name}
          side={strategyCatalogGuide.side}
          onClose={() => setStrategyCatalogGuide(null)}
        />
      )}

      {editingOrderId != null && (
        <EditScheduledOrderModal
          orderId={editingOrderId}
          apiUrl={apiUrl}
          onClose={() => setEditingOrderId(null)}
          onSaved={() => {
            setSuccessMessage('Scheduled order updated');
            coreCacheRef.current = null;
            void loadCoreData(true);
          }}
        />
      )}
    </div>
  );
};

export default GetOrderStatus;
