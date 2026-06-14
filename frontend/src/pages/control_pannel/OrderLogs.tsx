import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import './OrderLogs.css';
import CommonTable from '../../components/table/Table';
import DialogBox from '../../components/dialog_box/DialogBox';
import ErrorMessage from '../../components/ErrorMessage';
import 'react-datepicker/dist/react-datepicker.css';
import { format } from 'date-fns';
import DatePicker from 'react-datepicker';
import { syncMonitoringStatus } from '../../hooks/monitoringSync';
import { fetchJson } from '../../utils/api';

type OrderTab = 'logs' | 'scheduled' | 'book' | 'history';

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
  expiry_time?: string | null;
  expiry_action?: string | null;
  max_allowed_slippage_percent?: number | null;
  scanning_count?: number;
  current_price?: number | null;
  live_status?: string;
  actionRequired?: boolean;
}

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

const toTitleCase = (value: string) =>
  value
    .replace(/_/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/\b\w/g, (char) => char.toUpperCase());

const getOrderSide = (order: Partial<ScheduledOrderRow> | any): 'BUY' | 'SELL' | 'UNKNOWN' => {
  const side = String(order.side || order.order_type || '').toUpperCase();
  if (side === 'BUY' || side === 'SELL') return side;
  return 'UNKNOWN';
};

const formatStrategyType = (strategy: unknown, sideValue: unknown): string => {
  const side = String(sideValue || '').toUpperCase();
  const raw = String(strategy || '').trim();
  if (!raw || raw === 'Fixed Price') {
    if (side === 'BUY') return 'Fixed Price Buy';
    if (side === 'SELL') return 'Fixed Price Sell';
    return 'Fixed Price';
  }
  return toTitleCase(raw);
};

const formatDateTime = (value: string | null | undefined) => {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
};

const formatCurrency = (value: number | string | null | undefined) => {
  if (value == null || value === '' || Number.isNaN(Number(value))) return '';
  return `Rs. ${Number(value).toLocaleString('en-NP', { maximumFractionDigits: 2 })}`;
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
  } else if (strategy === 'Buy Below Price' || strategy === 'Dip Buy') {
    addDetail(details, 'Trigger Buy Price', order.price, formatCurrency);
  } else if (strategy === 'Breakout Buy') {
    addDetail(details, 'Breakout Trigger Price', order.price, formatCurrency);
    addDetail(details, 'Confirmation Checks', order.consecutive_drop_checks);
  } else if (strategy === 'Time-Based Buy') {
    addDetail(details, 'Buy Price', order.price, formatCurrency);
    addDetail(details, 'Expiry Time', order.expiry_time, formatDateTime);
    addDetail(details, 'Expiry Action', order.expiry_action);
  } else if (strategy === 'Fast Stop Loss') {
    addDetail(details, 'Stop Loss Price', order.stop_loss_price, formatCurrency);
    addDetail(details, 'Max Allowed Slippage', order.max_allowed_slippage_percent, formatPercent);
    addDetail(details, 'Execution Rule', 'Use Top Buy if available, otherwise latest LTP.');
  } else if (strategy === 'Stop Limit Sell') {
    addDetail(details, 'Stop Trigger', order.stop_loss_price, formatCurrency);
    addDetail(details, 'Minimum Sell Price', order.stop_limit_price, formatCurrency);
  } else if (strategy === 'Trailing Stop Loss') {
    addDetail(details, 'Activation Price', order.activation_price, formatCurrency);
    addDetail(details, 'Highest Tracked Price', order.highest_tracked_price, formatCurrency);
    addDetail(details, 'Trailing Drop', order.trailing_drop_percent, formatPercent);
  } else if (strategy === 'Smart Profit Booking') {
    addDetail(details, 'Profit Target', order.profit_target_price, formatCurrency);
    addDetail(details, 'Highest Tracked Price', order.highest_tracked_price, formatCurrency);
    addDetail(details, 'Minimum Wait Time', order.minimum_wait_minutes ? `${order.minimum_wait_minutes} minutes` : '');
    addDetail(details, 'Trailing Drop', order.trailing_drop_percent, formatPercent);
    addDetail(details, 'Stable Band', order.stable_band_percent, formatPercent);
    addDetail(details, 'Target Reached At', order.target_reached_at, formatDateTime);
  } else if (strategy === 'Book Profit + Stop Loss') {
    addDetail(details, 'Book Profit Target', order.book_profit_price, formatCurrency);
    addDetail(details, 'Stop Loss Price', order.stop_loss_price, formatCurrency);
    addDetail(details, 'Highest Tracked Price', order.highest_tracked_price, formatCurrency);
  } else if (strategy === 'Partial Profit Booking') {
    addDetail(details, 'Highest Tracked Price', order.highest_tracked_price, formatCurrency);
    addDetail(details, 'Trailing Drop', order.trailing_drop_percent, formatPercent);
  } else if (strategy === 'Break-Even Protection') {
    addDetail(details, 'Average Buy Price', order.average_buy_price, formatCurrency);
    addDetail(details, 'Activation Price', order.activation_price, formatCurrency);
    addDetail(details, 'Highest Tracked Price', order.highest_tracked_price, formatCurrency);
    addDetail(details, 'Trailing Drop', order.trailing_drop_percent, formatPercent);
  } else if (strategy === 'Time-Based Exit') {
    addDetail(details, 'Target Price', order.profit_target_price, formatCurrency);
    addDetail(details, 'Stop Loss Price', order.stop_loss_price, formatCurrency);
    addDetail(details, 'Expiry Time', order.expiry_time, formatDateTime);
    addDetail(details, 'Expiry Action', order.expiry_action);
  } else if (strategy === 'Emergency Exit') {
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
  { id: 'book', label: 'Order Book', icon: '📖' },
  { id: 'history', label: 'History', icon: '🕐' },
];

const todayDate = () => format(new Date(), 'yyyy-MM-dd');

const GetOrderStatus: React.FC = () => {
  const [orderedDate, setOrderedDate] = useState<string>(todayDate);
  const [clientID, setClientID] = useState('');
  const [scriptName, setScriptName] = useState('');
  const scriptNameRef = useRef(scriptName);
  useEffect(() => {
    scriptNameRef.current = scriptName;
  }, [scriptName]);
  const [orderLogs, setOrderLogs] = useState<any[]>([]);
  const [scheduledOrders, setScheduledOrders] = useState<ScheduledOrderRow[]>([]);
  const [monitorIntervalMs, setMonitorIntervalMs] = useState(5000);
  const [monitoringActive, setMonitoringActive] = useState(false);
  const [orderBook, setOrderBook] = useState<any[]>([]);
  const [orderHistory, setOrderHistory] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [hasLoaded, setHasLoaded] = useState(false);
  const [loggedInClientIDs, setLoggedInClientIDs] = useState<string[]>([]);
  const [activeTab, setActiveTab] = useState<OrderTab>('scheduled');
  const [dialogVisible, setDialogVisible] = useState(false);
  const [dialogMessage, setDialogMessage] = useState('');
  const [dialogAction, setDialogAction] = useState<() => void>(() => {});
  const [strategyDetailsOrder, setStrategyDetailsOrder] = useState<ScheduledOrderRow | null>(null);
  const [errorMessage, setErrorMessage] = useState('');
  const [successMessage, setSuccessMessage] = useState('');
  const apiUrl = localStorage.getItem('apiUrl') || window.location.origin;

  const fetchLoggedInClientIDs = useCallback(async () => {
    try {
      const response = await fetch(`${apiUrl}/logged_in_clients/`);
      if (response.ok) {
        const data = await response.json();
        setLoggedInClientIDs(data.logged_in_client_ids);
        if (data.logged_in_client_ids.length > 0) {
          setClientID(data.logged_in_client_ids[0]);
        }
      } else {
        setLoggedInClientIDs([]);
        setErrorMessage('Failed to fetch logged-in client IDs');
      }
    } catch (error: any) {
      setLoggedInClientIDs([]);
      setErrorMessage(`Error fetching logged-in client IDs: ${error.message}`);
    }
  }, [apiUrl]);

  useEffect(() => {
    fetchLoggedInClientIDs();
  }, [fetchLoggedInClientIDs]);

  useEffect(() => {
    const loadInterval = async () => {
      const result = await fetchJson<{ monitor_interval: number }>('/get_monitor_interval');
      if (result.ok && result.data.monitor_interval > 0) {
        setMonitorIntervalMs(result.data.monitor_interval * 1000);
      }
    };
    void loadInterval();
  }, []);

  const handleDateChange = (date: Date | null) => {
    setOrderedDate(date ? format(date, 'yyyy-MM-dd') : todayDate());
  };

  const fetchOrderBook = useCallback(async (selectedClientId: string) => {
    if (!selectedClientId) {
      setOrderBook([]);
      return;
    }
    const response = await fetch(`${apiUrl}/get_order_book?client_id=${selectedClientId}`);
    if (response.ok) {
      setOrderBook(await response.json());
    } else {
      setOrderBook([]);
    }
  }, [apiUrl]);

  const fetchOrderStatusLogs = useCallback(
    async (options?: { silent?: boolean }) => {
      const params = new URLSearchParams();
      const filterScript = scriptNameRef.current.trim();
      if (filterScript) {
        params.set('script_name', filterScript);
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
        setOrderLogs(data.order_logs || []);
        setScheduledOrders(
          (data.scheduled_orders || []).map((order: ScheduledOrderRow) => ({
            ...order,
            actionRequired: true,
          })),
        );
        if (typeof data.monitoring_active === 'boolean') {
          setMonitoringActive(data.monitoring_active);
        }
        void syncMonitoringStatus();
        if (typeof data.monitor_interval === 'number' && data.monitor_interval > 0) {
          setMonitorIntervalMs(data.monitor_interval * 1000);
        }
      } else {
        setOrderLogs([]);
        setScheduledOrders([]);
        if (!options?.silent) {
          throw new Error('Failed to fetch order logs');
        }
      }
    },
    [apiUrl, orderedDate],
  );

  const fetchOrderHistory = useCallback(async (selectedClientId: string) => {
    if (!selectedClientId) {
      setOrderHistory([]);
      return;
    }
    const response = await fetch(`${apiUrl}/order_history?client_id=${selectedClientId}`);
    if (response.ok) {
      setOrderHistory(await response.json());
    } else {
      setOrderHistory([]);
    }
  }, [apiUrl]);

  const loadClientTmsData = useCallback(
    async (selectedClientId: string) => {
      await Promise.all([fetchOrderBook(selectedClientId), fetchOrderHistory(selectedClientId)]);
    },
    [fetchOrderBook, fetchOrderHistory],
  );

  const loadLogsAndScheduled = useCallback(
    async (options?: { silent?: boolean }) => {
      if (!options?.silent) {
        setIsLoading(true);
      }
      setErrorMessage('');

      try {
        await fetchOrderStatusLogs({ silent: true });
        setHasLoaded(true);
      } catch {
        if (!options?.silent) {
          setErrorMessage('Failed to load order data.');
        }
      } finally {
        if (!options?.silent) {
          setIsLoading(false);
        }
      }
    },
    [fetchOrderStatusLogs],
  );

  useEffect(() => {
    void loadLogsAndScheduled();
  }, [loadLogsAndScheduled]);

  useEffect(() => {
    const bookClient = clientID || loggedInClientIDs[0] || '';
    if (!bookClient) {
      return;
    }
    void loadClientTmsData(bookClient);
  }, [clientID, loadClientTmsData, loggedInClientIDs]);

  useEffect(() => {
    if (!hasLoaded) {
      return undefined;
    }

    const pollMs = monitoringActive ? 5000 : Math.max(monitorIntervalMs, 5000);
    const interval = window.setInterval(() => {
      void fetchOrderStatusLogs({ silent: true });
    }, pollMs);

    return () => window.clearInterval(interval);
  }, [fetchOrderStatusLogs, hasLoaded, monitorIntervalMs, monitoringActive]);

  const handleSubmit = async (e?: React.FormEvent) => {
    e?.preventDefault();
    setSuccessMessage('');
    setIsLoading(true);
    try {
      await loadLogsAndScheduled({ silent: true });
      const bookClient = clientID || loggedInClientIDs[0] || '';
      if (bookClient) {
        await loadClientTmsData(bookClient);
      }
      setSuccessMessage('Data refreshed');
    } catch {
      setErrorMessage('Failed to refresh order data.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleCancelOrder = async (exchangeSecurityID: number) => {
    try {
      const response = await fetch(
        `${apiUrl}/cancel_order/?client_id=${clientID}&exchange_order_id=${exchangeSecurityID}`,
        { method: 'DELETE' },
      );
      if (response.ok) {
        setSuccessMessage('Order cancelled successfully');
        await fetchOrderBook(clientID);
      } else {
        setErrorMessage('Failed to cancel order');
      }
    } catch {
      setErrorMessage('Error cancelling order');
    }
  };

  const handleAction = async (row: any, actionType: string) => {
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
        handleCancelOrder(row.exchangeOrderId);
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
          order_type: side,
          strategy_type: (
            <button
              type="button"
              className={`strategy-chip ${side === 'BUY' ? 'buy' : side === 'SELL' ? 'sell' : ''}`}
              onClick={() => setStrategyDetailsOrder(order)}
            >
              {strategyLabel}
            </button>
          ),
          created_at: formatDateTime(order.created_at || order.target_reached_at || ''),
          qty: formatScanCount(order.qty),
          status: formatLiveScanStatus(order),
        };
      }),
    [scheduledOrders],
  );

  const orderLogRows = useMemo(
    () =>
      orderLogs.map((order) => {
        const side = getOrderSide(order);
        const strategyLabel = formatStrategyType(order.strategy_type, side);
        const detailOrder: ScheduledOrderRow = {
          order_id: order.order_id || 0,
          client_id: order.client_id || '',
          script_name: order.script_name || '',
          price: Number(order.execution_price ?? order.price ?? 0),
          qty: Number(order.qty || 0),
          status: order.status || '',
          order_type: String(order.order_type || side).toLowerCase(),
          strategy_type: strategyLabel,
          side,
          created_at: order.timestamp,
          execution_price: order.execution_price ?? order.price,
          execution_reason: order.status,
        };
        return {
          timestamp: formatDateTime(order.timestamp),
          script_name: order.script_name,
          order_type: side,
          qty: formatScanCount(order.qty),
          strategy_type: (
            <button
              type="button"
              className={`strategy-chip ${side === 'BUY' ? 'buy' : side === 'SELL' ? 'sell' : ''}`}
              onClick={() => setStrategyDetailsOrder(detailOrder)}
            >
              {strategyLabel}
            </button>
          ),
          status: order.status,
          price: formatCurrency(order.execution_price ?? order.price),
        };
      }),
    [orderLogs],
  );

  const tabData: Record<OrderTab, { count: number; columns: string[]; rows: any[]; empty: string }> = {
    logs: {
      count: orderLogs.length,
      columns: getVisibleColumns(
        orderLogRows,
        ['timestamp', 'script_name', 'order_type', 'qty', 'strategy_type', 'status'],
        ['price'],
      ),
      rows: orderLogRows,
      empty: hasLoaded
        ? 'No order logs found for today.'
        : 'Loading order logs...',
    },
    scheduled: {
      count: scheduledOrders.length,
      columns: ['script_name', 'order_type', 'qty', 'strategy_type', 'status', 'created_at'],
      rows: scheduledRows,
      empty: hasLoaded
        ? 'No scheduled orders found.'
        : 'Loading scheduled orders...',
    },
    book: {
      count: orderBook.length,
      columns: [
        'clientMemberCode',
        'symbol',
        'buyOrSell',
        'orderQuantity',
        'orderPrice',
        'orderTime',
        'activeStatus',
        'totalTradedQuantity',
        'remainingOrderQuantity',
      ],
      rows: orderBook,
      empty: hasLoaded ? 'No open orders in the order book.' : 'Loading order book...',
    },
    history: {
      count: orderHistory.length,
      columns: [
        'clientMemberCode',
        'symbol',
        'buyOrSell',
        'orderQuantity',
        'orderPrice',
        'orderTime',
        'activeStatus',
        'totalTradedQuantity',
        'remainingOrderQuantity',
      ],
      rows: orderHistory,
      empty: hasLoaded ? 'No order history found.' : 'Loading order history...',
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
              Today&apos;s logs and all scheduled orders load automatically. Use filters to narrow results.
            </p>
          </div>
          {loggedInClientIDs.length > 0 && (
            <span className="badge badge-success">{loggedInClientIDs.length} client(s) online</span>
          )}
        </div>

        {successMessage && <ErrorMessage message={successMessage} variant="success" />}
        {errorMessage && <ErrorMessage message={errorMessage} variant="error" />}

        <form onSubmit={handleSubmit} className="order-logs-form">
          <div className="order-logs-form-grid">
            <div className="form-group">
              <label htmlFor="clientId">Client ID (book / history)</label>
              <select
                id="clientId"
                className="select"
                value={clientID}
                onChange={(e) => setClientID(e.target.value)}
                disabled={loggedInClientIDs.length === 0}
              >
                {loggedInClientIDs.length === 0 ? (
                  <option value="">No logged-in clients</option>
                ) : (
                  loggedInClientIDs.map((id) => (
                    <option key={id} value={id}>
                      {id}
                    </option>
                  ))
                )}
              </select>
              {loggedInClientIDs.length === 0 && (
                <span className="order-logs-hint">Log in via TMS Login tab first.</span>
              )}
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
                selected={new Date(orderedDate)}
                onChange={handleDateChange}
                dateFormat="yyyy-MM-dd"
                placeholderText="Select a date"
                className="input order-logs-datepicker"
                wrapperClassName="order-logs-datepicker-wrap"
                isClearable
              />
            </div>

            <div className="form-group order-logs-submit-group">
              <label>&nbsp;</label>
              <button type="submit" className="btn btn-primary order-logs-submit" disabled={isLoading}>
                {isLoading ? 'Loading...' : 'Refresh'}
              </button>
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
            onClick={() => setActiveTab(tab.id)}
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
          </h3>
          <span className="badge badge-muted">{current.count} record(s)</span>
        </div>

        {isLoading ? (
          <div className="order-logs-loading">
            <div className="order-logs-spinner" />
            <p>Fetching order data from TMS...</p>
          </div>
        ) : (
          <CommonTable
            data={current.rows}
            onAction={activeTab === 'scheduled' || activeTab === 'book' ? handleAction : undefined}
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
                <p>{strategyDetailsOrder.script_name}</p>
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
          </div>
        </div>
      )}
    </div>
  );
};

export default GetOrderStatus;
