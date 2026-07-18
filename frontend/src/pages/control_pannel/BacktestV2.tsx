import React, { FormEvent, useEffect, useMemo, useRef, useState } from 'react';
import * as echarts from 'echarts/core';
import { BarChart, CandlestickChart, LineChart, ScatterChart } from 'echarts/charts';
import { AxisPointerComponent, DataZoomComponent, GridComponent, LegendComponent, TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import { fetchJson } from '../../utils/api';
import NepseAlphaSymbolLink from '../../components/NepseAlphaSymbolLink';
import './BacktestV2.css';
import './BacktestV2Strategy.css';
import './StrongBuy.css';
import './StockScopePicker.css';

echarts.use([BarChart, CandlestickChart, LineChart, ScatterChart, AxisPointerComponent, DataZoomComponent, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);

type Preset = { id: string; name: string; category: string; family: string; description: string };
type Run = {
  run_id: string; name: string; status: string; progress_pct: number; symbols_completed: number;
  symbols_total: number; combinations_completed: number; current_symbol?: string; created_at?: string;
  configuration: { start_date: string; end_date: string; preset_ids: string[]; ordinary_shares_only: boolean; history_mode?: 'all_available' | 'custom'; strategy_mode?: 'presets' | 'custom'; custom_query_text?: string };
  error_summary?: string;
};
type ResultRow = Record<string, any> & { result_id: number; symbol: string; preset_name: string };
type ResultPage = { items: ResultRow[]; page: number; page_size: number; total: number; pages: number };
type Portfolio = { preset_id: string; preset_name: string; summary: Record<string, number>; allocation_config: Record<string, number> };
type Opportunity = ResultRow & { rank: number; recommendation_score: number; current_signal_status: string; signal_date: string; reliability_score: number; current_technical_score: number; wins: number; losses: number; loss_rate_pct: number; net_profit: number; ltp: number; latest_volume: number; average_volume_20: number; buy_zone_low?: number; buy_zone_high?: number; protective_stop?: number; sell_zone_low?: number; sell_zone_high?: number; legacy_cost_model: boolean; current_evidence: Record<string, any>; assumptions: Record<string, any> };
type OpportunitySort = { field: string; direction: 'asc' | 'desc' };
type OpportunityAdvancedFilter = { id: number; field: string; operator: string; value: string };
type OpportunityPage = { items: Opportunity[]; page: number; page_size: number; total: number; pages: number; sorts?: OpportunitySort[]; filters?: Array<Omit<OpportunityAdvancedFilter, 'id'>>; scope?: string; freshness?: { latest_completed_session?: string; status?: string; excluded_weekday?: string }; disclaimer: string };
type TradePage = { items: Array<Record<string, any>>; page: number; page_size: number; total: number; pages: number };
type ExecutionChartPayload = { symbol: string; candles: Array<{ date: string; open: number; close: number; low: number; high: number; volume: number }>; trades: Array<Record<string, any>> };

const today = new Date().toISOString().slice(0, 10);
const defaultStart = '2018-01-01';
const allHistoryStart = (() => {
  const value = new Date(`${today}T00:00:00Z`);
  value.setUTCFullYear(value.getUTCFullYear() - 20);
  value.setUTCDate(value.getUTCDate() + 1);
  return value.toISOString().slice(0, 10);
})();
const defaultCustomQuery = `STRATEGY_VERSION 1
SIDE BUY
BACKTEST {
  INITIAL_CAPITAL 100000
  CHARGE_MODEL "nepse_equity"
  INVESTOR_TYPE "individual"
  APPLY_CGT TRUE
  DP_CHARGE 25
  SLIPPAGE_PCT 0.1
  STOP_LOSS_PCT 6
  TAKE_PROFIT_PCT 15
  MIN_HOLDING_DAYS 0
  MAX_HOLDING_DAYS 30
  POSITION_SIZE_PCT 100
  MAX_VOLUME_PARTICIPATION_PCT 10
  RISK_FREE_RATE_PCT 4
  DATA_SOURCE "auto"
}
RULE "Supertrend PPO Confirmation" FOR SYMBOL "NABIL" {
  WHEN technical_supertrend = "Bullish" AND technical_ppo_histogram > 0 AND technical_adx_14 >= 20
  ORDER PERCENT_OF_AVAILABLE_CASH 100
  EXECUTE MAX 100 TIMES PER SYMBOL
}`;
const columns = [
  ['symbol', 'Symbol'], ['preset_name', 'Strategy'], ['sector', 'Sector'], ['robust_score', 'Robust'],
  ['oos_return_pct', 'OOS return %'], ['oos_expectancy_pct', 'OOS expectancy %'], ['oos_trades', 'OOS trades'],
  ['win_rate_pct', 'Win rate %'], ['total_trades', 'Trades'], ['max_drawdown_pct', 'Drawdown %'],
  ['walk_forward_profitable_pct', 'Stable folds %'], ['data_completeness_pct', 'Data %'],
  ['latest_volume', 'Latest volume'], ['recommendation_status', 'Status'],
] as const;
const opportunityColumns: Array<{ key: string; label: string; sortKey?: string }> = [
  { key: 'rank', label: 'Rank' }, { key: 'symbol', label: 'Stock', sortKey: 'symbol' },
  { key: 'signal', label: 'Signal state', sortKey: 'current_signal_status' },
  { key: 'strategy', label: 'Strategy', sortKey: 'preset_name' },
  { key: 'score', label: 'Combined score', sortKey: 'recommendation_score' },
  { key: 'buy_zone', label: 'Strategy buy zone' }, { key: 'stop', label: 'Protective stop' },
  { key: 'sell_zone', label: 'Strategy sell zone' }, { key: 'ltp', label: 'LTP', sortKey: 'ltp' },
  { key: 'date', label: 'Trading session', sortKey: 'current_signal_date' },
  { key: 'win_rate', label: 'Win rate', sortKey: 'win_rate_pct' },
  { key: 'trades', label: 'Trades', sortKey: 'total_trades' }, { key: 'hold', label: 'Avg hold', sortKey: 'average_holding_days' },
  { key: 'return', label: 'Net return %', sortKey: 'net_return_pct' },
  { key: 'drawdown', label: 'Max drawdown', sortKey: 'max_drawdown_pct' },
  { key: 'avg_volume', label: '20-day avg volume', sortKey: 'average_volume_20' },
  { key: 'volume', label: 'Latest volume', sortKey: 'latest_volume' }, { key: 'actions', label: '' },
];
const opportunityFilterFields: Array<{ field: string; label: string; type: 'number' | 'text'; placeholder?: string; defaultOperator?: string; options?: Array<{ value: string; label: string }> }> = [
  { field: 'recommendation_score', label: 'Combined score', type: 'number', placeholder: '70' },
  { field: 'symbol', label: 'Stock', type: 'text', placeholder: 'NABIL' },
  { field: 'sector', label: 'Sector', type: 'text', placeholder: 'Commercial Bank' },
  { field: 'preset_name', label: 'Strategy', type: 'text', defaultOperator: 'eq' },
  { field: 'category', label: 'Strategy category', type: 'text', defaultOperator: 'eq' },
  { field: 'current_signal_status', label: 'Signal state', type: 'text', defaultOperator: 'eq', options: [
    { value: 'strong_buy', label: 'Strong buy today' }, { value: 'buy', label: 'Buy today' },
    { value: 'watch', label: 'Triggered · review' }, { value: 'near_trigger', label: 'Near trigger' },
    { value: 'no_signal', label: 'Historical leader' }, { value: 'stale', label: 'Historical · stale' },
  ] },
  { field: 'win_rate_pct', label: 'Win rate', type: 'number', placeholder: '60' },
  { field: 'total_trades', label: 'Trades', type: 'number', placeholder: '20' },
  { field: 'average_holding_days', label: 'Avg hold', type: 'number', placeholder: '15', defaultOperator: 'lte' },
  { field: 'loss_rate_pct', label: 'Loss rate', type: 'number', placeholder: '40', defaultOperator: 'lte' },
  { field: 'confidence_score', label: 'Confidence', type: 'number', placeholder: '60' },
  { field: 'net_return_pct', label: 'Net return %', type: 'number', placeholder: '25' },
  { field: 'net_profit', label: 'Net profit', type: 'number', placeholder: '100000' },
  { field: 'profit_factor', label: 'Profit factor', type: 'number', placeholder: '1.5' },
  { field: 'max_drawdown_pct', label: 'Max drawdown', type: 'number', placeholder: '25', defaultOperator: 'lte' },
  { field: 'sharpe_ratio', label: 'Sharpe', type: 'number', placeholder: '1' },
  { field: 'reliability_score', label: 'Reliability', type: 'number', placeholder: '60' },
  { field: 'condition_progress_pct', label: 'Conditions ready', type: 'number', placeholder: '75' },
  { field: 'ltp', label: 'LTP', type: 'number', placeholder: '500' },
  { field: 'latest_volume', label: 'Latest volume', type: 'number', placeholder: '10000' },
  { field: 'average_volume_20', label: '20-session average volume', type: 'number', placeholder: '10000' },
  { field: 'median_volume_20', label: '20-session median volume', type: 'number', placeholder: '10000' },
];
const numericFilterOperators = [
  { value: 'gte', label: 'at least (≥)' }, { value: 'lte', label: 'at most (≤)' },
  { value: 'gt', label: 'greater than (>)' }, { value: 'lt', label: 'less than (<)' }, { value: 'eq', label: 'equals (=)' },
];
const textFilterOperators = [
  { value: 'contains', label: 'contains' }, { value: 'eq', label: 'equals' }, { value: 'neq', label: 'does not equal' },
];
const defaultOpportunityFilterOperator = (field: typeof opportunityFilterFields[number]) => field.defaultOperator || (field.type === 'number' ? 'gte' : 'contains');
const defaultOpportunityFilters = { minimum_trades: 5, minimum_win_rate: 0, minimum_confidence: 0, minimum_sharpe: -999, minimum_profit_factor: 0, maximum_drawdown: 100, minimum_return: 0, minimum_volume: '', category: '', current_signal: 'buy' };
const fmt = (value: unknown, key: string) => {
  if (value == null || value === '') return '—';
  if (typeof value === 'number') {
    if (key.includes('volume')) return value.toLocaleString();
    return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }
  return String(value).replaceAll('_', ' ');
};
const signalLabel = (status: string) => ({
  strong_buy: 'Strong buy today', buy: 'Buy today', watch: 'Triggered · review',
  near_trigger: 'Near trigger', no_signal: 'Historical leader', stale: 'Historical · stale',
}[status] || fmt(status, 'status'));

const StrongBuyCharts: React.FC<{ trades: Array<Record<string, any>> }> = ({ trades }) => {
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!ref.current) return undefined;
    const chart = echarts.init(ref.current);
    const labels = trades.map((trade) => trade.exit_date);
    const profits = trades.map((trade) => Number(trade.pnl || 0));
    const equity = trades.map((trade) => Number(trade.running_equity || 0));
    const drawdown = trades.map((trade) => -Number(trade.drawdown_after_trade_pct || 0));
    chart.setOption({ animation: false, tooltip: { trigger: 'axis' }, legend: { data: ['Equity', 'Trade P/L', 'Drawdown %'] }, grid: { left: 58, right: 45, top: 45, bottom: 50 }, xAxis: { type: 'category', data: labels, axisLabel: { hideOverlap: true } }, yAxis: [{ type: 'value', name: 'NPR' }, { type: 'value', name: 'DD %' }], dataZoom: [{ type: 'inside' }, { type: 'slider', height: 18 }], series: [{ name: 'Equity', type: 'line', data: equity, showSymbol: false, lineStyle: { color: '#176da6', width: 2 } }, { name: 'Trade P/L', type: 'bar', data: profits, itemStyle: { color: (params: any) => Number(params.value) >= 0 ? '#1a9b5f' : '#d44848' } }, { name: 'Drawdown %', type: 'line', yAxisIndex: 1, data: drawdown, showSymbol: false, lineStyle: { color: '#e0932d' }, areaStyle: { color: 'rgba(224,147,45,.12)' } }] });
    const observer = new ResizeObserver(() => chart.resize()); observer.observe(ref.current);
    return () => { observer.disconnect(); chart.dispose(); };
  }, [trades]);
  return <div className="strong-buy-chart" ref={ref} aria-label="Equity, trade profit and drawdown chart" />;
};

const TradeCandlestickChart: React.FC<{ resultId: number; symbol: string }> = ({ resultId, symbol }) => {
  const ref = useRef<HTMLDivElement | null>(null);
  const [payload, setPayload] = useState<ExecutionChartPayload | null>(null);
  const [chartError, setChartError] = useState('');
  useEffect(() => {
    setPayload(null); setChartError('');
    void fetchJson<ExecutionChartPayload>(`/api/backtests/v2/results/${resultId}/chart`).then((response) => {
      if (response.ok) setPayload(response.data); else setChartError(response.error || 'Could not load price history.');
    });
  }, [resultId]);
  useEffect(() => {
    if (!ref.current || !payload?.candles?.length) return undefined;
    const chart = echarts.init(ref.current);
    const dates = payload.candles.map((bar) => bar.date);
    const candleData = payload.candles.map((bar) => [Number(bar.open), Number(bar.close), Number(bar.low), Number(bar.high)]);
    const volumeData = payload.candles.map((bar) => ({ value: Number(bar.volume || 0), itemStyle: { color: Number(bar.close) >= Number(bar.open) ? '#21a66f' : '#e05252' } }));
    const buys = payload.trades.map((trade) => [trade.entry_date, Number(trade.entry_price), Number(trade.quantity || 0)]);
    const sells = payload.trades.map((trade) => [trade.exit_date, Number(trade.exit_price), Number(trade.pnl || 0)]);
    const npr = (value: number) => `${value >= 0 ? '+' : '−'}NPR ${Math.abs(value).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
    chart.setOption({
      animation: false, backgroundColor: '#0e1725',
      legend: { top: 10, textStyle: { color: '#c9d5e5' }, data: [`${symbol} daily`, 'Buy', 'Sell', 'Volume'] },
      tooltip: { trigger: 'axis', axisPointer: { type: 'cross' }, backgroundColor: 'rgba(9,17,29,.96)', borderColor: '#2c4058', textStyle: { color: '#edf5ff' } },
      axisPointer: { link: [{ xAxisIndex: 'all' }] },
      grid: [{ left: 72, right: 28, top: 55, height: '64%' }, { left: 72, right: 28, top: '76%', height: '13%' }],
      xAxis: [
        { type: 'category', data: dates, boundaryGap: true, axisLine: { lineStyle: { color: '#34465d' } }, axisLabel: { color: '#98aac0', hideOverlap: true }, splitLine: { show: false } },
        { type: 'category', gridIndex: 1, data: dates, boundaryGap: true, axisLine: { lineStyle: { color: '#34465d' } }, axisLabel: { show: false }, splitLine: { show: false } },
      ],
      yAxis: [
        { scale: true, axisLabel: { color: '#98aac0' }, splitLine: { lineStyle: { color: '#1d2b3d' } } },
        { scale: true, gridIndex: 1, axisLabel: { color: '#98aac0', formatter: (value: number) => value >= 1000000 ? `${(value / 1000000).toFixed(1)}m` : value >= 1000 ? `${(value / 1000).toFixed(0)}k` : String(value) }, splitLine: { show: false } },
      ],
      dataZoom: [{ type: 'inside', xAxisIndex: [0, 1], start: Math.max(0, 100 - Math.min(100, 260 / dates.length * 100)), end: 100 }, { type: 'slider', xAxisIndex: [0, 1], bottom: 8, height: 20, borderColor: '#34465d', textStyle: { color: '#98aac0' } }],
      series: [
        { name: `${symbol} daily`, type: 'candlestick', data: candleData, itemStyle: { color: '#20b27a', color0: '#e45454', borderColor: '#20b27a', borderColor0: '#e45454' } },
        { name: 'Buy', type: 'scatter', symbol: 'triangle', symbolSize: 13, data: buys, itemStyle: { color: '#42d392', borderColor: '#d9fff0', borderWidth: 1 }, label: { show: true, position: 'bottom', formatter: 'BUY', color: '#7cf0ba', fontSize: 9, fontWeight: 700 } },
        { name: 'Sell', type: 'scatter', symbol: 'diamond', symbolSize: 13, data: sells, itemStyle: { color: '#ff5e66', borderColor: '#ffe0e2', borderWidth: 1 }, label: { show: true, position: 'top', distance: 5, formatter: (params: any) => npr(Number(params.value?.[2] || 0)), color: '#ff9ca1', backgroundColor: 'rgba(8,15,25,.82)', padding: [2, 4], borderRadius: 3, fontSize: 9, fontWeight: 700 } },
        { name: 'Volume', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: volumeData, barMaxWidth: 8 },
      ],
    });
    const observer = new ResizeObserver(() => chart.resize()); observer.observe(ref.current);
    return () => { observer.disconnect(); chart.dispose(); };
  }, [payload, symbol]);
  if (chartError) return <div className="research-alert">{chartError}</div>;
  if (!payload) return <div className="trade-chart-loading">Loading the exact daily price and trade history…</div>;
  if (!payload.candles.length) return <div className="research-alert">No cached OHLCV candles are available for this result period.</div>;
  return <div className="backtest-trade-chart" ref={ref} aria-label={`${symbol} candlestick chart with every simulated buy and sell`} />;
};

const BacktestV2: React.FC = () => {
  const params = useMemo(() => new URLSearchParams(window.location.search), []);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [runs, setRuns] = useState<Run[]>([]);
  const [activeRun, setActiveRun] = useState<Run | null>(null);
  const [name, setName] = useState('Full NEPSE robustness scan');
  const [historyMode, setHistoryMode] = useState<'all_available' | 'custom'>('all_available');
  const [startDate, setStartDate] = useState(defaultStart);
  const [endDate, setEndDate] = useState(today);
  const [ordinaryOnly, setOrdinaryOnly] = useState(true);
  const [minHoldingDays, setMinHoldingDays] = useState(0);
  const [maxHoldingDays, setMaxHoldingDays] = useState('');
  const [strategyMode, setStrategyMode] = useState<'presets' | 'custom'>('presets');
  const [customQuery, setCustomQuery] = useState(defaultCustomQuery);
  const [copyStatus, setCopyStatus] = useState('');
  const [creating, setCreating] = useState(false);
  const [runScope, setRunScope] = useState<'all' | 'single'>('all');
  const [stockSearch, setStockSearch] = useState('');
  const [selectedStock, setSelectedStock] = useState<{ symbol: string; company_name: string; sector?: string } | null>(null);
  const [stockSuggestions, setStockSuggestions] = useState<Array<{ symbol: string; company_name: string; sector?: string }>>([]);
  const [error, setError] = useState('');
  const [showHowItWorks, setShowHowItWorks] = useState(false);
  const [tab, setTab] = useState<'opportunities' | 'combinations' | 'portfolio' | 'ai' | 'quality'>('combinations');
  const [results, setResults] = useState<ResultPage>({ items: [], page: 1, page_size: 50, total: 0, pages: 0 });
  const [sort, setSort] = useState({ key: 'robust_score', direction: 'desc' });
  const [minimumTrades, setMinimumTrades] = useState(10);
  const [minimumScore, setMinimumScore] = useState(0);
  const [symbolFilter, setSymbolFilter] = useState(params.get('stock') || '');
  const [sectorFilter, setSectorFilter] = useState('');
  const [minimumVolume, setMinimumVolume] = useState('');
  const [maxAge, setMaxAge] = useState('');
  const [includeNonEquities, setIncludeNonEquities] = useState(false);
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);
  const [aiQuestion, setAiQuestion] = useState('Top 10 reliable ordinary shares with positive out-of-sample return, at least 10 out-of-sample trades, and low drawdown');
  const [aiAnswer, setAiAnswer] = useState<any>(null);
  const [aiBusy, setAiBusy] = useState(false);
  const [opportunities, setOpportunities] = useState<OpportunityPage>({ items: [], page: 1, page_size: 25, total: 0, pages: 0, disclaimer: '' });
  const [opportunityFilters, setOpportunityFilters] = useState(defaultOpportunityFilters);
  const [opportunitySorts, setOpportunitySorts] = useState<OpportunitySort[]>([{ field: 'recommendation_score', direction: 'desc' }]);
  const [opportunityFilterRows, setOpportunityFilterRows] = useState<OpportunityAdvancedFilter[]>([]);
  const [appliedOpportunityFilters, setAppliedOpportunityFilters] = useState<OpportunityAdvancedFilter[]>([]);
  const nextOpportunityFilterId = useRef(1);
  const [selectedOpportunity, setSelectedOpportunity] = useState<any>(null);
  const [detailTrades, setDetailTrades] = useState<TradePage>({ items: [], page: 1, page_size: 50, total: 0, pages: 0 });
  const [tradeFilter, setTradeFilter] = useState('all');
  const [detailBusy, setDetailBusy] = useState(false);
  const [paperClientId, setPaperClientId] = useState(() => {
    try { return (JSON.parse(localStorage.getItem('client_ids') || '[]') as string[])[0] || ''; } catch { return ''; }
  });
  const [promotionBusy, setPromotionBusy] = useState(false);
  const [promotionMessage, setPromotionMessage] = useState('');

  const loadRuns = async () => {
    const response = await fetchJson<{ items: Run[] }>('/api/backtests/v2/runs?page=1&page_size=50');
    if (!response.ok) return;
    setRuns(response.data.items);
    const requested = params.get('run');
    setActiveRun((current) => response.data.items.find((item) => item.run_id === (requested || current?.run_id)) || current || response.data.items[0] || null);
  };

  useEffect(() => {
    void fetchJson<{ presets: Preset[] }>('/api/backtest/presets').then((response) => {
      if (response.ok) { setPresets(response.data.presets); setSelected(new Set(response.data.presets.map((item) => item.id))); }
    });
    void loadRuns();
  }, []);

  useEffect(() => {
    if (runScope !== 'single' || stockSearch.trim().length < 1 || selectedStock?.symbol === stockSearch.trim().toUpperCase()) { setStockSuggestions([]); return undefined; }
    const timer = window.setTimeout(() => {
      void fetchJson<{ items: Array<{ symbol: string; company_name: string; sector?: string }> }>(`/api/backtests/v2/symbols?search=${encodeURIComponent(stockSearch.trim())}&include_non_equities=${ordinaryOnly ? 'false' : 'true'}`).then((response) => response.ok && setStockSuggestions(response.data.items));
    }, 180);
    return () => window.clearTimeout(timer);
  }, [ordinaryOnly, runScope, selectedStock?.symbol, stockSearch]);

  useEffect(() => {
    if (!activeRun || ['completed', 'failed', 'cancelled', 'paused'].includes(activeRun.status)) return undefined;
    const timer = window.setInterval(async () => {
      const response = await fetchJson<Run>(`/api/backtests/v2/runs/${activeRun.run_id}`);
      if (response.ok) { setActiveRun(response.data); void loadRuns(); }
    }, 1500);
    return () => window.clearInterval(timer);
  }, [activeRun?.run_id, activeRun?.status]);

  const filterAst = useMemo(() => {
    const conditions: Array<Record<string, unknown>> = [];
    if (minimumTrades > 0) conditions.push({ field: 'oos_trades', operator: 'gte', value: minimumTrades });
    if (minimumScore > 0) conditions.push({ field: 'robust_score', operator: 'gte', value: minimumScore });
    if (symbolFilter.trim()) conditions.push({ field: 'symbol', operator: 'contains', value: symbolFilter.trim().toUpperCase() });
    if (sectorFilter.trim()) conditions.push({ field: 'sector', operator: 'contains', value: sectorFilter.trim() });
    if (minimumVolume) conditions.push({ field: 'latest_volume', operator: 'gte', value: Number(minimumVolume) });
    if (maxAge) conditions.push({ field: 'listing_age_days', operator: 'lte', value: Number(maxAge) });
    return { join: 'and', conditions };
  }, [maxAge, minimumScore, minimumTrades, minimumVolume, sectorFilter, symbolFilter]);

  const loadResults = async (page = 1) => {
    if (!activeRun) return;
    const response = await fetchJson<ResultPage>(`/api/backtests/v2/runs/${activeRun.run_id}/results/query`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filters: filterAst, include_non_equities: includeNonEquities, sort_by: sort.key, sort_direction: sort.direction, page, page_size: results.page_size }),
    });
    if (response.ok) setResults(response.data); else setError(response.error || 'Could not load results.');
  };

  useEffect(() => { void loadResults(1); }, [activeRun?.run_id, activeRun?.combinations_completed, filterAst, includeNonEquities, sort.key, sort.direction, results.page_size]);

  useEffect(() => {
    if (!activeRun || tab !== 'portfolio') return;
    void fetchJson<{ items: Portfolio[] }>(`/api/backtests/v2/runs/${activeRun.run_id}/portfolios`).then((response) => response.ok && setPortfolios(response.data.items));
  }, [activeRun?.run_id, activeRun?.status, tab]);

  const loadOpportunities = async (page = 1) => {
    const response = await fetchJson<OpportunityPage>('/api/backtests/v2/runs/all/strong-buys/query', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...opportunityFilters, sorts: opportunitySorts, filters: appliedOpportunityFilters.map(({ field, operator, value }) => ({ field, operator, value })), minimum_volume: opportunityFilters.minimum_volume ? Number(opportunityFilters.minimum_volume) : null, category: opportunityFilters.category || null, include_non_equities: includeNonEquities, page, page_size: opportunities.page_size }),
    });
    if (response.ok) setOpportunities(response.data); else setError(response.error || 'Could not load current opportunities.');
  };

  useEffect(() => { if (tab === 'opportunities') void loadOpportunities(1); }, [activeRun?.run_id, activeRun?.combinations_completed, tab, opportunityFilters, opportunitySorts, appliedOpportunityFilters, includeNonEquities, opportunities.page_size]);

  useEffect(() => {
    if (!showHowItWorks) return undefined;
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') setShowHowItWorks(false); };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [showHowItWorks]);

  const openOpportunity = async (row: Opportunity) => {
    setDetailBusy(true); setTradeFilter('all');
    const [detailResponse, tradesResponse] = await Promise.all([
      fetchJson<any>(`/api/backtests/v2/runs/all/strong-buys/${row.symbol}?result_id=${row.result_id}`),
      fetchJson<TradePage>(`/api/backtests/v2/results/${row.result_id}/trades?page=1&page_size=100&result_filter=all`),
    ]);
    setDetailBusy(false);
    if (detailResponse.ok && tradesResponse.ok) { setSelectedOpportunity(detailResponse.data); setDetailTrades(tradesResponse.data); }
    else setError((!detailResponse.ok && detailResponse.error) || (!tradesResponse.ok && tradesResponse.error) || 'Could not load recommendation details.');
  };

  const linkedDetailOpened = useRef(false);
  useEffect(() => {
    const resultId = Number(params.get('result') || 0);
    const symbol = String(params.get('stock') || '').toUpperCase();
    if (!activeRun || !resultId || !symbol || linkedDetailOpened.current) return;
    linkedDetailOpened.current = true;
    void openOpportunity({ result_id: resultId, symbol } as Opportunity);
  }, [activeRun?.run_id]);

  const filterDetailTrades = async (filter: string) => {
    const resultId = selectedOpportunity?.best?.result_id;
    if (!resultId) return;
    setTradeFilter(filter);
    const response = await fetchJson<TradePage>(`/api/backtests/v2/results/${resultId}/trades?page=1&page_size=100&result_filter=${filter}`);
    if (response.ok) setDetailTrades(response.data);
  };

  const startRun = async (event: FormEvent) => {
    event.preventDefault(); setCreating(true); setError('');
    if (runScope === 'single' && !selectedStock) { setCreating(false); setError('Choose one stock from the symbol suggestions before running.'); return; }
    if (strategyMode === 'custom' && customQuery.trim().length < 20) { setCreating(false); setError('Enter a complete Strategy Language query.'); return; }
    if (maxHoldingDays && minHoldingDays > Number(maxHoldingDays)) { setCreating(false); setError('Minimum holding days cannot exceed maximum holding days.'); return; }
    const response = await fetchJson<Run>('/api/backtests/v2/runs', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, history_mode: historyMode, start_date: historyMode === 'all_available' ? allHistoryStart : startDate, end_date: historyMode === 'all_available' ? today : endDate, strategy_mode: strategyMode, custom_query_text: strategyMode === 'custom' ? customQuery : null, preset_ids: strategyMode === 'presets' ? Array.from(selected) : [], symbols: runScope === 'single' && selectedStock ? [selectedStock.symbol] : null, ordinary_shares_only: ordinaryOnly, min_holding_days: minHoldingDays, max_holding_days: maxHoldingDays ? Number(maxHoldingDays) : null, data_source: 'merolagani', max_workers: 1, run_type: runScope === 'single' ? 'single_stock' : 'market_scan' }),
    }, 120000);
    setCreating(false);
    if (!response.ok) { setError(response.error || 'Could not queue the research run.'); return; }
    setActiveRun(response.data); void loadRuns();
  };

  const copyGptPrompt = async () => {
    const symbol = selectedStock?.symbol || 'NABIL';
    const response = await fetchJson<{ prompt: string }>(`/api/backtest/gpt-prompt?symbol=${encodeURIComponent(symbol)}`);
    if (!response.ok) { setError(response.error || 'Could not create the GPT prompt.'); return; }
    await navigator.clipboard.writeText(response.data.prompt);
    setCopyStatus('Prompt copied'); window.setTimeout(() => setCopyStatus(''), 1800);
  };

  const promoteToPaper = async () => {
    const resultId = selectedOpportunity?.best?.result_id;
    if (!resultId || !paperClientId.trim()) { setError('Enter the TMS client ID that will own the paper strategy.'); return; }
    setPromotionBusy(true); setPromotionMessage('');
    const response = await fetchJson<any>(`/api/backtests/v2/results/${resultId}/promote-to-paper`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ client_id: paperClientId.trim(), name: `Paper · ${selectedOpportunity.best.symbol} · ${selectedOpportunity.best.preset_name}` }),
    }, 120000);
    setPromotionBusy(false);
    if (!response.ok) { setError(response.error || 'Could not create the paper strategy.'); return; }
    setPromotionMessage(`Paper draft #${response.data.id} created. The exact query was copied and preloaded into Schedule Order; live use still requires its separate validation and confirmation.`);
    if (response.data.query_text) {
      await navigator.clipboard.writeText(response.data.query_text);
      const symbol = selectedOpportunity.best.symbol;
      let scheduleDraft: Record<string, unknown> = {};
      let strategyDraft: Record<string, unknown> = {};
      try { scheduleDraft = JSON.parse(localStorage.getItem('tms-schedule-order-draft-v1') || '{}'); } catch { scheduleDraft = {}; }
      try { strategyDraft = JSON.parse(localStorage.getItem('tms-strategy-form-draft-v1:schedule-order') || '{}'); } catch { strategyDraft = {}; }
      localStorage.setItem('tms-schedule-order-draft-v1', JSON.stringify({ ...scheduleDraft, clientID: paperClientId.trim(), scriptName: symbol, selectedScriptSymbol: symbol, orderType: 'buy', selectedStrategy: 'Custom Query Buy' }));
      localStorage.setItem('tms-strategy-form-draft-v1:schedule-order', JSON.stringify({ ...strategyDraft, strategy: 'Custom Query Buy', ruleQueryText: response.data.query_text }));
    }
  };

  const control = async (action: 'pause' | 'resume' | 'cancel' | 'retry') => {
    if (!activeRun) return;
    const response = await fetchJson<Run>(`/api/backtests/v2/runs/${activeRun.run_id}/${action}`, { method: 'POST' });
    if (response.ok) { setActiveRun(response.data); void loadRuns(); } else setError(response.error || `Could not ${action} this run.`);
  };

  const askAi = async () => {
    if (!activeRun || !aiQuestion.trim()) return;
    setAiBusy(true); setAiAnswer(null);
    const response = await fetchJson<any>(`/api/backtests/v2/runs/${activeRun.run_id}/ai-query`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: aiQuestion, include_non_equities: includeNonEquities }),
    }, 120000);
    setAiBusy(false);
    if (response.ok) setAiAnswer(response.data); else setError(response.error || 'AI analysis failed.');
  };

  const grouped = useMemo(() => Object.entries(presets.reduce<Record<string, Preset[]>>((all, preset) => {
    (all[preset.category] ||= []).push(preset); return all;
  }, {})), [presets]);

  const toggleSort = (key: string) => setSort((current) => ({ key, direction: current.key === key && current.direction === 'desc' ? 'asc' : 'desc' }));
  const toggleOpportunitySort = (field: string, additive: boolean) => setOpportunitySorts((current): OpportunitySort[] => {
    const index = current.findIndex((item) => item.field === field);
    if (!additive) {
      if (index === 0 && current.length === 1) return [{ field, direction: current[0].direction === 'desc' ? 'asc' : 'desc' }];
      return [{ field, direction: 'desc' }];
    }
    if (index < 0) return [...current, { field, direction: 'desc' as const }].slice(0, 8);
    if (current[index].direction === 'desc') return current.map((item, itemIndex) => itemIndex === index ? { ...item, direction: 'asc' as const } : item);
    const remaining = current.filter((_, itemIndex) => itemIndex !== index);
    return remaining.length ? remaining : [{ field: 'recommendation_score', direction: 'desc' }];
  });
  const opportunitySortMarker = (field?: string) => {
    if (!field) return '';
    const index = opportunitySorts.findIndex((item) => item.field === field);
    return index < 0 ? '↕' : `${opportunitySorts[index].direction === 'desc' ? '↓' : '↑'} ${index + 1}`;
  };
  const addOpportunityFilter = () => {
    const field = opportunityFilterFields[0];
    setOpportunityFilterRows((current) => [...current, { id: nextOpportunityFilterId.current++, field: field.field, operator: defaultOpportunityFilterOperator(field), value: '' }]);
  };
  const updateOpportunityFilter = (id: number, update: Partial<OpportunityAdvancedFilter>) => {
    setOpportunityFilterRows((current) => current.map((item) => item.id === id ? { ...item, ...update } : item));
  };
  const applyOpportunityFilters = () => {
    if (opportunityFilterRows.some((item) => !item.value.trim())) {
      setError('Enter a value for every advanced recommendation filter before applying.'); return;
    }
    setError('');
    setAppliedOpportunityFilters(opportunityFilterRows.map((item) => ({ ...item })));
  };
  const resetOpportunityWorkspace = () => {
    setOpportunityFilters(defaultOpportunityFilters);
    setOpportunityFilterRows([]);
    setAppliedOpportunityFilters([]);
    setOpportunitySorts([{ field: 'recommendation_score', direction: 'desc' }]);
  };

  return <div className="research-page">
    <header className="research-hero">
      <div><span className="research-kicker">NEPSE Research Lab · Daily data</span><h1>Backtesting workspace</h1><p>Reproducible out-of-sample rankings, shared-capital simulation, and persistent background scans.</p></div>
      <div className="research-hero-actions"><button type="button" onClick={() => setShowHowItWorks(true)}>How it works</button><a href="/dashboard/backtest?legacy=1">Custom strategy language</a><span>Research only · no broker orders</span></div>
    </header>

    {error && <div className="research-alert" role="alert">{error}<button onClick={() => setError('')}>Dismiss</button></div>}

    {showHowItWorks && <div className="backtest-help-backdrop" role="presentation">
      <section className="backtest-help-modal" role="dialog" aria-modal="true" aria-labelledby="backtest-help-title">
        <header><div><span>NEPSE Research Lab guide</span><h2 id="backtest-help-title">How this backtest and table work</h2><p>Use this page to compare historical research results—not as a promise of future performance.</p></div><button type="button" className="backtest-help-close" onClick={() => setShowHowItWorks(false)} aria-label="Close how it works">×</button></header>
        <div className="backtest-help-body">
          <section><h3>1. What a backtest does</h3><p>Your entry conditions are evaluated after each completed daily session. A matching BUY signal enters at the next available session open. One single-stock backtest holds one position at a time and never places a broker order.</p><div className="backtest-help-flow"><span>Daily close signal</span><b>→</b><span>Next open entry</span><b>→</b><span>Risk-managed exit</span><b>→</b><span>Net result</span></div></section>
          <section><h3>2. How selling works</h3><p>The current engine is long-only: the strategy creates the BUY entry; exits are managed by the selected risk settings.</p><ol><li><b>Stop loss / trailing stop first.</b> If both stop and target are touched in one daily candle, the stop is used first as the conservative assumption.</li><li><b>Take profit</b> applies after the minimum holding period.</li><li><b>Maximum holding days</b> exits at that day’s close.</li><li><b>End of history</b> closes any remaining position at the final close.</li></ol><p className="backtest-help-note">A gap below a stop exits at the weaker opening price. Buy and sell slippage are included.</p></section>
          <section><h3>3. Net profit includes Nepal-market costs</h3><div className="backtest-help-grid"><article><b>On buy</b><span>Broker commission, SEBON fee, buy slippage.</span></article><article><b>On sell</b><span>Broker commission, SEBON fee, DP charge, sell slippage and CGT on profitable sales.</span></article><article><b>Position limits</b><span>Cash, selected sizing, and maximum volume participation can reject an order.</span></article></div><p>Every saved result keeps the exact charge model, sizing, stop, target and holding settings used for that run.</p></section>
          <section><h3>4. Reading the Recommendations table</h3><p>It shows one best-matching historical strategy per stock. By default, ordinary shares are included; change the instrument filter only if you intentionally want funds, debentures, promoter shares, or other classes.</p><div className="backtest-help-score"><b>Combined score = 45% win rate + 30% net return + 15% trade sample + 10% reliability</b><span>Trade sample reaches its maximum at 50 trades. Net return is capped at 100 before scoring so one extreme result cannot dominate.</span></div><p><b>Robust score is different:</b> it favours locked out-of-sample expectancy and return, Sharpe, drawdown protection, walk-forward stability, and enough out-of-sample trades. Use Robust score when comparing strategies; use Combined score to quickly rank recommendation candidates.</p></section>
          <section><h3>5. Finding the result you want</h3><ul><li>Click any column heading to sort it. Hold <kbd>Shift</kbd> while clicking another heading to add a secondary sort.</li><li>Use the quick filters for trades, win rate, return, liquidity and signal state.</li><li>Use Advanced stock filters for exact multiple conditions. All chosen conditions must match.</li><li><b>Strong buy today</b> means the saved strategy condition matched on the latest completed daily session; <b>Historical leader</b> means it ranked well historically but has no new entry today.</li></ul></section>
          <section className="backtest-help-disclaimer"><h3>Important</h3><p>Historical performance, rankings and current signals are research tools. They can be affected by data gaps, liquidity, fees, execution assumptions and market conditions. Review the trades, sample size, drawdown, current signal conditions and your own risk limits before using a paper or live strategy.</p></section>
        </div>
        <footer><span>Press <kbd>Esc</kbd> anytime to close.</span><button type="button" onClick={() => setShowHowItWorks(false)}>Yes, I understand</button></footer>
      </section>
    </div>}

    <section className="research-run-library" aria-label="Saved backtest runs">
      <div className="research-run-library-head"><span><small>Continuous research</small><h2>Scan workspaces</h2><p>Identical stock and strategy scans update one workspace instead of creating duplicates.</p></span><div><strong>{runs.length}</strong><span>unique</span><button onClick={() => void loadRuns()}>Refresh</button></div></div>
      <div className="research-run-strip">{runs.length === 0 ? <p>No v2 research runs yet.</p> : runs.map((run) => <button key={run.run_id} className={activeRun?.run_id === run.run_id ? 'active' : ''} onClick={() => setActiveRun(run)}><span className="research-run-card-top"><b>{run.name}</b><em className={`run-${run.status}`}>{run.status}</em></span><span className="research-run-card-metrics"><small><strong>{run.symbols_completed}/{run.symbols_total}</strong> stocks</small><small><strong>{run.combinations_completed.toLocaleString()}</strong> results</small></span><span className="research-run-card-progress"><i style={{ width: `${Math.max(0, Math.min(100, run.progress_pct || 0))}%` }} /></span></button>)}</div>
    </section>

    <section className="research-layout">
      <main className="research-main">
        <details className="research-new-run" open={!activeRun}>
          <summary><span><b>New research run</b><small>Name it, select the universe and strategies, then leave it running safely in the background.</small></span><strong>Configure</strong></summary>
          <form onSubmit={startRun}>
            <div className="research-form-grid"><label>Run name<input value={name} onChange={(e) => setName(e.target.value)} required /></label><label>History<select value={historyMode} onChange={(e) => setHistoryMode(e.target.value as 'all_available' | 'custom')}><option value="all_available">All available history (default)</option><option value="custom">Custom date range</option></select><small>{historyMode === 'all_available' ? 'Uses up to 20 years and each stock’s earliest available session.' : 'Use only when comparing an exact market period.'}</small></label>{historyMode === 'custom' && <><label>Start<input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} required /></label><label>End<input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} required /></label></>}<label>Universe<select value={ordinaryOnly ? 'ordinary' : 'all'} onChange={(e) => setOrdinaryOnly(e.target.value === 'ordinary')}><option value="ordinary">Ordinary shares only</option><option value="all">All instrument classes</option></select></label><label>Stocks to test<select value={runScope} onChange={(e) => { setRunScope(e.target.value as 'all' | 'single'); setSelectedStock(null); setStockSearch(''); }}><option value="all">All stocks in universe</option><option value="single">One particular stock</option></select></label><label>Strategy source<select value={strategyMode} onChange={(e) => setStrategyMode(e.target.value as 'presets' | 'custom')}><option value="presets">Professional presets</option><option value="custom">One custom query</option></select></label><label>Minimum hold (days)<input type="number" min="0" max="365" value={minHoldingDays} onChange={(e) => setMinHoldingDays(Math.max(0, Number(e.target.value) || 0))} /><small>Stop-loss protection remains active.</small></label><label>Maximum hold (days)<input type="number" min="1" max="365" value={maxHoldingDays} onChange={(e) => setMaxHoldingDays(e.target.value)} placeholder="Use preset/query default" /><small>Blank preserves each strategy default.</small></label></div>
            {runScope === 'single' && <div className="stock-picker"><label>Find stock by symbol or company name<input value={stockSearch} onChange={(e) => { setStockSearch(e.target.value.toUpperCase()); setSelectedStock(null); }} placeholder="Type NABIL or Nabil Bank…" autoComplete="off" required /></label>{selectedStock && <div className="selected-stock"><b>{selectedStock.symbol}</b><span>{selectedStock.company_name}</span><em>{selectedStock.sector || 'Sector unavailable'}</em></div>}{stockSuggestions.length > 0 && <div className="stock-suggestions" role="listbox">{stockSuggestions.map((item) => <button type="button" role="option" aria-selected={selectedStock?.symbol === item.symbol} key={item.symbol} onClick={() => { setSelectedStock(item); setStockSearch(item.symbol); setStockSuggestions([]); setName(`${item.symbol} strategy research`); }}><b>{item.symbol}</b><span>{item.company_name}</span><em>{item.sector || ''}</em></button>)}</div>}<small>All selected presets will run only on the chosen stock. This does not affect saved all-market runs.</small></div>}
            {strategyMode === 'presets' ? <><div className="research-preset-head"><span><b>Preset catalog</b><small>{selected.size}/{presets.length} selected · grouped by family</small></span><div><button type="button" onClick={() => setSelected(new Set(presets.map((item) => item.id)))}>All {presets.length}</button><button type="button" onClick={() => setSelected(new Set())}>Clear</button></div></div><div className="research-preset-groups">{grouped.map(([category, items]) => <details key={category}><summary>{category}<span>{items.filter((item) => selected.has(item.id)).length}/{items.length}</span></summary><div>{items.map((preset) => <label key={preset.id} title={preset.description}><input type="checkbox" checked={selected.has(preset.id)} onChange={() => setSelected((current) => { const next = new Set(current); next.has(preset.id) ? next.delete(preset.id) : next.add(preset.id); return next; })} /><span>{preset.name}</span></label>)}</div></details>)}</div></> : <div className="research-custom-query"><div><span><b>Custom Strategy Language</b><small>The symbol in this query is a template. For an all-stock run, the server safely retargets only the symbol and keeps every condition, risk setting, charge, and order-sizing rule unchanged.</small></span><button type="button" onClick={() => void copyGptPrompt()}>Copy prompt for GPT</button>{copyStatus && <em>{copyStatus}</em>}</div><textarea value={customQuery} onChange={(e) => setCustomQuery(e.target.value)} rows={20} spellCheck={false} /></div>}
            <div className="research-submit"><p>History is cached per stock. Scans use a low-priority background worker so normal trading and dashboard requests stay responsive. The exact versioned query is stored with every result and can be promoted to paper, then separately confirmed for live scheduling.</p><button disabled={creating || (strategyMode === 'presets' ? selected.size === 0 : customQuery.trim().length < 20)}>{creating ? 'Queuing…' : strategyMode === 'custom' ? `Queue query on ${runScope === 'all' ? 'all stocks' : selectedStock?.symbol || 'one stock'}` : `Queue ${selected.size} strategies`}</button></div>
          </form>
        </details>

        {activeRun && <>
          <section className="research-run-head"><div><span className={`run-${activeRun.status}`}>{activeRun.status}</span><h2>{activeRun.name}</h2><p>{activeRun.configuration.start_date} → {activeRun.configuration.end_date} · ordinary shares {activeRun.configuration.ordinary_shares_only ? 'default' : 'not restricted'}</p></div><div className="research-controls">{activeRun.status === 'running' && <button onClick={() => void control('pause')}>Pause</button>}{activeRun.status === 'paused' && <button onClick={() => void control('resume')}>Resume</button>}{activeRun.status === 'failed' && <button onClick={() => void control('retry')}>Retry failed</button>}{['queued', 'running', 'paused'].includes(activeRun.status) && <button className="danger" onClick={() => void control('cancel')}>Cancel</button>}</div></section>
          <section className="research-progress"><div><b>{activeRun.progress_pct}%</b><span>{activeRun.symbols_completed}/{activeRun.symbols_total} stocks</span><span>{activeRun.combinations_completed.toLocaleString()} persisted results</span><span>{activeRun.current_symbol || 'Waiting for next checkpoint'}</span></div><progress value={activeRun.progress_pct} max="100" /><small>Partial rankings below update after every completed stock. You may leave this page and return later.</small></section>
          <nav className="research-tabs">{([['combinations', 'All results'], ['portfolio', 'Portfolio'], ['ai', 'Ask AI'], ['quality', 'Data quality']] as const).map(([key, label]) => <button key={key} className={tab === key ? 'active' : ''} onClick={() => setTab(key)}>{label}</button>)}<a href="/dashboard/recommendations">Open live recommendations ↗</a></nav>

          {tab === 'opportunities' && <section className="research-panel strong-buy-panel">
            <div className="research-panel-title recommendation-title"><div><span className="current-session-badge">Fresh, deduplicated market view</span><h3>Best stock recommendations across all research</h3><p>One best strategy per stock across every compatible run. Duplicate stock/strategy results are merged and older trading sessions are excluded.</p></div><div className="freshness-card"><small>Latest completed trading session</small><strong>{opportunities.freshness?.latest_completed_session || 'Checking…'}</strong><span>Refreshes at 10:00 and 11:00 Nepal time</span></div></div>
            {activeRun?.symbols_total === 1 && <div className="single-stock-explainer"><span><b>{activeRun.combinations_completed.toLocaleString()} strategies were tested for this stock.</b> Recommendations keeps its best strategy; Combinations contains every result.</span><button type="button" onClick={() => setTab('combinations')}>View all {activeRun.combinations_completed.toLocaleString()} strategies</button></div>}
            <details className="recommendation-tools">
              <summary><span><b>Filters and sorting</b><small>Open when you want to narrow the fresh market list.</small></span><strong>{appliedOpportunityFilters.length ? `${appliedOpportunityFilters.length} active` : 'Optional'}</strong></summary>
              <div className="strong-buy-filters">
              <label>Min trades<input type="number" min="0" value={opportunityFilters.minimum_trades} onChange={(e) => setOpportunityFilters((v) => ({ ...v, minimum_trades: Number(e.target.value) }))} /></label>
              <label>Min historical win %<input type="number" min="0" max="100" value={opportunityFilters.minimum_win_rate} onChange={(e) => setOpportunityFilters((v) => ({ ...v, minimum_win_rate: Number(e.target.value) }))} /></label>
              <label>Min confidence<input type="number" min="0" max="100" value={opportunityFilters.minimum_confidence} onChange={(e) => setOpportunityFilters((v) => ({ ...v, minimum_confidence: Number(e.target.value) }))} /></label>
              <label>Min Sharpe<input type="number" step=".1" value={opportunityFilters.minimum_sharpe} onChange={(e) => setOpportunityFilters((v) => ({ ...v, minimum_sharpe: Number(e.target.value) }))} /></label>
              <label>Min profit factor<input type="number" step=".1" min="0" value={opportunityFilters.minimum_profit_factor} onChange={(e) => setOpportunityFilters((v) => ({ ...v, minimum_profit_factor: Number(e.target.value) }))} /></label>
              <label>Max drawdown %<input type="number" min="0" max="100" value={opportunityFilters.maximum_drawdown} onChange={(e) => setOpportunityFilters((v) => ({ ...v, maximum_drawdown: Number(e.target.value) }))} /></label>
              <label>Min return %<input type="number" value={opportunityFilters.minimum_return} onChange={(e) => setOpportunityFilters((v) => ({ ...v, minimum_return: Number(e.target.value) }))} /></label>
              <label>Min volume<input type="number" min="0" value={opportunityFilters.minimum_volume} onChange={(e) => setOpportunityFilters((v) => ({ ...v, minimum_volume: e.target.value }))} /></label>
              <label>Strategy category<select value={opportunityFilters.category} onChange={(e) => setOpportunityFilters((v) => ({ ...v, category: e.target.value }))}><option value="">All categories</option>{Array.from(new Set(presets.map((item) => item.category))).map((category) => <option key={category}>{category}</option>)}</select></label>
              <label>Signal state<select value={opportunityFilters.current_signal} onChange={(e) => setOpportunityFilters((v) => ({ ...v, current_signal: e.target.value }))}><option value="all">Best available</option><option value="triggered_today">Triggered latest session</option><option value="near_trigger">Near trigger</option><option value="strong_buy">Strong Buy only</option><option value="buy">Buy or Strong Buy</option><option value="watch">Triggered · review</option><option value="no_signal">Historical only</option></select></label>
              <label>Instrument class<select value={includeNonEquities ? 'all' : 'ordinary'} onChange={(e) => setIncludeNonEquities(e.target.value === 'all')}><option value="ordinary">Ordinary shares only</option><option value="all">Explicitly include all</option></select></label>
              <label>Rows per page<select value={opportunities.page_size} onChange={(e) => setOpportunities((current) => ({ ...current, page_size: Number(e.target.value) }))}><option>25</option><option>50</option><option>100</option></select></label>
              </div>
            <section className="recommendation-filter-builder" aria-label="Advanced recommendation filters">
              <div className="recommendation-filter-heading"><div><h4>Advanced stock filters</h4><p>Combine up to 12 exact conditions. Every condition must match; filters are never silently weakened.</p></div><button type="button" onClick={addOpportunityFilter}>+ Add condition</button></div>
              {opportunityFilterRows.length > 0 && <div className="recommendation-filter-rows">{opportunityFilterRows.map((item) => {
                const definition = opportunityFilterFields.find((field) => field.field === item.field) || opportunityFilterFields[0];
                const valueOptions = definition.options || (definition.field === 'preset_name'
                  ? Array.from(new Map(presets.map((preset) => [preset.name, { value: preset.name, label: preset.name }])).values())
                  : definition.field === 'category'
                    ? Array.from(new Set(presets.map((preset) => preset.category))).sort().map((category) => ({ value: category, label: category }))
                    : undefined);
                const operators = definition.type === 'number' ? numericFilterOperators : valueOptions ? textFilterOperators.filter((operator) => operator.value !== 'contains') : textFilterOperators;
                return <div className="recommendation-filter-row" key={item.id}>
                  <select aria-label="Filter field" value={item.field} onChange={(e) => { const next = opportunityFilterFields.find((field) => field.field === e.target.value) || opportunityFilterFields[0]; updateOpportunityFilter(item.id, { field: next.field, operator: defaultOpportunityFilterOperator(next), value: '' }); }}>{opportunityFilterFields.map((field) => <option value={field.field} key={field.field}>{field.label}</option>)}</select>
                  <select aria-label="Filter operator" value={item.operator} onChange={(e) => updateOpportunityFilter(item.id, { operator: e.target.value })}>{operators.map((operator) => <option value={operator.value} key={operator.value}>{operator.label}</option>)}</select>
                  {valueOptions ? <select aria-label={`${definition.label} filter value`} value={item.value} onChange={(e) => updateOpportunityFilter(item.id, { value: e.target.value })}><option value="">Choose {definition.label.toLowerCase()}…</option>{valueOptions.map((option) => <option value={option.value} key={option.value}>{option.label}</option>)}</select> : <input aria-label={`${definition.label} filter value`} type={definition.type === 'number' ? 'number' : 'text'} step={definition.type === 'number' ? 'any' : undefined} value={item.value} placeholder={definition.placeholder} onChange={(e) => updateOpportunityFilter(item.id, { value: e.target.value })} />}
                  <button type="button" className="remove-filter" aria-label={`Remove ${definition.label} filter`} onClick={() => setOpportunityFilterRows((current) => current.filter((row) => row.id !== item.id))}>×</button>
                </div>;
              })}</div>}
              <div className="recommendation-filter-actions"><span>{appliedOpportunityFilters.length ? `${appliedOpportunityFilters.length} advanced condition${appliedOpportunityFilters.length === 1 ? '' : 's'} applied` : 'No advanced conditions applied'}</span><div><button type="button" className="secondary" onClick={resetOpportunityWorkspace}>Reset filters + sorting</button><button type="button" disabled={opportunityFilterRows.length === 0} onClick={applyOpportunityFilters}>Apply exact filters</button></div></div>
              {appliedOpportunityFilters.length > 0 && <div className="applied-filter-chips">{appliedOpportunityFilters.map((item) => { const label = opportunityFilterFields.find((field) => field.field === item.field)?.label || item.field; const operator = [...numericFilterOperators, ...textFilterOperators].find((option) => option.value === item.operator)?.label || item.operator; return <span key={item.id}>{label} {operator} <b>{item.value}</b></span>; })}</div>}
            </section>
              <div className="recommendation-sort-guide"><span><b>Dynamic sorting:</b> click a column to make it primary and toggle ↓/↑. Hold Shift while clicking to add or change secondary rules.</span><button type="button" onClick={() => setOpportunitySorts([{ field: 'recommendation_score', direction: 'desc' }])}>Reset to combined score</button></div>
            </details>
            <div className="research-table-summary"><b>{opportunities.total} fresh ranked stocks</b><span>All research merged · no duplicate stock rows · {opportunitySorts.map((item, index) => { const label = opportunityColumns.find((column) => column.sortKey === item.field)?.label || item.field; return `${index + 1}. ${label} ${item.direction === 'desc' ? '↓' : '↑'}`; }).join(' · ')}</span></div>
            <div className="research-table-wrap strong-buy-table"><table><thead><tr>{opportunityColumns.map((column) => { const sortIndex = opportunitySorts.findIndex((item) => item.field === column.sortKey); const ariaSort = sortIndex === 0 ? (opportunitySorts[0].direction === 'desc' ? 'descending' : 'ascending') : undefined; return <th key={column.key} aria-sort={ariaSort}>{column.sortKey ? <button type="button" className={`recommendation-sort-button ${sortIndex >= 0 ? 'active' : ''}`} title="Click for primary sort; Shift-click to add a sorting rule" onClick={(event) => toggleOpportunitySort(column.sortKey!, event.shiftKey)}>{column.label}<span>{opportunitySortMarker(column.sortKey)}</span></button> : column.label}</th>; })}</tr></thead><tbody>{opportunities.items.map((row) => <tr key={row.result_id}><td>{row.rank}</td><td><div className="stock-chart-links"><button className="symbol-link" onClick={() => void openOpportunity(row)}>{row.symbol}</button><NepseAlphaSymbolLink symbol={row.symbol}>Chart ↗</NepseAlphaSymbolLink></div></td><td><span className={`signal-pill ${row.current_signal_status}`}>{signalLabel(row.current_signal_status)}</span></td><td>{row.preset_name}</td><td><b>{fmt(row.recommendation_score, 'score')}</b></td><td className="price-zone buy-zone">{row.buy_zone_low ? `NPR ${fmt(row.buy_zone_low, 'money')}–${fmt(row.buy_zone_high, 'money')}` : 'No current entry'}</td><td className="price-zone stop-zone">{row.protective_stop ? `NPR ${fmt(row.protective_stop, 'money')}` : '—'}</td><td className="price-zone sell-zone">{row.sell_zone_low ? `NPR ${fmt(row.sell_zone_low, 'money')}–${fmt(row.sell_zone_high, 'money')}` : '—'}</td><td>{fmt(row.ltp, 'ltp')}</td><td>{row.signal_date}</td><td><b>{fmt(row.win_rate_pct, 'percent')}%</b></td><td>{row.total_trades}</td><td>{fmt(row.average_holding_days, 'days')} days</td><td>{fmt(row.net_return_pct, 'percent')}%</td><td>{fmt(row.max_drawdown_pct, 'percent')}%</td><td>{fmt(row.average_volume_20, 'average_volume_20')}</td><td>{fmt(row.latest_volume, 'latest_volume')}</td><td><button className="view-evidence" onClick={() => void openOpportunity(row)}>Details</button></td></tr>)}</tbody></table>{opportunities.items.length === 0 && <div className="research-empty">No fresh ordinary-share recommendation matches these exact filters. The application does not substitute older trading sessions or silently weaken filters.</div>}</div>
            <div className="research-pagination"><button disabled={opportunities.page <= 1} onClick={() => void loadOpportunities(opportunities.page - 1)}>Previous</button><span>Page {opportunities.page} of {opportunities.pages || 1}</span><button disabled={opportunities.page >= opportunities.pages} onClick={() => void loadOpportunities(opportunities.page + 1)}>Next</button></div>
            <p className="strong-buy-disclaimer">Backtested historical performance does not guarantee future results. This is research, not financial advice, and never places a broker order.</p>
          </section>}

          {tab === 'combinations' && <section className="research-panel">
            <div className="research-filter-grid"><label>Symbol<input value={symbolFilter} onChange={(e) => setSymbolFilter(e.target.value)} placeholder="NABIL" /></label><label>Sector<input value={sectorFilter} onChange={(e) => setSectorFilter(e.target.value)} placeholder="Commercial Bank" /></label><label>Min OOS trades<input type="number" min="0" value={minimumTrades} onChange={(e) => setMinimumTrades(Number(e.target.value) || 0)} /></label><label>Min robust score<input type="number" min="0" max="100" value={minimumScore} onChange={(e) => setMinimumScore(Number(e.target.value) || 0)} /></label><label>Min latest volume<input type="number" min="0" value={minimumVolume} onChange={(e) => setMinimumVolume(e.target.value)} /></label><label>Max listing age (days)<input type="number" min="1" value={maxAge} onChange={(e) => setMaxAge(e.target.value)} /></label><label>Instrument class<select value={includeNonEquities ? 'all' : 'ordinary'} onChange={(e) => setIncludeNonEquities(e.target.value === 'all')}><option value="ordinary">Ordinary shares only</option><option value="all">Explicitly include all</option></select></label><label>Rows<select value={results.page_size} onChange={(e) => setResults((current) => ({ ...current, page_size: Number(e.target.value) }))}><option>25</option><option>50</option><option>100</option></select></label></div>
            <div className="research-table-summary"><b>{results.total.toLocaleString()} matching simulations</b><span>Ranked by {sort.key.replaceAll('_', ' ')} {sort.direction}</span></div>
            <div className="research-table-wrap"><table><thead><tr>{columns.map(([key, label]) => <th key={key} onClick={() => toggleSort(key)}>{label}{sort.key === key ? (sort.direction === 'desc' ? ' ↓' : ' ↑') : ''}</th>)}</tr></thead><tbody>{results.items.map((row) => <tr key={row.result_id} className={row.recommendation_status === 'recommended' ? 'recommended' : ''}>{columns.map(([key]) => <td key={key}>{key === 'symbol' ? <div className="stock-chart-links"><a href={`/dashboard/backtest?run=${activeRun.run_id}&stock=${row.symbol}&result=${row.result_id}`}>{row.symbol}</a><NepseAlphaSymbolLink symbol={row.symbol}>Chart ↗</NepseAlphaSymbolLink></div> : key === 'robust_score' ? <span className={`score score-${Math.floor(Number(row[key] || 0) / 20)}`}>{fmt(row[key], key)}</span> : fmt(row[key], key)}</td>)}</tr>)}</tbody></table>{results.items.length === 0 && <div className="research-empty">No result matches these exact filters. Filters were not silently weakened.</div>}</div>
            <div className="research-pagination"><button disabled={results.page <= 1} onClick={() => void loadResults(results.page - 1)}>Previous</button><span>Page {results.page} of {results.pages || 1}</span><button disabled={results.page >= results.pages} onClick={() => void loadResults(results.page + 1)}>Next</button></div>
          </section>}

          {tab === 'portfolio' && <section className="research-panel"><div className="research-panel-title"><div><h3>Shared-capital strategy leaderboard</h3><p>One cash balance · max 10 positions · 10% per stock · 30% per sector · 5% reserve.</p></div></div><div className="portfolio-grid">{portfolios.map((item) => <article key={item.preset_id}><span>{item.preset_name}</span><strong className={item.summary.net_return_pct >= 0 ? 'positive' : 'negative'}>{fmt(item.summary.net_return_pct, 'return')}%</strong><dl><div><dt>Final equity</dt><dd>NPR {fmt(item.summary.final_equity, 'money')}</dd></div><div><dt>Drawdown</dt><dd>{fmt(item.summary.max_drawdown_pct, 'percent')}%</dd></div><div><dt>Accepted</dt><dd>{item.summary.accepted_signals}</dd></div><div><dt>Rejected</dt><dd>{item.summary.rejected_signals}</dd></div></dl></article>)}</div>{portfolios.length === 0 && <div className="research-empty">Portfolio results are finalized after the stock scan completes.</div>}</section>}

          {tab === 'ai' && <section className="research-panel"><div className="research-panel-title"><div><h3>Ask AI for the top 10</h3><p>AI creates validated filter JSON. The database never executes generated SQL and explicit filters are preserved.</p></div></div><div className="ai-query"><textarea rows={4} value={aiQuestion} onChange={(e) => setAiQuestion(e.target.value)} /><button disabled={aiBusy} onClick={() => void askAi()}>{aiBusy ? 'Validating…' : 'Generate query + top 10'}</button></div>{aiAnswer && <><pre>{aiAnswer.generated_query}</pre><p>{aiAnswer.explanation}</p>{aiAnswer.total_matches === 0 && <div className="research-alert">No exact matches. {aiAnswer.suggested_relaxations.join(' ')}</div>}<div className="research-table-wrap"><table><thead><tr>{columns.slice(0, 10).map(([key, label]) => <th key={key}>{label}</th>)}</tr></thead><tbody>{aiAnswer.items.map((row: ResultRow) => <tr key={row.result_id}>{columns.slice(0, 10).map(([key]) => <td key={key}>{fmt(row[key], key)}</td>)}</tr>)}</tbody></table></div></>}</section>}

          {tab === 'quality' && <section className="research-panel quality-grid"><article><b>Universe snapshot</b><strong>{activeRun.symbols_total}</strong><p>Instrument membership is frozen when the run starts.</p></article><article><b>Completed symbols</b><strong>{activeRun.symbols_completed}</strong><p>Each completion is checkpointed for restart recovery.</p></article><article><b>Ordinary-share enforcement</b><strong>{activeRun.configuration.ordinary_shares_only ? 'On' : 'Explicitly off'}</strong><p>Non-equities stay excluded at the API unless explicitly requested.</p></article><article><b>Validation split</b><strong>70 / 30</strong><p>The newest 30% of sessions are locked for out-of-sample metrics.</p></article></section>}
        </>}
      </main>
    </section>
    {detailBusy && <div className="detail-loading">Loading complete signal and trade evidence…</div>}
    {selectedOpportunity && <div className="strong-buy-overlay" role="dialog" aria-modal="true" aria-label="Backtest recommendation details"><div className="strong-buy-drawer">
      <header><div><span className={`signal-pill ${selectedOpportunity.best.current_signal_status}`}>{fmt(selectedOpportunity.best.current_signal_status, 'status')}</span><h2>{selectedOpportunity.best.symbol} · {selectedOpportunity.best.preset_name}</h2><p>Signal {selectedOpportunity.best.current_signal_date} · calculated from the latest completed daily session</p><NepseAlphaSymbolLink symbol={selectedOpportunity.best.symbol} className="drawer-nepse-chart">Open {selectedOpportunity.best.symbol} chart on NEPSE Alpha ↗</NepseAlphaSymbolLink></div><button aria-label="Close details" onClick={() => setSelectedOpportunity(null)}>×</button></header>
      <section className="detail-score-row"><article><span>Reliability score</span><strong>{fmt(selectedOpportunity.best.reliability_score, 'score')}</strong></article><article><span>Current technical score</span><strong>{fmt(selectedOpportunity.best.current_technical_score, 'score')}</strong></article><article><span>Current LTP</span><strong>NPR {fmt(selectedOpportunity.best.ltp, 'ltp')}</strong></article><article><span>Latest volume</span><strong>{fmt(selectedOpportunity.best.latest_volume, 'latest_volume')}</strong></article></section>
      <section className="detail-section strategy-price-plan"><h3>Strategy planning prices</h3><p>These zones use the saved strategy’s stop, target, and ATR volatility. They are planning levels; the backtest still models entry at the next available open.</p><div><article><span>Buy zone</span><strong>{selectedOpportunity.best.buy_zone_low ? `NPR ${fmt(selectedOpportunity.best.buy_zone_low, 'money')}–${fmt(selectedOpportunity.best.buy_zone_high, 'money')}` : 'No current entry signal'}</strong></article><article><span>Protective stop</span><strong>{selectedOpportunity.best.protective_stop ? `NPR ${fmt(selectedOpportunity.best.protective_stop, 'money')}` : '—'}</strong></article><article><span>Strategy sell zone</span><strong>{selectedOpportunity.best.sell_zone_low ? `NPR ${fmt(selectedOpportunity.best.sell_zone_low, 'money')}–${fmt(selectedOpportunity.best.sell_zone_high, 'money')}` : '—'}</strong></article><article><span>20-day average volume</span><strong>{fmt(selectedOpportunity.best.average_volume_20, 'average_volume_20')}</strong></article></div></section>
      <section className="detail-section"><h3>Latest strategy signal evidence</h3><p className="evidence-reason">{selectedOpportunity.best.current_evidence?.reason}</p><code>{selectedOpportunity.best.current_evidence?.strategy_condition}</code>{selectedOpportunity.best.current_evidence?.conditions_total > 0 && <p><b>{selectedOpportunity.best.current_evidence.conditions_passed}/{selectedOpportunity.best.current_evidence.conditions_total}</b> entry conditions currently pass ({fmt(selectedOpportunity.best.current_evidence.condition_progress_pct, 'percent')}%). “Near trigger” is readiness evidence, not a forecast.</p>}<div className="latest-values">{Object.entries(selectedOpportunity.best.current_evidence?.latest_values || {}).map(([key, value]) => <div key={key}><span>{key.replaceAll('_', ' ')}</span><b>{fmt(value, key)}</b></div>)}</div><h4>Condition checks</h4><div className="condition-checks">{(selectedOpportunity.best.current_evidence?.conditions || []).map((condition: any, index: number) => <div className={condition.matched ? 'passed' : 'failed'} key={`${condition.expression}-${index}`}><b>{condition.matched ? 'Passed' : 'Failed'}</b><span>{condition.expression}</span>{condition.message && <small>{condition.message}</small>}</div>)}</div></section>
      <section className="detail-section"><h3>How reliability was calculated</h3><div className="score-breakdown">{Object.entries(selectedOpportunity.best.current_evidence?.reliability?.components || {}).map(([key, value]) => <div key={key}><span>{key.replaceAll('_', ' ')}</span><b>+{fmt(value, key)}</b></div>)}</div>{(selectedOpportunity.best.current_evidence?.reliability?.penalties || []).map((penalty: any) => <p className="score-penalty" key={penalty.code}>−{penalty.points} · {penalty.code.replaceAll('_', ' ')}</p>)}</section>
      <section className="detail-section"><h3>Complete historical backtest summary</h3><div className="historical-summary">{Object.entries(selectedOpportunity.best.assumptions?.summary || {}).map(([key, value]) => <div key={key}><span>{key.replaceAll('_', ' ')}</span><b>{fmt(value, key)}</b></div>)}</div><div className="risk-config"><span>Stop loss {selectedOpportunity.best.assumptions?.stop_loss_pct}%</span><span>Take profit {selectedOpportunity.best.assumptions?.take_profit_pct}%</span><span>Min hold {selectedOpportunity.best.assumptions?.min_holding_days || 0} days</span><span>Max hold {selectedOpportunity.best.assumptions?.max_holding_days} days</span>{String(selectedOpportunity.best.assumptions?.charge_model || '').startsWith('nepse_equity') ? <><span>NEPSE tiered brokerage</span><span>SEBON 0.015% each side</span><span>DP NPR 25 per sale</span><span>CGT by holding period</span></> : <span>Legacy flat-fee result · rerun for official Nepal charges</span>}<span>Strategy {selectedOpportunity.best.assumptions?.preset_version}</span><span>{selectedOpportunity.best.assumptions?.period?.start} → {selectedOpportunity.best.assumptions?.period?.end}</span></div></section>
      <section className="detail-section execution-promotion"><h3>Use the same query for trading</h3><p>The stored query—not a rewritten approximation—creates a paper draft first. Live scheduling remains a separate action with current account, balance, holdings, and risk checks.</p><div><label>TMS client ID<input value={paperClientId} onChange={(e) => setPaperClientId(e.target.value)} placeholder="Client ID" /></label><button disabled={promotionBusy || !paperClientId.trim()} onClick={() => void promoteToPaper()}>{promotionBusy ? 'Creating paper draft…' : 'Promote exact query to paper'}</button><a href="/dashboard/schedule-order">Open Schedule Order</a></div>{promotionMessage && <strong>{promotionMessage}</strong>}</section>
      <section className="detail-section"><h3>Every simulated trade on the daily chart</h3><p>Green triangles are next-session simulated entries. Red diamonds are exits; each exit label shows the net NPR profit or loss after saved charges.</p><TradeCandlestickChart resultId={selectedOpportunity.best.result_id} symbol={selectedOpportunity.best.symbol} /></section>
      <section className="detail-section"><h3>Equity, profit and drawdown</h3><StrongBuyCharts trades={detailTrades.items} /></section>
      <section className="detail-section"><div className="trade-heading"><div><h3>Complete wins and losses</h3><p>{detailTrades.total} historical trades · net results include brokerage, SEBON, DP, CGT, and slippage</p></div><select value={tradeFilter} onChange={(e) => void filterDetailTrades(e.target.value)}><option value="all">All trades</option><option value="wins">Wins only</option><option value="losses">Losses only</option><option value="stop_loss">Stop-loss exits</option><option value="take_profit">Take-profit exits</option></select></div><div className="research-table-wrap detail-trades"><table><thead><tr>{['Result','Strategy','Signal','Entry date','Entry price','Exit date','Exit price','Qty','Held','Exit reason','Gross return','Net return','Brokerage','SEBON','DP','CGT','Total charges','P/L','Running equity','Drawdown'].map((item) => <th key={item}>{item}</th>)}</tr></thead><tbody>{detailTrades.items.map((trade) => <tr key={trade.trade_id}><td><span className={`trade-${trade.result}`}>{trade.result}</span></td><td>{selectedOpportunity.best.preset_name}</td><td>{trade.signal_date || '—'}</td><td>{trade.entry_date}</td><td>{fmt(trade.entry_price, 'money')}</td><td>{trade.exit_date}</td><td>{fmt(trade.exit_price, 'money')}</td><td>{trade.quantity}</td><td>{trade.holding_days}d</td><td>{fmt(trade.exit_reason, 'reason')}</td><td>{trade.gross_return_pct}%</td><td>{trade.net_return_pct}%</td><td>NPR {fmt(trade.broker_commission, 'money')}</td><td>NPR {fmt(trade.sebon_fee, 'money')}</td><td>NPR {fmt(trade.dp_charge, 'money')}</td><td>NPR {fmt(trade.capital_gains_tax, 'money')}<small>{fmt(trade.capital_gains_tax_rate_pct, 'percent')}%</small></td><td>NPR {fmt(trade.total_charges, 'money')}</td><td>NPR {fmt(trade.pnl, 'money')}</td><td>NPR {fmt(trade.running_equity, 'money')}</td><td>{trade.drawdown_after_trade_pct}%</td></tr>)}</tbody></table></div></section>
      {selectedOpportunity.alternatives?.length > 0 && <section className="detail-section"><h3>Other saved strategies for this stock</h3><div className="alternative-strategies">{selectedOpportunity.alternatives.map((item: any) => <span key={item.result_id}>{item.preset_name} · {signalLabel(item.current_signal_status)} · reliability {item.reliability_score}</span>)}</div></section>}
      <p className="strong-buy-disclaimer">Backtested historical performance does not guarantee future results. No broker order is placed or scheduled from this view.</p>
    </div></div>}
  </div>;
};

export default BacktestV2;
