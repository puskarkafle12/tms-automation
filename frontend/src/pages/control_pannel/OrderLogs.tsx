import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import './OrderLogs.css';
import CommonTable from '../../components/table/Table';
import DialogBox from '../../components/dialog_box/DialogBox';
import ErrorMessage from '../../components/ErrorMessage';
import 'react-datepicker/dist/react-datepicker.css';
import DatePicker from 'react-datepicker';
import { syncMonitoringStatus } from '../../hooks/monitoringSync';
import {
  apiTimestampToUtcMs,
  dateFromNepalDateString,
  formatNepalDateTime,
  nepalDateStringFromDate,
  offsetNepalDate,
  setServerTodayNpt,
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
import {
  REFRESH_SCHEDULED_ORDERS_KEY,
  SCHEDULED_ORDERS_CHANGED_EVENT,
  deleteScheduledOrdersById,
  deleteScheduledBatchById,
  notifyScheduledOrdersChanged,
  resolveScheduledOrderIdsForBulkDelete,
  type ScheduledBulkDeleteMode,
} from './scheduleOrderHelpers';
import { formatOrderQuantityDisplay, getDisplayQtyForOrder } from '../../lib/strategies/rulePlanHelpers';
import { buildStrategyDetailLayout } from '../../lib/strategies/orderStrategyDetails';
import {
  formatScheduledQuantitySummary,
  formatScheduledTriggerPrice,
} from '../../lib/strategies/scheduledOrderDisplay';
import {
  groupScheduledOrdersByBatch,
  type ScheduledBatchGroup,
} from '../../lib/strategies/scheduledBatchGroups';
import { fetchServerTime, serverUtcToMs } from '../../api/time.api';
import type { ApiTimeValue } from '../../utils/nepalTime';
import {
  readUiPortalSettings,
  subscribeUiPortalSettings,
} from '../../lib/uiPortalSettings';
import {
  fetchPortalSettings,
  savePortalSettings,
  type PortalSettings,
  type PortalSettingsLimits,
} from '../../api/settings.api';

type OrderTab = 'logs' | 'scheduled' | 'book' | 'history';
type ScanIntervalUnit = 'seconds' | 'minutes' | 'hours';

const CORE_CACHE_STORAGE_KEY = 'tms-order-logs-core-v1';
const TRADE_BOOK_CACHE_STORAGE_KEY = 'tms-order-logs-trade-book-v1';
const HISTORY_CACHE_STORAGE_KEY = 'tms-order-logs-history-v1';

const HISTORY_RANGE_OPTIONS: { id: HistoryRangePreset; label: string }[] = [
  { id: 'week', label: '1 Week' },
  { id: 'month', label: '1 Month' },
  { id: 'custom', label: 'Custom' },
  { id: 'forever', label: 'All Time' },
];

const SCAN_INTERVAL_UNITS: Array<{ value: ScanIntervalUnit; label: string; multiplier: number }> = [
  { value: 'seconds', label: 'Seconds', multiplier: 1 },
  { value: 'minutes', label: 'Minutes', multiplier: 60 },
  { value: 'hours', label: 'Hours', multiplier: 3600 },
];

interface ScheduledOrderRow {
  order_id: number;
  client_id: string;
  script_name: string;
  price: number;
  qty: number;
  status: string;
  order_type: string;
  created_at?: ApiTimeValue;
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
  reference_ltp?: number | null;
  trigger_price?: number | null;
  reference_ltp_captured_at?: string | null;
  drop_percent?: number | null;
  max_allowed_slippage_percent?: number | null;
  scanning_count?: number;
  tms_scan_count?: number;
  nepse_alpha_scan_count?: number;
  nepse_alpha_last_source?: string | null;
  nepse_alpha_last_fetched_at?: number | string | null;
  current_price?: number | null;
  last_checked_ltp?: number | null;
  last_scan_at?: ApiTimeValue;
  failed_reason?: string | null;
  cancelled_reason?: string | null;
  live_status?: string;
  is_scanning?: boolean;
  display_error?: string | null;
  last_monitor_message?: string | null;
  monitor_logs?: string | null;
  monitor_phase?: string;
  monitoring_active?: boolean;
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

const formatScanCount = (value: number | null | undefined): string => {
  return String(Math.max(0, Math.round(Number(value) || 0)));
};

const formatLiveScanStatus = (order: ScheduledOrderRow): string => {
  if (order.is_scanning) {
    return 'scanning';
  }
  if (order.display_error) {
    return order.display_error;
  }
  if (order.live_status) {
    return order.live_status;
  }
  return order.status || 'pending';
};

const ScheduledOrderStatusCell: React.FC<{ order: ScheduledOrderRow }> = ({ order }) => {
  if (order.is_scanning) {
    const count = order.tms_scan_count ?? order.scanning_count ?? 0;
    return (
      <span className="scheduled-order-status scanning" title="Actively scanning">
        <span className="scheduled-order-status-dot" aria-hidden="true" />
        <span className="scheduled-order-status-count">{formatScanCount(count)}</span>
      </span>
    );
  }

  if (order.display_error) {
    return (
      <span className="scheduled-order-status error" title={order.display_error}>
        {order.display_error}
      </span>
    );
  }

  const fallback = order.live_status || order.status || 'pending';
  return (
    <span className="scheduled-order-status idle" title={fallback}>
      {fallback}
    </span>
  );
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

const formatDateTime = (value: ApiTimeValue) => formatNepalDateTime(value);

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

const isCacheFresh = (fetchedAt: number | null | undefined, ttlMs: number) =>
  fetchedAt != null && Date.now() - fetchedAt < ttlMs;

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

const TABS: { id: OrderTab; label: string; icon: string }[] = [
  { id: 'scheduled', label: 'Scheduled', icon: '📅' },
  { id: 'book', label: 'Trade Book', icon: '📖' },
  { id: 'logs', label: 'Order Logs', icon: '📋' },
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
  const timestamp = apiTimestampToUtcMs(order?.timestamp ?? order?.created_at ?? null);
  return timestamp ?? 0;
};

const isCompletedStatus = (status: unknown) => {
  const normalized = String(status || '').trim().toLowerCase();
  return COMPLETED_STATUS_RANK.has(normalized);
};

const getScanUnitConfig = (unit: ScanIntervalUnit) =>
  SCAN_INTERVAL_UNITS.find((item) => item.value === unit) || SCAN_INTERVAL_UNITS[0];

const splitScanInterval = (seconds: number): { value: number; unit: ScanIntervalUnit } => {
  if (seconds >= 3600 && seconds % 3600 === 0) {
    return { value: seconds / 3600, unit: 'hours' };
  }
  if (seconds >= 60 && seconds % 60 === 0) {
    return { value: seconds / 60, unit: 'minutes' };
  }
  return { value: seconds, unit: 'seconds' };
};

const GetOrderStatus: React.FC = () => {
  const [orderedDate, setOrderedDate] = useState<string>('');
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
  const [isClearingLogs, setIsClearingLogs] = useState(false);
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
  const [uiPortalSettings, setUiPortalSettings] = useState(readUiPortalSettings);
  const liveRefreshMs = uiPortalSettings.orderLogsLiveRefreshSeconds * 1000;
  const backgroundCacheTtlMs = uiPortalSettings.orderLogsBackgroundRefreshMinutes * 60 * 1000;
  useEffect(() => subscribeUiPortalSettings(setUiPortalSettings), []);
  const [dialogVisible, setDialogVisible] = useState(false);
  const [dialogMessage, setDialogMessage] = useState('');
  const [dialogAction, setDialogAction] = useState<() => void>(() => {});
  const [selectedScheduledIds, setSelectedScheduledIds] = useState<Set<number>>(new Set());
  const [isBulkDeleting, setIsBulkDeleting] = useState(false);
  const [isBulkCancellingTrades, setIsBulkCancellingTrades] = useState(false);
  const [strategyDetailsOrderId, setStrategyDetailsOrderId] = useState<number | null>(null);
  const [strategyDetailsExpanded, setStrategyDetailsExpanded] = useState(false);
  const [strategyDetailsFallback, setStrategyDetailsFallback] = useState<ScheduledOrderRow | null>(null);
  const [strategyDetailsNow, setStrategyDetailsNow] = useState<number | null>(null);
  const [strategyCatalogGuide, setStrategyCatalogGuide] = useState<{ name: string; side: 'buy' | 'sell' } | null>(null);
  const [editingOrderId, setEditingOrderId] = useState<number | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [serverSettings, setServerSettings] = useState<PortalSettings | null>(null);
  const [settingsLimits, setSettingsLimits] = useState<PortalSettingsLimits | null>(null);
  const [scanIntervalValue, setScanIntervalValue] = useState(5);
  const [scanIntervalUnit, setScanIntervalUnit] = useState<ScanIntervalUnit>('seconds');
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [settingsLoading, setSettingsLoading] = useState(false);
  const [settingsError, setSettingsError] = useState('');
  const [errorMessage, setErrorMessage] = useState('');
  const [successMessage, setSuccessMessage] = useState('');
  const [clientsFetched, setClientsFetched] = useState(false);
  const apiUrl = localStorage.getItem('apiUrl') || window.location.origin;

  const loadServerSettings = useCallback(async () => {
    setSettingsLoading(true);
    setSettingsError('');
    try {
      const response = await fetchPortalSettings();
      const split = splitScanInterval(response.settings.monitor_interval_seconds);
      setServerSettings(response.settings);
      setSettingsLimits(response.limits);
      setScanIntervalValue(split.value);
      setScanIntervalUnit(split.unit);
    } catch {
      setSettingsError('Could not load schedule settings.');
    } finally {
      setSettingsLoading(false);
    }
  }, []);

  const openSettings = () => {
    setSettingsOpen(true);
    void loadServerSettings();
  };

  const saveScheduleSettings = async () => {
    const unit = getScanUnitConfig(scanIntervalUnit);
    const rawSeconds = Math.round(Number(scanIntervalValue || 0) * unit.multiplier);
    const limits = settingsLimits?.monitor_interval_seconds || { min: 3, max: 300 };
    const nextSeconds = Math.max(limits.min, Math.min(limits.max, rawSeconds));
    setSettingsSaving(true);
    setSettingsError('');
    try {
      const response = await savePortalSettings({
        ...(serverSettings || {}),
        monitor_interval_seconds: nextSeconds,
      });
      const split = splitScanInterval(response.settings.monitor_interval_seconds);
      setServerSettings(response.settings);
      setSettingsLimits(response.limits);
      setScanIntervalValue(split.value);
      setScanIntervalUnit(split.unit);
      setSettingsOpen(false);
      setSuccessMessage('Schedule settings saved');
    } catch {
      setSettingsError('Failed to save schedule settings.');
    } finally {
      setSettingsSaving(false);
    }
  };

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

  const openStrategyDetails = useCallback((order: ScheduledOrderRow) => {
    setStrategyDetailsOrderId(order.order_id);
    setStrategyDetailsFallback(order);
    setStrategyDetailsNow(Date.now());
    setStrategyDetailsExpanded(false);
  }, []);

  const closeStrategyDetails = useCallback(() => {
    setStrategyDetailsOrderId(null);
    setStrategyDetailsFallback(null);
    setStrategyDetailsExpanded(false);
  }, []);

  const strategyDetailsOrder = useMemo(() => {
    if (strategyDetailsOrderId == null) {
      return null;
    }
    return scheduledOrders.find((order) => order.order_id === strategyDetailsOrderId)
      ?? strategyDetailsFallback;
  }, [scheduledOrders, strategyDetailsFallback, strategyDetailsOrderId]);

  const strategyDetailLayout = useMemo(() => {
    if (!strategyDetailsOrder) {
      return null;
    }
    return buildStrategyDetailLayout(strategyDetailsOrder, {
      formatStrategyType,
      getOrderSide: (order) => getOrderSide(order as ScheduledOrderRow),
      formatCurrency,
      formatDateTime: (value) => formatDateTime(value as ApiTimeValue),
      formatPercent,
      formatLiveScanStatus: (order) => formatLiveScanStatus(order as ScheduledOrderRow),
      formatScanCount,
      now: strategyDetailsNow,
    });
  }, [strategyDetailsNow, strategyDetailsOrder]);

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
        if (data.server_time) {
          setServerTodayNpt(data.server_time.date || data.server_time.today_npt || '');
          const utcMs = serverUtcToMs(data.server_time);
          if (utcMs != null) {
            setStrategyDetailsNow(utcMs);
          }
        }
        const nextOrderLogs = data.order_logs || [];
        const monitorPhase = data.monitor_phase;
        const monitoringActive = data.monitoring_active;
        const nextScheduledOrders = (data.scheduled_orders || []).map((order: ScheduledOrderRow) => ({
          ...order,
          monitor_phase: monitorPhase,
          monitoring_active: monitoringActive,
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
        && isCacheFresh(cached.fetchedAt, backgroundCacheTtlMs)
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
      backgroundCacheTtlMs,
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
      if (!isCacheFresh(cached.fetchedAt, backgroundCacheTtlMs)) {
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
      if (!isCacheFresh(cached.fetchedAt, backgroundCacheTtlMs) || !cached.key) {
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
      if (!isCacheFresh(cached.fetchedAt, backgroundCacheTtlMs)) {
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
      if (!force && isCacheFresh(coreCacheRef.current, backgroundCacheTtlMs) && hasLoaded) {
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
      backgroundCacheTtlMs,
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

      if (!force && cached?.key === cacheKey && isCacheFresh(cached.fetchedAt, backgroundCacheTtlMs)) {
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
      backgroundCacheTtlMs,
      buildHistoryCacheKey,
      fetchTradebookHistory,
      historyFromDate,
      historyRangePreset,
      historyToDate,
      persistHistoryCache,
    ],
  );

  useEffect(() => {
    void fetchServerTime().then((payload) => {
      setServerTodayNpt(payload.today_npt);
      setOrderedDate((current) => current || payload.today_npt);
      setHistoryFromDate((current) => current || offsetNepalDate(payload.today_npt, { days: 7 }));
      setHistoryToDate((current) => current || payload.today_npt);
      const utcMs = serverUtcToMs(payload.now);
      if (utcMs != null) {
        setStrategyDetailsNow(utcMs);
      }
    });
  }, []);

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

  const refreshScheduledOrders = useCallback(() => {
    coreCacheRef.current = null;
    setActiveTab('scheduled');
    void loadCoreData(true);
  }, [loadCoreData]);

  useEffect(() => {
    if (!clientsFetched) {
      return undefined;
    }
    if (sessionStorage.getItem(REFRESH_SCHEDULED_ORDERS_KEY)) {
      sessionStorage.removeItem(REFRESH_SCHEDULED_ORDERS_KEY);
      refreshScheduledOrders();
    }
    const handler = () => refreshScheduledOrders();
    window.addEventListener(SCHEDULED_ORDERS_CHANGED_EVENT, handler);
    return () => window.removeEventListener(SCHEDULED_ORDERS_CHANGED_EVENT, handler);
  }, [clientsFetched, refreshScheduledOrders]);

  useEffect(() => {
    if (activeTab !== 'scheduled' && activeTab !== 'logs' && strategyDetailsOrderId == null) {
      return undefined;
    }
    const intervalMs = strategyDetailsOrderId != null ? 3000 : liveRefreshMs;
    const interval = window.setInterval(() => {
      void loadCoreData(true);
    }, intervalMs);
    return () => window.clearInterval(interval);
  }, [activeTab, loadCoreData, liveRefreshMs, strategyDetailsOrderId]);

  useEffect(() => {
    if (strategyDetailsOrderId == null) {
      return undefined;
    }
    const tick = window.setInterval(() => {
      setStrategyDetailsNow((current) => (current == null ? current : current + 1000));
    }, 1000);
    return () => window.clearInterval(tick);
  }, [strategyDetailsOrderId]);

  useEffect(() => {
    if (strategyDetailsOrderId == null || strategyCatalogGuide) {
      return undefined;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        closeStrategyDetails();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [closeStrategyDetails, strategyCatalogGuide, strategyDetailsOrderId]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      void loadCoreData(true);
      void loadTradeBooks(activeClientIds, true);
      if (historyRangePreset !== 'custom') {
        void loadHistoryData(true);
      }
    }, backgroundCacheTtlMs);
    return () => window.clearInterval(interval);
  }, [activeClientIds, backgroundCacheTtlMs, historyRangePreset, loadCoreData, loadHistoryData, loadTradeBooks]);

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

  const handleClearOrderLogs = useCallback(async () => {
    const clientIds = activeClientIds;
    if (!clientIds.length) {
      setErrorMessage('No client is available to clear logs for.');
      return;
    }

    setIsClearingLogs(true);
    setErrorMessage('');
    setSuccessMessage('');
    try {
      const params = new URLSearchParams();
      params.set('client_ids', clientIds.join(','));
      const response = await fetch(`${apiUrl}/order_status_logs/clear?${params.toString()}`, {
        method: 'DELETE',
      });
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || `Clear logs request failed (${response.status})`);
      }
      setOrderLogs([]);
      coreCacheRef.current = null;
      try {
        sessionStorage.removeItem(CORE_CACHE_STORAGE_KEY);
      } catch {
        // Ignore storage errors.
      }
      await loadCoreData(true);
      setSuccessMessage('Order logs cleared.');
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : 'Failed to clear order logs.');
    } finally {
      setIsClearingLogs(false);
      setDialogVisible(false);
    }
  }, [activeClientIds, apiUrl, loadCoreData]);

  const confirmClearOrderLogs = useCallback(() => {
    const clientLabel = selectedClientId ? getClientLabel(selectedClientId) : `${activeClientIds.length} client(s)`;
    setDialogMessage(`Clear all visible order logs for ${clientLabel}? This will hide them from the UI but keep them marked deleted in the database.`);
    setDialogAction(() => () => {
      void handleClearOrderLogs();
    });
    setDialogVisible(true);
  }, [activeClientIds.length, getClientLabel, handleClearOrderLogs, selectedClientId]);

  const handleTabChange = (tab: OrderTab) => {
    setActiveTab(tab);
    if (tab !== 'scheduled') {
      setSelectedScheduledIds(new Set());
    }
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
      return false;
    }
    try {
      const response = await fetch(
        `${apiUrl}/cancel_order/?client_id=${clientId}&exchange_order_id=${exchangeSecurityID}`,
        { method: 'DELETE' },
      );
      if (response.ok) {
        return true;
      }
      setErrorMessage('Failed to cancel order');
      return false;
    } catch {
      setErrorMessage('Error cancelling order');
      return false;
    }
  };

  const cancellableOpenTrades = useMemo(
    () => orderBook.filter((row) => row.client_id && row.exchangeOrderId),
    [orderBook],
  );

  const confirmCancelAllOpenTrades = () => {
    if (!cancellableOpenTrades.length) {
      setErrorMessage('No open orders to cancel.');
      return;
    }
    setDialogMessage(`Cancel all ${cancellableOpenTrades.length} open order(s)?`);
    setDialogAction(() => () => {
      void handleCancelAllOpenTrades();
      setDialogVisible(false);
    });
    setDialogVisible(true);
  };

  const handleCancelAllOpenTrades = async () => {
    if (!cancellableOpenTrades.length) {
      setErrorMessage('No open orders to cancel.');
      return;
    }
    setIsBulkCancellingTrades(true);
    setErrorMessage('');
    setSuccessMessage('');
    let cancelled = 0;
    const failures: string[] = [];
    for (const row of cancellableOpenTrades) {
      const ok = await handleCancelOrder(String(row.client_id), Number(row.exchangeOrderId));
      if (ok) {
        cancelled += 1;
      } else {
        failures.push(String(row.exchangeOrderId));
      }
    }
    tradeBookCacheRef.current = null;
    await loadTradeBooks(activeClientIds, true);
    if (cancelled && failures.length) {
      setErrorMessage(`Cancelled ${cancelled} open order(s). Failed: ${failures.length}.`);
    } else if (failures.length) {
      setErrorMessage('Failed to cancel open orders.');
    } else {
      setSuccessMessage(`Cancelled ${cancelled} open order(s).`);
    }
    setIsBulkCancellingTrades(false);
  };

  const handleToggleScheduledRow = useCallback((rowId: string | number, selected: boolean) => {
    const orderId = Number(rowId);
    if (!Number.isFinite(orderId)) return;
    setSelectedScheduledIds((prev) => {
      const next = new Set(prev);
      if (selected) {
        next.add(orderId);
      } else {
        next.delete(orderId);
      }
      return next;
    });
  }, []);

  const handleToggleAllScheduledRows = useCallback((selected: boolean, rowIds: Array<string | number>) => {
    setSelectedScheduledIds((prev) => {
      const next = new Set(prev);
      rowIds.forEach((rowId) => {
        const orderId = Number(rowId);
        if (!Number.isFinite(orderId)) return;
        if (selected) {
          next.add(orderId);
        } else {
          next.delete(orderId);
        }
      });
      return next;
    });
  }, []);

  const runBulkDeleteScheduledOrders = useCallback(async (orderIds: number[]) => {
    if (!orderIds.length) {
      setErrorMessage('No scheduled orders selected for deletion.');
      return;
    }
    setIsBulkDeleting(true);
    setErrorMessage('');
    setSuccessMessage('');
    try {
      const { deletedIds, failedIds } = await deleteScheduledOrdersById(apiUrl, orderIds);
      if (deletedIds.length) {
        setScheduledOrders((prev) => prev.filter((order) => !deletedIds.includes(order.order_id)));
        setSelectedScheduledIds((prev) => {
          const next = new Set(prev);
          deletedIds.forEach((id) => next.delete(id));
          return next;
        });
        notifyScheduledOrdersChanged();
      }
      if (failedIds.length && deletedIds.length) {
        setErrorMessage(`Deleted ${deletedIds.length} order(s). Failed to delete ${failedIds.length}.`);
      } else if (failedIds.length) {
        setErrorMessage('Failed to delete selected scheduled orders.');
      } else {
        setSuccessMessage(`Deleted ${deletedIds.length} scheduled order(s).`);
      }
    } catch {
      setErrorMessage('Error deleting scheduled orders.');
    } finally {
      setIsBulkDeleting(false);
      setDialogVisible(false);
    }
  }, [apiUrl]);

  const confirmBulkDeleteScheduledOrders = useCallback((mode: ScheduledBulkDeleteMode) => {
    const orderIds = resolveScheduledOrderIdsForBulkDelete(
      scheduledOrders,
      mode,
      selectedScheduledIds,
      (order) => getOrderSide(order),
    );
    if (!orderIds.length) {
      setErrorMessage('No scheduled orders match that delete action.');
      return;
    }
    const label = mode === 'selected'
      ? `${orderIds.length} selected scheduled order(s)`
      : mode === 'buy'
        ? `all ${orderIds.length} buy scheduled order(s)`
        : mode === 'sell'
          ? `all ${orderIds.length} sell scheduled order(s)`
          : `all ${orderIds.length} scheduled order(s)`;
    setDialogMessage(`Are you sure you want to delete ${label}?`);
    setDialogAction(() => () => {
      void runBulkDeleteScheduledOrders(orderIds);
    });
    setDialogVisible(true);
  }, [runBulkDeleteScheduledOrders, scheduledOrders, selectedScheduledIds]);

  const confirmDeleteScheduledBatch = useCallback((batch: ScheduledBatchGroup<ScheduledOrderRow>) => {
    if (!batch.orders.length) {
      setErrorMessage('This batch has no scheduled orders to delete.');
      return;
    }
    setDialogMessage(
      `Delete all ${batch.orders.length} scheduled order(s) in batch "${batch.label}"?`,
    );
    setDialogAction(() => () => {
      void (async () => {
        setIsBulkDeleting(true);
        setErrorMessage('');
        setSuccessMessage('');
        try {
          const result = await deleteScheduledBatchById(apiUrl, batch.batchId);
          if (!result.ok) {
            setErrorMessage(result.error || 'Failed to delete scheduled batch.');
            return;
          }
          setScheduledOrders((prev) => prev.filter(
            (order) => !result.deletedIds.includes(order.order_id),
          ));
          setSelectedScheduledIds((prev) => {
            const next = new Set(prev);
            result.deletedIds.forEach((orderId) => next.delete(orderId));
            return next;
          });
          notifyScheduledOrdersChanged();
          setSuccessMessage(`Deleted batch "${batch.label}" (${result.deletedCount} order(s)).`);
        } catch {
          setErrorMessage('Error deleting scheduled batch.');
        } finally {
          setIsBulkDeleting(false);
          setDialogVisible(false);
        }
      })();
    });
    setDialogVisible(true);
  }, [apiUrl]);

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
            setSelectedScheduledIds((prev) => {
              const next = new Set(prev);
              next.delete(Number(row.order_id));
              return next;
            });
            notifyScheduledOrdersChanged();
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
        void (async () => {
          const ok = await handleCancelOrder(row.client_id, row.exchangeOrderId);
          if (ok) {
            setSuccessMessage('Order cancelled successfully');
            tradeBookCacheRef.current = null;
            await loadTradeBooks(activeClientIds, true);
          }
          setDialogVisible(false);
        })();
      });
      setDialogVisible(true);
    }
  };

  const mapScheduledOrderToRow = useCallback((order: ScheduledOrderRow) => {
    const side = getOrderSide(order);
    const strategyLabel = formatStrategyType(order.strategy_type, side);
    return {
      ...order,
      canEdit: isScheduledOrderEditable(order),
      stock: <StockClientCell symbol={order.script_name} clientLabel={getClientLabel(order.client_id)} />,
      order_type: side,
      trigger_price: formatScheduledTriggerPrice(order),
      strategy_type: (
        <button
          type="button"
          className={`strategy-chip ${side === 'BUY' ? 'buy' : side === 'SELL' ? 'sell' : ''}`}
          onClick={() => openStrategyDetails(order)}
          title="Show details"
          aria-label={`Show details for ${strategyLabel}`}
        >
          <span className="strategy-chip-label">{strategyLabel}</span>
          <span className="strategy-chip-action">Show details</span>
        </button>
      ),
      created_at: formatDateTime(order.created_at || order.target_reached_at || ''),
      qty: formatScheduledQuantitySummary(order),
      status: <ScheduledOrderStatusCell order={order} />,
    };
  }, [getClientLabel, openStrategyDetails]);

  const scheduledRows = useMemo(
    () => scheduledOrders.map(mapScheduledOrderToRow),
    [mapScheduledOrderToRow, scheduledOrders],
  );

  const scheduledBatchLayout = useMemo(() => {
    const { batches, standalone } = groupScheduledOrdersByBatch(scheduledOrders);
    return {
      batches: batches.map((batch) => ({
        ...batch,
        rows: batch.orders.map(mapScheduledOrderToRow),
      })),
      standaloneRows: standalone.map(mapScheduledOrderToRow),
    };
  }, [mapScheduledOrderToRow, scheduledOrders]);

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
            qty: Number(getDisplayQtyForOrder(order)),
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
                onClick={() => openStrategyDetails(detailOrder)}
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
    [getClientLabel, openStrategyDetails, orderLogs],
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
      columns: ['stock', 'order_type', 'qty', 'trigger_price', 'strategy_type', 'status', 'created_at'],
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
  const scheduledColumns = ['stock', 'order_type', 'qty', 'trigger_price', 'strategy_type', 'status', 'created_at'];

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
              className="order-logs-settings-btn"
              onClick={openSettings}
              aria-label="Open schedule settings"
              title="Schedule settings"
            >
              <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path
                  d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z"
                  stroke="currentColor"
                  strokeWidth="2"
                />
                <path
                  d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1 .6 1.7 1.7 0 0 0-.4 1.1V21a2 2 0 1 1-4 0v-.09A1.7 1.7 0 0 0 8.6 19.4a1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-.6-1 1.7 1.7 0 0 0-1.1-.4H3a2 2 0 1 1 0-4h.09A1.7 1.7 0 0 0 4.6 8.6a1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-.6 1.7 1.7 0 0 0 .4-1.1V3a2 2 0 1 1 4 0v.09A1.7 1.7 0 0 0 15.4 4.6a1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.7 1.7 0 0 0 19.4 9c.2.38.57.6 1 .6h.6a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.51 1.4Z"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </button>
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
              <div className="order-logs-date-field">
                <DatePicker
                  id="orderedDate"
                  selected={dateFromNepalDateString(orderedDate)}
                  onChange={handleDateChange}
                  dateFormat="yyyy-MM-dd"
                  placeholderText="Select a date"
                  className="input order-logs-datepicker order-logs-datepicker--with-today"
                  wrapperClassName="order-logs-datepicker-wrap"
                />
                <button
                  type="button"
                  className={`order-logs-date-today${orderedDate === todayNepalDate() ? ' active' : ''}`}
                  onClick={() => setOrderedDate(todayNepalDate())}
                  title="Jump to today (Nepal time)"
                  aria-label="Set ordered date to today"
                >
                  <span className="order-logs-date-today-icon" aria-hidden="true">📅</span>
                  <span className="order-logs-date-today-label">Today</span>
                </button>
              </div>
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
          <div className="order-logs-content-header-actions">
            <span className="badge badge-muted">{current.count} record(s)</span>
            {activeTab === 'logs' && (
              <button
                type="button"
                className="order-logs-clear-btn"
                onClick={confirmClearOrderLogs}
                disabled={isClearingLogs || activeClientIds.length === 0}
                aria-label="Clear order logs"
                title={activeClientIds.length > 0 ? 'Clear order logs' : 'No clients available'}
              >
                <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path
                    d="M4 7h16"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                  />
                  <path
                    d="M9 7V5.5A1.5 1.5 0 0 1 10.5 4h3A1.5 1.5 0 0 1 15 5.5V7"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                  />
                  <path
                    d="M7 7l1 13a1.5 1.5 0 0 0 1.5 1.4h5a1.5 1.5 0 0 0 1.5-1.4l1-13"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                  <path
                    d="M10 11v6M14 11v6"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                  />
                </svg>
              </button>
            )}
          </div>
        </div>

        {activeTab === 'scheduled' && scheduledOrders.length > 0 && (
          <div className="order-logs-scheduled-bulk">
            <span className="order-logs-scheduled-bulk-count">
              {selectedScheduledIds.size} selected
            </span>
            <div className="order-logs-scheduled-bulk-actions">
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                disabled={selectedScheduledIds.size === 0 || isBulkDeleting}
                onClick={() => confirmBulkDeleteScheduledOrders('selected')}
              >
                Delete selected
              </button>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                disabled={isBulkDeleting}
                onClick={() => confirmBulkDeleteScheduledOrders('buy')}
              >
                Delete all buy
              </button>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                disabled={isBulkDeleting}
                onClick={() => confirmBulkDeleteScheduledOrders('sell')}
              >
                Delete all sell
              </button>
              <button
                type="button"
                className="btn btn-danger btn-sm"
                disabled={isBulkDeleting}
                onClick={() => confirmBulkDeleteScheduledOrders('all')}
              >
                Delete all
              </button>
            </div>
          </div>
        )}

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
                <div className="order-logs-trade-section-actions">
                  <span className="badge badge-muted">{openTradeRows.length} record(s)</span>
                  {cancellableOpenTrades.length > 0 ? (
                    <button
                      type="button"
                      className="btn btn-danger btn-sm"
                      disabled={isBulkCancellingTrades}
                      onClick={confirmCancelAllOpenTrades}
                    >
                      Cancel all open
                    </button>
                  ) : null}
                </div>
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
        ) : activeTab === 'scheduled' ? (
          scheduledOrders.length === 0 ? (
            <div className="order-logs-empty-state">{current.empty}</div>
          ) : (
            <div className="order-logs-scheduled-sections">
              {scheduledBatchLayout.standaloneRows.length > 0 ? (
                <section className="order-logs-scheduled-batch order-logs-scheduled-batch-standalone">
                  {scheduledBatchLayout.batches.length > 0 ? (
                    <div className="order-logs-scheduled-batch-header">
                      <div className="order-logs-scheduled-batch-copy">
                        <h4 className="order-logs-scheduled-batch-title">Individual orders</h4>
                        <p className="order-logs-scheduled-batch-meta">Orders not part of a custom-query batch</p>
                      </div>
                    </div>
                  ) : null}
                  <CommonTable
                    data={scheduledBatchLayout.standaloneRows}
                    onAction={handleAction}
                    columns={scheduledColumns}
                    selectable
                    selectedRowIds={selectedScheduledIds}
                    rowIdKey="order_id"
                    onToggleRow={handleToggleScheduledRow}
                    onToggleAll={handleToggleAllScheduledRows}
                  />
                </section>
              ) : null}
              {scheduledBatchLayout.batches.map((batch) => (
                <section key={batch.batchId} className="order-logs-scheduled-batch">
                  <div className="order-logs-scheduled-batch-header">
                    <div className="order-logs-scheduled-batch-copy">
                      <h4 className="order-logs-scheduled-batch-title">{batch.label}</h4>
                      <p className="order-logs-scheduled-batch-meta">
                        {batch.orders.length} scheduled
                        {batch.symbolCount > batch.orders.length ? ` of ${batch.symbolCount}` : ''}
                        {batch.createdAt ? ` · ${formatDateTime(batch.createdAt)}` : ''}
                      </p>
                    </div>
                    <button
                      type="button"
                      className="btn btn-danger btn-sm"
                      disabled={isBulkDeleting}
                      onClick={() => confirmDeleteScheduledBatch(batch)}
                    >
                      Delete batch
                    </button>
                  </div>
                  <CommonTable
                    data={batch.rows}
                    onAction={handleAction}
                    columns={scheduledColumns}
                    selectable
                    selectedRowIds={selectedScheduledIds}
                    rowIdKey="order_id"
                    onToggleRow={handleToggleScheduledRow}
                    onToggleAll={handleToggleAllScheduledRows}
                  />
                </section>
              ))}
            </div>
          )
        ) : (
          <CommonTable
            data={current.rows}
            onAction={undefined}
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

      {strategyDetailsOrder && strategyDetailLayout && (
        <div className="strategy-details-backdrop" role="presentation" onClick={closeStrategyDetails}>
          <div className="strategy-details-modal strategy-details-modal-rich" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
            <div className="strategy-details-header">
              <div>
                <h3>Strategy Details</h3>
                <p>
                  <NepseAlphaSymbolLink symbol={strategyDetailsOrder.script_name} />
                </p>
              </div>
              <button type="button" className="strategy-details-close" onClick={closeStrategyDetails} aria-label="Close strategy details">
                ×
              </button>
            </div>

            <div className="strategy-details-headline">
              {strategyDetailLayout.headline.map((item) => (
                <div key={item.label} className="strategy-details-headline-item">
                  <span>{item.label}</span>
                  <strong>{item.value}</strong>
                </div>
              ))}
            </div>

            {strategyDetailLayout.primary.length > 0 ? (
              <div className="strategy-details-metrics">
                {strategyDetailLayout.primary.map((item) => (
                  <div key={item.label} className={`strategy-details-metric ${item.kind === 'muted' ? 'muted' : ''}`}>
                    <span className="strategy-details-metric-label">{item.label}</span>
                    <span className="strategy-details-metric-value">{item.value}</span>
                  </div>
                ))}
              </div>
            ) : null}

            {strategyDetailLayout.secondary.length > 0 ? (
              <div className="strategy-details-expand-wrap">
                <button
                  type="button"
                  className="strategy-details-see-more"
                  onClick={() => setStrategyDetailsExpanded((current) => !current)}
                  aria-expanded={strategyDetailsExpanded}
                >
                  {strategyDetailsExpanded ? 'See less' : 'See more details'}
                </button>
                {strategyDetailsExpanded ? (
                  <dl className="strategy-details-list strategy-details-list-secondary">
                    {strategyDetailLayout.secondary.map((item) => (
                      <div key={item.label} className="strategy-details-row">
                        <dt>{item.label}</dt>
                        <dd className={item.kind === 'muted' ? 'strategy-details-muted' : undefined}>
                          {item.kind === 'query' ? (
                            <pre className="strategy-details-query">{item.value}</pre>
                          ) : item.kind === 'logs' ? (
                            <pre className="strategy-details-logs">{item.value}</pre>
                          ) : (
                            item.value
                          )}
                        </dd>
                      </div>
                    ))}
                  </dl>
                ) : null}
              </div>
            ) : null}

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

      {settingsOpen && (
        <div className="order-logs-settings-backdrop" role="presentation" onClick={() => setSettingsOpen(false)}>
          <div
            className="order-logs-settings-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="orderLogsSettingsTitle"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="order-logs-settings-header">
              <div>
                <h3 id="orderLogsSettingsTitle">Schedule Settings</h3>
                <p>Change the server scan interval for scheduled orders.</p>
              </div>
              <button
                type="button"
                className="order-logs-settings-close"
                onClick={() => setSettingsOpen(false)}
                aria-label="Close schedule settings"
              >
                ×
              </button>
            </div>

            {settingsError ? <ErrorMessage message={settingsError} variant="error" /> : null}

            <div className="order-logs-settings-field">
              <label htmlFor="scanIntervalValue">Scan every</label>
              <div className="order-logs-settings-interval">
                <input
                  id="scanIntervalValue"
                  type="text"
                  inputMode="numeric"
                  pattern="[0-9]*"
                  className="input"
                  value={scanIntervalValue}
                  disabled={settingsLoading || settingsSaving}
                  onChange={(event) => {
                    const nextValue = event.target.value.replace(/[^0-9]/g, '');
                    setScanIntervalValue(nextValue === '' ? 0 : Number(nextValue));
                  }}
                />
                <select
                  className="select"
                  value={scanIntervalUnit}
                  disabled={settingsLoading || settingsSaving}
                  onChange={(event) => setScanIntervalUnit(event.target.value as ScanIntervalUnit)}
                >
                  {SCAN_INTERVAL_UNITS.map((unit) => (
                    <option key={unit.value} value={unit.value}>
                      {unit.label}
                    </option>
                  ))}
                </select>
              </div>
              <p>
                Saved as seconds on the server and applied to every scheduled order monitor.
                {settingsLimits
                  ? ` Allowed range: ${settingsLimits.monitor_interval_seconds.min}-${settingsLimits.monitor_interval_seconds.max} seconds.`
                  : ''}
              </p>
            </div>

            <div className="order-logs-settings-actions">
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => setSettingsOpen(false)}
                disabled={settingsSaving}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => void saveScheduleSettings()}
                disabled={settingsLoading || settingsSaving}
              >
                {settingsSaving ? 'Saving...' : 'Save'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default GetOrderStatus;
