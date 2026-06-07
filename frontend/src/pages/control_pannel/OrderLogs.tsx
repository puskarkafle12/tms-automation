import React, { useCallback, useEffect, useMemo, useState } from 'react';
import './OrderLogs.css';
import CommonTable from '../../components/table/Table';
import DialogBox from '../../components/dialog_box/DialogBox';
import ErrorMessage from '../../components/ErrorMessage';
import 'react-datepicker/dist/react-datepicker.css';
import { format } from 'date-fns';
import DatePicker from 'react-datepicker';
import { monitoringStore } from '../../hooks/monitoringStore';
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
  scanning_count?: number;
  current_price?: number | null;
  actionRequired?: boolean;
}

const formatLiveScanStatus = (order: ScheduledOrderRow, monitoringActive: boolean): string => {
  const base = order.status || 'pending';
  if (!monitoringActive) {
    return `${base} (off)`;
  }
  const count = order.scanning_count ?? 0;
  const ltp = order.current_price;
  if (ltp != null && Number(ltp) > 0) {
    return `${base} (${count} · ${Number(ltp).toFixed(1)})`;
  }
  return `${base} (${count})`;
};

const TABS: { id: OrderTab; label: string; icon: string }[] = [
  { id: 'logs', label: 'Order Logs', icon: '📋' },
  { id: 'scheduled', label: 'Scheduled', icon: '📅' },
  { id: 'book', label: 'Order Book', icon: '📖' },
  { id: 'history', label: 'History', icon: '🕐' },
];

const todayDate = () => format(new Date(), 'yyyy-MM-dd');

const GetOrderStatus: React.FC = () => {
  const [orderedDate, setOrderedDate] = useState<string>(todayDate);
  const [clientID, setClientID] = useState('');
  const [scriptName, setScriptName] = useState('');
  const [orderLogs, setOrderLogs] = useState<any[]>([]);
  const [scheduledOrders, setScheduledOrders] = useState<ScheduledOrderRow[]>([]);
  const [monitorIntervalMs, setMonitorIntervalMs] = useState(5000);
  const [monitoringActive, setMonitoringActive] = useState(false);
  const [orderBook, setOrderBook] = useState<any[]>([]);
  const [orderHistory, setOrderHistory] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [hasLoaded, setHasLoaded] = useState(false);
  const [loggedInClientIDs, setLoggedInClientIDs] = useState<string[]>([]);
  const [activeTab, setActiveTab] = useState<OrderTab>('logs');
  const [dialogVisible, setDialogVisible] = useState(false);
  const [dialogMessage, setDialogMessage] = useState('');
  const [dialogAction, setDialogAction] = useState<() => void>(() => {});
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
      if (scriptName.trim()) {
        params.set('script_name', scriptName.trim());
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
          monitoringStore.setScheduledActive(data.monitoring_active);
        }
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
    [apiUrl, orderedDate, scriptName],
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

    const pollMs = monitoringActive ? 2000 : monitorIntervalMs;
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
      scheduledOrders.map((order) => ({
        ...order,
        status: formatLiveScanStatus(order, monitoringActive),
        liveStatus: monitoringActive,
      })),
    [monitoringActive, scheduledOrders],
  );

  const tabData: Record<OrderTab, { count: number; columns: string[]; rows: any[]; empty: string }> = {
    logs: {
      count: orderLogs.length,
      columns: ['client_id', 'script_name', 'qty', 'price', 'order_type', 'status', 'timestamp'],
      rows: orderLogs,
      empty: hasLoaded
        ? 'No order logs found for today.'
        : 'Loading order logs...',
    },
    scheduled: {
      count: scheduledOrders.length,
      columns: ['client_id', 'script_name', 'order_type', 'price', 'status', 'qty'],
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
    </div>
  );
};

export default GetOrderStatus;
