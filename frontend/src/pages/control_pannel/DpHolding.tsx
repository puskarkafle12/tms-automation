import React, { useCallback, useEffect, useRef, useState } from 'react';
import './DpHolding.css';
import ErrorMessage from '../../components/ErrorMessage';
import NepseAlphaSymbolLink from '../../components/NepseAlphaSymbolLink';
import Dropdown from '../../components/Dropdown';
import CommonTable from '../../components/table/Table';
import StrategySellForm, { StrategyPayload } from './StrategySellForm';
import { getBoardLotSize, normalizeSellQty } from './lotSize';

interface DPHolding {
  clientID: string;
  valueAsOfPreviousClosePrice: number;
  valueAsOfLTP: number;
  percentChange?: string;
  gainedProfit?: number;
  color?: string;
  scrip?: string;
  symbolName?: string;
  previousCloseprice?: number;
  ltp?: number;
  currentBalance?: number;
  averageBuyPrice?: number;
  buyValue?: number;
  actualProfitLoss?: number | null;
  buyPriceSource?: string;
  holdingDays?: number | null;
  dateRange?: string;
}

interface ClientSession {
  client_id: string;
  display_name?: string | null;
  broker_no: string;
}

interface CombinedHolding extends DPHolding {
  holders: DPHolding[];
  clientCount: number;
}

interface QuoteLevel {
  sequenceId?: number;
  quantity?: number;
  price?: number;
  totalOrders?: number;
  buySell?: number;
}

interface StockQuote {
  ltp?: number;
  averageTradedPrice?: number;
  openPrice?: number;
  dayHigh?: number;
  dayLow?: number;
  closePrice?: number;
  lastTradedQty?: number;
  volume?: number;
  lastTradedTime?: string;
  totalBuyQty?: number;
  totalSellQty?: number;
  topBuy?: QuoteLevel[];
  topSell?: QuoteLevel[];
  security?: {
    id?: number;
    symbol?: string;
    securityName?: string;
    companyName?: string;
  };
}

const getApiUrl = () => localStorage.getItem('apiUrl') || window.location.origin;

const formatCurrency = (value: number) =>
  value.toLocaleString('en-NP', { maximumFractionDigits: 2 });

const holdingSymbol = (holding: DPHolding) => holding.scrip || holding.symbolName || '';

const clientLabel = (client: ClientSession) => {
  const name = client.display_name?.trim() || client.client_id;
  return client.broker_no ? `${name}[${client.broker_no}]` : name;
};

const normalizeSymbol = (holding: DPHolding) => holdingSymbol(holding).trim().toUpperCase();

const formatValue = (value: unknown) => {
  if (typeof value === 'number') {
    return value.toLocaleString('en-NP', { maximumFractionDigits: 2 });
  }
  if (typeof value === 'string') {
    return value || '-';
  }
  return '-';
};

const formatHoldingDuration = (days: number | null | undefined) => {
  const totalDays = Math.max(0, Math.floor(Number(days || 0)));
  if (!totalDays) {
    return '-';
  }

  if (totalDays < 30) {
    return `${totalDays}d`;
  }

  const years = Math.floor(totalDays / 365);
  const remainingAfterYears = totalDays % 365;
  const months = Math.floor(remainingAfterYears / 30);
  const remainingDays = remainingAfterYears % 30;

  const parts: string[] = [];
  if (years > 0) parts.push(`${years}y`);
  if (months > 0) parts.push(`${months}m`);
  if (remainingDays > 0 || parts.length === 0) parts.push(`${remainingDays}d`);

  return parts.join(' ');
};

const processHoldings = (holdings: DPHolding[]) =>
  holdings.map((holding) => {
    const fallbackProfit = (holding.valueAsOfLTP || 0) - (holding.valueAsOfPreviousClosePrice || 0);
    const gainedProfit = typeof holding.actualProfitLoss === 'number' ? holding.actualProfitLoss : fallbackProfit;
    const baseValue = holding.buyValue || holding.valueAsOfPreviousClosePrice || 0;
    const percentChange = baseValue
      ? ((gainedProfit / baseValue) * 100).toFixed(1)
      : '0.0';

    return {
      ...holding,
      percentChange,
      gainedProfit,
      color:
        gainedProfit > 0
          ? 'lightgreen'
          : gainedProfit < 0
            ? 'red'
            : 'lightyellow',
    };
  });

const combineHoldings = (holdings: DPHolding[]): CombinedHolding[] => {
  const bySymbol = new Map<string, CombinedHolding>();
  for (const holding of holdings) {
    const symbol = normalizeSymbol(holding);
    if (!symbol) {
      continue;
    }
    const existing = bySymbol.get(symbol);
    if (existing) {
      existing.holders.push(holding);
      existing.clientCount = new Set(existing.holders.map((item) => item.clientID)).size;
      existing.currentBalance = (existing.currentBalance || 0) + (holding.currentBalance || 0);
      existing.valueAsOfLTP = (existing.valueAsOfLTP || 0) + (holding.valueAsOfLTP || 0);
      existing.valueAsOfPreviousClosePrice =
        (existing.valueAsOfPreviousClosePrice || 0) + (holding.valueAsOfPreviousClosePrice || 0);
      existing.buyValue = (existing.buyValue || 0) + (holding.buyValue || 0);
      existing.actualProfitLoss = (existing.actualProfitLoss || 0) + (holding.actualProfitLoss || 0);
      existing.gainedProfit = existing.actualProfitLoss || ((existing.valueAsOfLTP || 0) - (existing.valueAsOfPreviousClosePrice || 0));
      existing.percentChange = existing.buyValue
        ? (((existing.gainedProfit || 0) / existing.buyValue) * 100).toFixed(1)
        : '0.0';
      existing.ltp = holding.ltp || existing.ltp;
      existing.previousCloseprice = holding.previousCloseprice || existing.previousCloseprice;
      existing.averageBuyPrice = existing.currentBalance
        ? (existing.buyValue || 0) / existing.currentBalance
        : existing.averageBuyPrice;
      existing.holdingDays = Math.max(Number(existing.holdingDays || 0), Number(holding.holdingDays || 0)) || null;
    } else {
      bySymbol.set(symbol, {
        ...holding,
        clientID: 'combined',
        scrip: symbol,
        holders: [holding],
        clientCount: 1,
      });
    }
  }
  return processHoldings(Array.from(bySymbol.values())) as CombinedHolding[];
};

const allocateBoardLotSafeSell = (holders: DPHolding[], qty: number, lotSize: number) => {
  const targetQty = Math.max(0, Math.floor(qty));
  const optionsByHolder = holders.map((holder) => {
    const holdingQty = Math.max(0, Math.floor(Number(holder.currentBalance || 0)));
    const options = new Set<number>([0]);
    for (let candidate = lotSize; candidate <= Math.min(holdingQty, targetQty); candidate += lotSize) {
      const normalized = normalizeSellQty(candidate, holdingQty, lotSize);
      if (normalized.qty === candidate || normalized.isSellAll) {
        options.add(candidate);
      }
    }
    if (holdingQty <= targetQty) {
      options.add(holdingQty);
    }
    return { holder, options: Array.from(options).sort((a, b) => b - a) };
  });

  const allocations = new Map<number, Array<{ client_id: string; qty: number }>>();
  allocations.set(0, []);

  for (const { holder, options } of optionsByHolder) {
    const next = new Map(allocations);
    for (const [sum, current] of Array.from(allocations.entries())) {
      for (const option of options) {
        const nextSum = sum + option;
        if (nextSum > targetQty || next.has(nextSum)) {
          continue;
        }
        next.set(
          nextSum,
          option > 0 && holder.clientID
            ? [...current, { client_id: holder.clientID, qty: option }]
            : current,
        );
      }
    }
    allocations.clear();
    next.forEach((value, key) => allocations.set(key, value));
  }

  return allocations.get(targetQty) || null;
};

const DPHoldings: React.FC = () => {
  const [loggedInClientIDs, setLoggedInClientIDs] = useState<string[]>([]);
  const [loggedInClients, setLoggedInClients] = useState<ClientSession[]>([]);
  const [selectedCombinedClients, setSelectedCombinedClients] = useState<string[]>([]);
  const [clientID, setClientID] = useState('');
  const [dpHoldings, setDPHoldings] = useState<DPHolding[]>([]);
  const [combinedHoldings, setCombinedHoldings] = useState<CombinedHolding[]>([]);
  const [holdingMode, setHoldingMode] = useState<'single' | 'combined'>('single');
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const [successMessage, setSuccessMessage] = useState('');
  const [hasFetched, setHasFetched] = useState(false);
  const [sellHolding, setSellHolding] = useState<DPHolding | null>(null);
  const [quote, setQuote] = useState<StockQuote | null>(null);
  const [quoteLoading, setQuoteLoading] = useState(false);
  const [quoteError, setQuoteError] = useState('');
  const [sellSubmitting, setSellSubmitting] = useState(false);
  const holdingsRequestId = useRef(0);

  useEffect(() => {
    const fetchLoggedInClientIDs = async () => {
      try {
        const response = await fetch(`${getApiUrl()}/logged_in_clients/`);
        if (response.ok) {
          const data = await response.json();
          const sessions: ClientSession[] = data.sessions || (data.logged_in_client_ids || []).map((id: string) => ({
            client_id: id,
            broker_no: '',
          }));
          const ids = sessions.map((client) => client.client_id);
          setLoggedInClients(sessions);
          setLoggedInClientIDs(ids);
          setSelectedCombinedClients(ids);
          setClientID(ids[0] || '');
        }
      } catch (error) {
        console.error('Error fetching logged-in client IDs:', error);
      }
    };
    fetchLoggedInClientIDs();
  }, []);

  const fetchHoldings = useCallback(async (selectedClientID: string) => {
    if (!selectedClientID) {
      setDPHoldings([]);
      setHasFetched(false);
      return;
    }

    const requestId = holdingsRequestId.current + 1;
    holdingsRequestId.current = requestId;
    setIsLoading(true);
    setErrorMessage('');
    setHasFetched(true);

    try {
      const response = await fetch(`${getApiUrl()}/dp_holdings?client_id=${selectedClientID}`, {
        headers: { Accept: 'application/json' },
      });

      if (requestId !== holdingsRequestId.current) {
        return;
      }

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        setErrorMessage(data.detail || data.message || 'Failed to fetch DP holdings.');
        setDPHoldings([]);
        return;
      }

      const data = await response.json();
      if (requestId !== holdingsRequestId.current) {
        return;
      }

      setDPHoldings(processHoldings(data));
    } catch (error) {
      setErrorMessage('Failed to fetch DP holdings. Check your API connection.');
      setDPHoldings([]);
    } finally {
      if (requestId === holdingsRequestId.current) {
        setIsLoading(false);
      }
    }
  }, []);


  useEffect(() => {
    if (holdingMode === 'single') {
      fetchHoldings(clientID);
    }
  }, [clientID, fetchHoldings, holdingMode]);

  const fetchCombinedHoldings = useCallback(async (clientIds: string[]) => {
    const selectedIds = clientIds.filter(Boolean);
    if (selectedIds.length === 0) {
      setCombinedHoldings([]);
      setHasFetched(false);
      return;
    }

    const requestId = holdingsRequestId.current + 1;
    holdingsRequestId.current = requestId;
    setIsLoading(true);
    setErrorMessage('');
    setHasFetched(true);

    try {
      const allHoldings = await Promise.all(
        selectedIds.map(async (id) => {
          const response = await fetch(`${getApiUrl()}/dp_holdings?client_id=${encodeURIComponent(id)}`, {
            headers: { Accept: 'application/json' },
          });
          if (!response.ok) {
            return [];
          }
          const data = await response.json();
          return processHoldings(
            data.map((holding: DPHolding) => ({
              ...holding,
              clientID: id,
            })),
          );
        }),
      );

      if (requestId !== holdingsRequestId.current) {
        return;
      }
      setCombinedHoldings(combineHoldings(allHoldings.flat()));
    } catch {
      setErrorMessage('Failed to fetch combined holdings. Check your API connection.');
      setCombinedHoldings([]);
    } finally {
      if (requestId === holdingsRequestId.current) {
        setIsLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    if (holdingMode === 'combined') {
      void fetchCombinedHoldings(selectedCombinedClients);
    }
  }, [fetchCombinedHoldings, holdingMode, selectedCombinedClients]);

  const toggleCombinedClient = (id: string) => {
    setSelectedCombinedClients((prev) =>
      prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id],
    );
  };

  const openSellDialog = async (holding: DPHolding) => {
    const symbol = holdingSymbol(holding);
    const quoteClientId = (holding as CombinedHolding).holders?.[0]?.clientID || clientID;
    setSellHolding(holding);
    setQuote(null);
    setQuoteError('');
    setSuccessMessage('');

    if (!quoteClientId || !symbol) {
      setQuoteError('Stock quote is not available for this holding.');
      return;
    }

    setQuoteLoading(true);
    try {
      const params = new URLSearchParams({ client_id: quoteClientId, symbol });
      const response = await fetch(`${getApiUrl()}/stock_quote?${params.toString()}`, {
        headers: { Accept: 'application/json' },
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        setQuoteError(data.detail || data.message || 'Stock quote unavailable.');
        return;
      }
      const data = await response.json();
      const nextQuote = data.quote || null;
      setQuote(nextQuote);
    } catch {
      setQuoteError('Stock quote unavailable.');
    } finally {
      setQuoteLoading(false);
    }
  };

  const closeSellDialog = () => {
    setSellHolding(null);
    setQuote(null);
    setQuoteError('');
    setSellSubmitting(false);
  };

  const submitSellOrder = async (strategyPayload: StrategyPayload) => {
    if (!sellHolding) {
      return;
    }

    const symbol = holdingSymbol(sellHolding);
    const qty = strategyPayload.qty;
    const price = strategyPayload.price;
    const availableQty = Number(sellHolding.currentBalance || 0);

    if (!symbol || !qty || qty < 1 || !price || price <= 0) {
      setQuoteError('Enter a valid sell quantity and price.');
      return;
    }
    if (availableQty > 0 && qty > availableQty) {
      setQuoteError(`Quantity cannot exceed holding balance (${availableQty}).`);
      return;
    }

    setSellSubmitting(true);
    setQuoteError('');
    try {
      const holders = (sellHolding as CombinedHolding).holders?.length
        ? [...(sellHolding as CombinedHolding).holders]
        : [{ ...sellHolding, clientID }];
      const lotSize = getBoardLotSize(quote?.security || sellHolding);
      const orders = strategyPayload.odd_lot_allowed
        ? (() => {
          let remainingQty = qty;
          const greedyOrders = [];
          for (const holder of holders) {
            if (remainingQty <= 0) {
              break;
            }
            const holderQty = Math.min(remainingQty, Number(holder.currentBalance || 0));
            if (holderQty <= 0 || !holder.clientID) {
              continue;
            }
            greedyOrders.push({ client_id: holder.clientID, qty: holderQty });
            remainingQty -= holderQty;
          }
          return remainingQty > 0 ? null : greedyOrders;
        })()
        : allocateBoardLotSafeSell(holders, qty, lotSize);

      if (!orders) {
        setQuoteError(
          strategyPayload.odd_lot_allowed
            ? `Quantity cannot exceed combined holding balance (${availableQty}).`
            : 'Could not split this combined sell into board-lot safe per-user orders. Use Sell All, enable Odd Lot Mode, or adjust quantity.',
        );
        return;
      }

      for (const order of orders) {
        const response = await fetch(`${getApiUrl()}/add_order/`, {
          method: 'POST',
          headers: {
            Accept: 'application/json',
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            client_id: order.client_id,
            script_name: symbol,
            order_type: 'sell',
            ...strategyPayload,
            qty: order.qty,
            security_details: quote?.security || {},
          }),
        });

        if (!response.ok) {
          const data = await response.json().catch(() => ({}));
          setQuoteError(data.detail || data.message || 'Failed to schedule sell order.');
          return;
        }
      }

      setSuccessMessage(
        orders.length > 1
          ? `${strategyPayload.strategy_type} scheduled for ${symbol} across ${orders.length} users.`
          : `${strategyPayload.strategy_type} scheduled for ${symbol}.`,
      );
      closeSellDialog();
    } catch {
      setQuoteError('Failed to schedule sell order. Check your API connection.');
    } finally {
      setSellSubmitting(false);
    }
  };

  const visibleHoldings = holdingMode === 'combined' ? combinedHoldings : dpHoldings;
  const totals = visibleHoldings.reduce(
    (acc, row) => {
      acc.valueAsOfPreviousClosePrice += row.valueAsOfPreviousClosePrice || 0;
      acc.valueAsOfLTP += row.valueAsOfLTP || 0;
      acc.buyValue += row.buyValue || 0;
      acc.actualProfitLoss += typeof row.actualProfitLoss === 'number' ? row.actualProfitLoss : 0;
      acc.dailyGain += (row.valueAsOfLTP || 0) - (row.valueAsOfPreviousClosePrice || 0);
      return acc;
    },
    { valueAsOfPreviousClosePrice: 0, valueAsOfLTP: 0, buyValue: 0, actualProfitLoss: 0, dailyGain: 0, profit: 0 },
  );
  totals.profit = totals.buyValue > 0 ? totals.actualProfitLoss : totals.valueAsOfLTP - totals.valueAsOfPreviousClosePrice;

  const isProfit = totals.profit >= 0;
  const isDailyGain = totals.dailyGain >= 0;
  const portfolioRows = visibleHoldings.map((holding, index) => {
    const dailyGain = (holding.valueAsOfLTP || 0) - (holding.valueAsOfPreviousClosePrice || 0);
    const totalProfit = typeof holding.actualProfitLoss === 'number' ? holding.actualProfitLoss : null;
    const averageBuyPrice = holding.averageBuyPrice ?? null;
    const ltp = holding.ltp ?? null;
    const currentValue = holding.valueAsOfLTP ?? null;
    const balance = holding.currentBalance ?? null;
    return {
      scrip: (
        <strong>
          <NepseAlphaSymbolLink symbol={holdingSymbol(holding)}>
            {formatValue(holding.scrip || holdingSymbol(holding))}
          </NepseAlphaSymbolLink>
          {holding.symbolName && holding.symbolName !== holding.scrip && (
            <span className="dp-holdings-symbol-name">{holding.symbolName}</span>
          )}
        </strong>
      ),
      ...(holdingMode === 'combined' ? { users: (holding as CombinedHolding).clientCount || 1 } : {}),
      averageBuyPrice: averageBuyPrice == null ? '-' : formatValue(averageBuyPrice),
      ltp: ltp == null ? '-' : formatValue(ltp),
      valueAsOfLTP: currentValue == null ? '-' : formatValue(currentValue),
      dailyGain: (
        <span className={dailyGain >= 0 ? 'positive' : 'negative'}>
          {dailyGain >= 0 ? '+' : '-'}{formatCurrency(Math.abs(dailyGain))}
        </span>
      ),
      totalProfit: totalProfit == null ? '-' : (
        <span className={totalProfit >= 0 ? 'positive' : 'negative'}>
          {totalProfit >= 0 ? '+' : '-'}{formatCurrency(Math.abs(totalProfit))}
        </span>
      ),
      percentChange: `${holding.percentChange}%`,
      balance: balance == null ? '-' : formatValue(balance),
      holdingDays: formatHoldingDuration(holding.holdingDays),
      action: (
        <button
          type="button"
          className="table-action-btn dp-sell-btn"
          onClick={() => openSellDialog(holding)}
        >
          Sell
        </button>
      ),
      color: holding.color,
      sortValues: {
        averageBuyPrice: averageBuyPrice ?? '',
        ltp: ltp ?? '',
        valueAsOfLTP: currentValue ?? '',
        dailyGain,
        totalProfit: totalProfit ?? '',
        percentChange: Number(String(holding.percentChange || 0).replace(/[^0-9.-]/g, '')) || 0,
        balance: balance ?? '',
        holdingDays: holding.holdingDays ?? '',
      },
      rowKey: `${holdingSymbol(holding)}-${index}`,
    };
  });
  const portfolioColumns = [
    'scrip',
    ...(holdingMode === 'combined' ? ['users'] : []),
    'balance',
    'averageBuyPrice',
    'ltp',
    'valueAsOfLTP',
    'dailyGain',
    'totalProfit',
    'percentChange',
    'holdingDays',
    'action',
  ];

  return (
    <div className="dp-holdings-page">
      <div className="dp-holdings-hero panel">
        <div className="dp-holdings-hero-content">
          <div className="dp-holdings-hero-icon" aria-hidden="true">📊</div>
          <div>
            <h2 className="dp-holdings-hero-title">Portfolio</h2>
            <p className="dp-holdings-hero-subtitle">
              View holdings, buy cost, current value, and profit or loss for logged-in clients.
            </p>
          </div>
        </div>
        {loggedInClientIDs.length > 0 && (
          <span className="badge badge-success">{loggedInClientIDs.length} client(s) online</span>
        )}
      </div>

      {errorMessage && <ErrorMessage message={errorMessage} variant="error" persistent />}
      {successMessage && <ErrorMessage message={successMessage} variant="success" />}

      <div className="dp-holdings-filters panel">
        <div className="dp-holdings-filters-header">
          <div>
            <h3 className="panel-title">Get Holdings</h3>
            <p className="panel-subtitle">Select one client or combine multiple logged-in clients into one portfolio.</p>
          </div>
          <div className="dp-holdings-tabs" role="tablist" aria-label="DP holding view">
            <button
              type="button"
              className={holdingMode === 'single' ? 'active' : ''}
              onClick={() => setHoldingMode('single')}
            >
              Single Client
            </button>
            <button
              type="button"
              className={holdingMode === 'combined' ? 'active' : ''}
              onClick={() => setHoldingMode('combined')}
            >
              Combined Portfolio
            </button>
          </div>
        </div>

        <div className="dp-holdings-form">
          {holdingMode === 'single' ? (
            <Dropdown
              id="dpClientId"
              label="User"
              value={clientID}
              onChange={setClientID}
              disabled={loggedInClientIDs.length === 0}
              placeholder={loggedInClientIDs.length === 0 ? 'No logged-in clients' : 'Select a user'}
              hint={loggedInClientIDs.length === 0 ? 'Log in via TMS Login tab first.' : undefined}
              options={loggedInClients.map((client) => ({
                value: client.client_id,
                label: clientLabel(client),
              }))}
            />
          ) : (
            <div className="form-group dp-combined-user-picker">
              <label>Combined Users</label>
              <div className="dp-combined-client-list">
                {loggedInClients.map((client) => (
                  <label key={client.client_id} className="dp-combined-client-chip">
                    <input
                      type="checkbox"
                      checked={selectedCombinedClients.includes(client.client_id)}
                      onChange={() => toggleCombinedClient(client.client_id)}
                    />
                    {clientLabel(client)}
                  </label>
                ))}
              </div>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => setSelectedCombinedClients(loggedInClientIDs)}
              >
                Add all users
              </button>
            </div>
          )}
        </div>
      </div>

      {visibleHoldings.length > 0 && (
        <div className="dp-holdings-stats">
          <div className="dp-holdings-stat-card">
            <span className="dp-holdings-stat-label">Holdings</span>
            <span className="dp-holdings-stat-value">{visibleHoldings.length}</span>
          </div>
          <div className="dp-holdings-stat-card">
            <span className="dp-holdings-stat-label">Daily Gain</span>
            <span className={`dp-holdings-stat-value ${isDailyGain ? 'positive' : 'negative'}`}>
              {isDailyGain ? '+' : '-'}{formatCurrency(Math.abs(totals.dailyGain))}
            </span>
          </div>
          <div className="dp-holdings-stat-card">
            <span className="dp-holdings-stat-label">Current Value (LTP)</span>
            <span className="dp-holdings-stat-value">Rs. {formatCurrency(totals.valueAsOfLTP)}</span>
          </div>
          <div className={`dp-holdings-stat-card ${isProfit ? 'profit' : 'loss'}`}>
            <span className="dp-holdings-stat-label">Total Profit</span>
            <span className={`dp-holdings-stat-value ${isProfit ? 'positive' : 'negative'}`}>
              {isProfit ? '+' : '-'}{formatCurrency(Math.abs(totals.profit))}
            </span>
          </div>
        </div>
      )}

      <div className="dp-holdings-content panel">
        <div className="dp-holdings-content-header">
          <h3 className="panel-title">Portfolio Table</h3>
          {clientID && hasFetched && !isLoading && (
            <span className="badge badge-muted">
              {holdingMode === 'combined' ? `${selectedCombinedClients.length} users` : clientID}
            </span>
          )}
        </div>

        {isLoading ? (
          <div className="dp-holdings-loading">
            <span className="dp-holdings-spinner" aria-hidden="true" />
            <p>Fetching DP holdings from TMS...</p>
          </div>
        ) : visibleHoldings.length > 0 ? (
          <div className="dp-holdings-table-shell">
            <CommonTable
              data={portfolioRows}
              columns={portfolioColumns}
              emptyMessage="No portfolio holdings found."
            />
            <div className={`dp-holdings-totals ${isProfit ? 'profit' : 'loss'}`} role="row">
              <div className="dp-holdings-total-item">
                <span className="dp-holdings-total-label">Daily Gain</span>
                <span className={`dp-holdings-total-value ${isDailyGain ? 'positive' : 'negative'}`}>
                  {isDailyGain ? '+' : '-'}{formatCurrency(Math.abs(totals.dailyGain))}
                </span>
              </div>
              <div className="dp-holdings-total-item">
                <span className="dp-holdings-total-label">Total LTP Value</span>
                <span className="dp-holdings-total-value">Rs. {formatCurrency(totals.valueAsOfLTP)}</span>
              </div>
              <div className="dp-holdings-total-item dp-holdings-total-item-pl">
                <span className="dp-holdings-total-label">Total Profit</span>
                <span className={`dp-holdings-total-value ${isProfit ? 'positive' : 'negative'}`}>
                  {isProfit ? '+' : ''}{formatCurrency(Math.abs(totals.profit))}
                </span>
              </div>
            </div>
          </div>
        ) : (
          <div className="dp-holdings-empty">
            <span style={{ fontSize: '2rem', opacity: 0.5 }} aria-hidden="true">📂</span>
            <p>
              {hasFetched
                ? holdingMode === 'combined'
                  ? 'No combined holdings found for selected users.'
                  : 'No holdings found for this client.'
                : 'Select a client to load DP holdings automatically.'}
            </p>
          </div>
        )}
      </div>

      {sellHolding && (
        <div className="dp-sell-modal-backdrop" role="presentation" onClick={closeSellDialog}>
          <div className="dp-sell-modal panel" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
            <div className="dp-sell-modal-header">
              <div>
                <h3>
                  {(sellHolding as CombinedHolding).holders?.length ? 'Combined Sell' : 'Sell'}{' '}
                  <NepseAlphaSymbolLink symbol={holdingSymbol(sellHolding)} />
                </h3>
                <p>{sellHolding.symbolName || quote?.security?.securityName || 'DP holding sell order'}</p>
              </div>
              <button type="button" className="dp-sell-close" onClick={closeSellDialog} aria-label="Close">×</button>
            </div>

            {quoteError && <ErrorMessage message={quoteError} variant="error" />}

            <div className="dp-sell-summary">
              <div>
                <span>LTP</span>
                <strong>{quoteLoading ? 'Loading...' : formatValue(quote?.ltp ?? sellHolding.ltp)}</strong>
              </div>
              <div>
                <span>Balance</span>
                <strong>{formatValue(sellHolding.currentBalance)}</strong>
              </div>
              {(sellHolding as CombinedHolding).holders?.length && (
                <div>
                  <span>Users</span>
                  <strong>{(sellHolding as CombinedHolding).clientCount}</strong>
                </div>
              )}
              <div>
                <span>Day Range</span>
                <strong>{quote ? `${formatValue(quote.dayLow)} - ${formatValue(quote.dayHigh)}` : '-'}</strong>
              </div>
              <div>
                <span>Volume</span>
                <strong>{formatValue(quote?.volume)}</strong>
              </div>
            </div>

            <div className="dp-depth-grid">
              <DepthTable title="Top Buy" rows={quote?.topBuy || []} />
              <DepthTable title="Top Sell" rows={quote?.topSell || []} />
            </div>

            {(sellHolding as CombinedHolding).holders?.length && (
              <div className="dp-combined-allocation">
                <h4>Sell allocation by user</h4>
                {(sellHolding as CombinedHolding).holders.map((holder) => {
                  const client = loggedInClients.find((item) => item.client_id === holder.clientID);
                  return (
                    <div key={`${holder.clientID}-${holdingSymbol(holder)}`} className="dp-combined-allocation-row">
                      <span>{client ? clientLabel(client) : holder.clientID}</span>
                      <strong>{formatValue(holder.currentBalance)}</strong>
                    </div>
                  );
                })}
              </div>
            )}

            <StrategySellForm
              key={`${holdingSymbol(sellHolding)}-${quote?.ltp || sellHolding.ltp || ''}`}
              currentLtp={Number(quote?.ltp ?? sellHolding.ltp ?? 0)}
              availableQty={Number(sellHolding.currentBalance || 0)}
              averageBuyPrice={
                sellHolding.currentBalance
                  ? Number(sellHolding.valueAsOfPreviousClosePrice || 0) / Number(sellHolding.currentBalance || 1)
                  : null
              }
              topBuyPrice={quote?.topBuy?.find((row) => Number(row.price || 0) > 0)?.price || null}
              initialQty={String(sellHolding.currentBalance || '')}
              initialPrice={String(quote?.ltp || sellHolding.ltp || '')}
              securityDetails={quote?.security || sellHolding}
              isSubmitting={sellSubmitting}
              submitError={quoteError}
              onSubmit={submitSellOrder}
            />
          </div>
        </div>
      )}
    </div>
  );
};

const DepthTable: React.FC<{ title: string; rows: QuoteLevel[] }> = ({ title, rows }) => {
  const activeRows = rows.filter((row) => Number(row.quantity || 0) > 0 || Number(row.price || 0) > 0);

  return (
    <div className="dp-depth-table">
      <h4>{title}</h4>
      {activeRows.length > 0 ? (
        <table>
          <thead>
            <tr>
              <th>Price</th>
              <th>Qty</th>
              <th>Orders</th>
            </tr>
          </thead>
          <tbody>
            {activeRows.map((row, index) => (
              <tr key={`${title}-${row.sequenceId ?? index}`}>
                <td>{formatValue(row.price)}</td>
                <td>{formatValue(row.quantity)}</td>
                <td>{formatValue(row.totalOrders)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p>No depth available.</p>
      )}
    </div>
  );
};

export default DPHoldings;
