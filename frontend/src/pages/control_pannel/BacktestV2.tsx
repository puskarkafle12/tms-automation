import React, { FormEvent, useEffect, useMemo, useRef, useState } from 'react';
import * as echarts from 'echarts/core';
import { BarChart, CandlestickChart, LineChart, ScatterChart } from 'echarts/charts';
import { AxisPointerComponent, DataZoomComponent, GridComponent, LegendComponent, TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import { fetchJson, getApiUrl } from '../../utils/api';
import NepseAlphaSymbolLink from '../../components/NepseAlphaSymbolLink';
import ColumnPickerModal from '../../components/ColumnPickerModal';
import CategoricalHeaderFilter, {
  isCategoricalColumn,
  uniqueCategoricalValues,
} from '../../components/table/CategoricalHeaderFilter';
import TradeLightweightChart, {
  type TradeChartCandle,
  type TradeChartSignal,
  type TradeChartProjection,
  type TradeChartTrade,
  type TradeChartZone,
  type TradeChartZoneSnapshot,
  type TradeChartRiskLevel,
} from '../../components/TradeLightweightChart';
import { nextBacktestSortRules } from './backtestSort';
import './BacktestV2.css';
import './BacktestV2Filters.css';
import './BacktestV2Strategy.css';
import './StrongBuy.css';
import './StockScopePicker.css';

echarts.use([BarChart, CandlestickChart, LineChart, ScatterChart, AxisPointerComponent, DataZoomComponent, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);

type Preset = {
  id: string; name: string; category: string; family: string; description: string;
  tier?: string; recommended_listing_age_days?: number;
};
type Run = {
  run_id: string; name: string; run_type?: string; status: string; progress_pct: number; symbols_completed: number;
  symbols_total: number; combinations_completed: number; current_symbol?: string; created_at?: string;
  started_at?: string | null;
  configuration: {
    start_date: string; end_date: string; preset_ids: string[]; ordinary_shares_only: boolean;
    history_mode?: 'all_available' | 'custom'; strategy_mode?: 'presets' | 'custom' | 'discovery';
    custom_query_text?: string; discovery_budget?: number; max_listing_age_days?: number | null;
  };
  error_summary?: string;
  pause_requested?: boolean;
  cancel_requested?: boolean;
  archived_at?: string | null;
  archive_expires_at?: string | null;
  archive_days_remaining?: number;
};
type IpoStrategySummary = {
  items: Array<{
    strategy_id: string; strategy_name: string; stocks_tested: number; stocks_with_trades: number;
    profitable_stocks: number; pooled_trades: number; pooled_wins: number; pooled_win_rate_pct: number;
    confidence_lower_bound_pct: number; evidence_score: number; confidence_tier: 'high' | 'moderate' | 'preliminary';
    tested_max_holding_days?: number | null; average_holding_days?: number | null;
    market_proxy_regimes: Record<'bullish' | 'bearish' | 'neutral', { trades: number; wins: number; win_rate_pct: number }>;
    first_30_days: { trades: number; wins: number; win_rate_pct: number };
    lifecycle_windows: Record<'0_30' | '31_60' | '61_90' | '91_180' | '181_365', { trades: number; wins: number; win_rate_pct: number }>;
    cumulative_first_trade_windows: Record<'30' | '60' | '90' | '180', {
      days: number; trades: number; wins: number; win_rate_pct: number; average_return_pct: number;
      stock_coverage_pct: number; confidence_lower_bound_pct: number; evidence_score: number;
    }>;
    best_first_trade_horizon?: '30' | '60' | '90' | '180' | null;
    best_lifecycle_window?: '0_30' | '31_60' | '61_90' | '91_180' | '181_365' | null;
    entry_occurrences: Record<'first' | 'second' | 'third', { trades: number; wins: number; win_rate_pct: number }>;
    exit_rule_id?: string | null; stop_loss_pct?: number | null; take_profit_pct?: number | null;
    trailing_stop_pct?: number | null; exit_reasons: Record<string, { trades: number; wins: number }>;
    cross_stock_qualified: boolean;
  }>;
  ipo_price_paths: Array<{
    symbol: string; stage: 'markup' | 'selloff' | 'base_or_recovery' | 'recovered';
    peak_session: number; peak_date: string; peak_normalized: number;
    trough_session: number; trough_date: string; trough_normalized: number;
    peak_to_trough_drawdown_pct: number; recovery_from_trough_pct: number;
    current_from_peak_pct: number; latest_normalized: number;
    points: Array<{ session: number; date: string; listing_age_days: number; normalized_close: number }>;
  }>;
  common_pattern: Array<{ session: number; median: number; p25: number; p75: number; stocks: number }>;
  minimum_stock_coverage: number; candidate_rule: string; qualification_rule: string; regime_method: string;
};
type IpoStrategyDetail = {
  strategy_id: string; strategy_name: string; description: string; condition: string;
  exit_rule_id?: string | null; stop_loss_pct?: number | null; take_profit_pct?: number | null;
  trailing_stop_pct?: number | null;
  stock_results: Array<{
    symbol: string; total_trades: number; wins: number; win_rate_pct: number;
    trades: Array<{
      sequence_no: number; signal_date?: string | null; entry_date?: string | null;
      entry_price?: number | null; exit_date?: string | null; exit_price?: number | null;
      holding_days?: number; exit_reason?: string; return_pct: number;
    }>;
  }>;
};
type ResultRow = Record<string, any> & { result_id: number; symbol: string; preset_name: string };
type ResultPage = {
  items: ResultRow[]; page: number; page_size: number; total: number; pages: number;
  cached_total?: number; trade_outcomes?: number; zero_trade_outcomes?: number;
  include_zero_trade_simulations?: boolean;
};
type ResultAdvancedFilter = { id: number; field: string; operator: string; value: string };
type ResultSort = { field: string; direction: 'asc' | 'desc' };
type Portfolio = { preset_id: string; preset_name: string; summary: Record<string, number>; allocation_config: Record<string, number> };
type Opportunity = ResultRow & { rank: number; recommendation_score: number; current_signal_status: string; signal_date: string; reliability_score: number; current_technical_score: number; wins: number; losses: number; loss_rate_pct: number; net_profit: number; ltp: number; latest_volume: number; average_volume_20: number; buy_zone_low?: number; buy_zone_high?: number; protective_stop?: number; sell_zone_low?: number; sell_zone_high?: number; legacy_cost_model: boolean; current_evidence: Record<string, any>; assumptions: Record<string, any> };
type OpportunitySort = { field: string; direction: 'asc' | 'desc' };
type OpportunityAdvancedFilter = { id: number; field: string; operator: string; value: string };
type OpportunityPage = { items: Opportunity[]; page: number; page_size: number; total: number; pages: number; sorts?: OpportunitySort[]; filters?: Array<Omit<OpportunityAdvancedFilter, 'id'>>; scope?: string; freshness?: { latest_completed_session?: string; status?: string; excluded_weekday?: string }; disclaimer: string };
type TradePage = { items: Array<Record<string, any>>; page: number; page_size: number; total: number; pages: number };
type ExecutionChartPayload = {
  symbol: string;
  candles: TradeChartCandle[];
  trades: TradeChartTrade[];
  signals: TradeChartSignal[];
  projection?: TradeChartProjection | null;
  zones?: TradeChartZone[];
  zone_history?: TradeChartZoneSnapshot[];
  risk_levels?: TradeChartRiskLevel[];
};

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
  MIN_HOLDING_DAYS 5
  MAX_HOLDING_DAYS 90
  POSITION_SIZE_PCT 100
  MAX_VOLUME_PARTICIPATION_PCT 10
  RISK_FREE_RATE_PCT 4
  DATA_SOURCE "auto"
}
RULE "Supertrend PPO Confirmation" FOR SYMBOL "NABIL" {
  WHEN technical_supertrend = "Bullish" AND technical_ppo_histogram > 0 AND technical_adx_14 >= 20
  ORDER PERCENT_OF_AVAILABLE_CASH 100
  EXECUTE ON EVERY MATCH
}`;
const RESULT_COLUMNS: Array<{ key: string; label: string; locked?: boolean }> = [
  { key: 'symbol', label: 'Symbol', locked: true },
  { key: 'preset_name', label: 'Strategy' },
  { key: 'current_signal_status', label: 'Signal' },
  { key: 'current_signal_date', label: 'Signal session' },
  { key: 'sector', label: 'Sector' },
  { key: 'robust_score', label: 'Robust' },
  { key: 'oos_return_pct', label: 'OOS return %' },
  { key: 'oos_expectancy_pct', label: 'OOS expectancy %' },
  { key: 'oos_trades', label: 'OOS trades' },
  { key: 'win_rate_pct', label: 'Win rate %' },
  { key: 'total_trades', label: 'Trades' },
  { key: 'max_drawdown_pct', label: 'Drawdown %' },
  { key: 'min_holding_days', label: 'Min hold' },
  { key: 'max_holding_days', label: 'Max hold' },
  { key: 'walk_forward_profitable_pct', label: 'Stable folds %' },
  { key: 'data_completeness_pct', label: 'Data %' },
  { key: 'latest_volume', label: 'Latest volume' },
  { key: 'recommendation_status', label: 'Status' },
];
const columns = RESULT_COLUMNS;
const DEFAULT_VISIBLE_RESULT_COLUMNS = [
  'symbol', 'win_rate_pct', 'current_signal_status', 'sector', 'total_trades', 'preset_name',
];
const BACKTEST_VISIBLE_COLUMNS_KEY = 'tms-backtest-v2-visible-columns-v2';
const BACKTEST_FILTER_HISTORY_KEY = 'tms-backtest-v2-filter-history-v1';
const resultColumnLabel = (key: string) => RESULT_COLUMNS.find((column) => column.key === key)?.label || key;
const formatScanDuration = (totalSeconds: number) => {
  const seconds = Math.max(0, Math.round(totalSeconds));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const rem = seconds % 60;
  if (minutes < 60) return rem ? `${minutes}m ${rem}s` : `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const remMinutes = minutes % 60;
  return remMinutes ? `${hours}h ${remMinutes}m` : `${hours}h`;
};
const estimateScanRemaining = (run: Run | null) => {
  if (!run) return { label: '—', detail: '' };
  const remainingStocks = Math.max(0, Number(run.symbols_total || 0) - Number(run.symbols_completed || 0));
  if (['completed', 'cancelled', 'failed'].includes(run.status)) {
    return { label: run.status === 'completed' ? 'Done' : 'Stopped', detail: '' };
  }
  if (run.status === 'paused' || run.pause_requested) {
    return { label: 'Paused', detail: remainingStocks ? `${remainingStocks} stocks left` : '' };
  }
  if (run.status === 'queued' || run.symbols_completed <= 0) {
    return { label: 'Estimating…', detail: 'Waiting for the first stock checkpoint' };
  }
  const startedMs = Date.parse(String(run.started_at || run.created_at || ''));
  if (!Number.isFinite(startedMs) || remainingStocks <= 0) {
    return { label: remainingStocks <= 0 ? 'Finishing…' : 'Estimating…', detail: '' };
  }
  const elapsedSec = Math.max(1, (Date.now() - startedMs) / 1000);
  const stocksPerSec = run.symbols_completed / elapsedSec;
  if (stocksPerSec <= 0) return { label: 'Estimating…', detail: '' };
  const etaSec = remainingStocks / stocksPerSec;
  return {
    label: `~${formatScanDuration(etaSec)} left`,
    detail: `${remainingStocks} stocks · ${formatScanDuration(elapsedSec)} elapsed`,
  };
};
const normalizeVisibleResultColumns = (keys: string[]) => {
  const known = new Set(RESULT_COLUMNS.map((column) => column.key));
  const ordered = keys.map(String).filter((key, index, all) => known.has(key) && all.indexOf(key) === index && key !== 'symbol');
  return ['symbol', ...ordered];
};
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
const resultFilterFields: Array<{ field: string; label: string; type: 'number' | 'text'; options?: Array<{ value: string; label: string }> }> = [
  { field: 'symbol', label: 'Symbol or company', type: 'text' },
  { field: 'sector', label: 'Sector', type: 'text' },
  { field: 'preset_name', label: 'Strategy name', type: 'text' },
  { field: 'preset_family', label: 'Strategy family', type: 'text' },
  { field: 'category', label: 'Strategy category', type: 'text' },
  { field: 'current_signal_status', label: 'Current signal', type: 'text', options: [
    { value: 'strong_buy', label: 'Strong buy today' }, { value: 'buy', label: 'Buy today' },
    { value: 'watch', label: 'Triggered · review' }, { value: 'near_trigger', label: 'Near trigger' },
    { value: 'no_signal', label: 'Historical leader' }, { value: 'stale', label: 'Historical · stale' },
  ] },
  { field: 'robust_score', label: 'Robust score', type: 'number' },
  { field: 'oos_trades', label: 'OOS trades', type: 'number' },
  { field: 'oos_return_pct', label: 'OOS return %', type: 'number' },
  { field: 'oos_expectancy_pct', label: 'OOS expectancy %', type: 'number' },
  { field: 'oos_sharpe_ratio', label: 'OOS Sharpe', type: 'number' },
  { field: 'win_rate_pct', label: 'Historical win rate %', type: 'number' },
  { field: 'total_trades', label: 'Historical trades', type: 'number' },
  { field: 'min_holding_days', label: 'Minimum holding days', type: 'number' },
  { field: 'max_holding_days', label: 'Maximum holding days', type: 'number' },
  { field: 'stop_loss_pct', label: 'Stop loss %', type: 'number' },
  { field: 'take_profit_pct', label: 'Take profit %', type: 'number' },
  { field: 'trailing_stop_pct', label: 'Trailing stop %', type: 'number' },
  { field: 'slippage_pct_each_side', label: 'Slippage each side %', type: 'number' },
  { field: 'net_return_pct', label: 'Net return %', type: 'number' },
  { field: 'profit_factor', label: 'Profit factor', type: 'number' },
  { field: 'max_drawdown_pct', label: 'Maximum drawdown %', type: 'number' },
  { field: 'walk_forward_profitable_pct', label: 'Profitable walk-forward folds %', type: 'number' },
  { field: 'data_completeness_pct', label: 'Data completeness %', type: 'number' },
  { field: 'liquidity_score', label: 'Liquidity score', type: 'number' },
  { field: 'latest_volume', label: 'Latest volume', type: 'number' },
  { field: 'average_turnover_20', label: '20-session average turnover', type: 'number' },
  { field: 'listing_age_days', label: 'Listing age (days)', type: 'number' },
  { field: 'recommendation_status', label: 'Validation status', type: 'text', options: [
    { value: 'recommended', label: 'Recommended' }, { value: 'watch', label: 'Watch' },
    { value: 'insufficient_sample', label: 'Insufficient sample' },
  ] },
  { field: 'technical_signal', label: 'Latest technical signal', type: 'text', options: [
    { value: 'Strong Buy', label: 'Strong Buy' }, { value: 'Buy', label: 'Buy' },
    { value: 'Neutral', label: 'Neutral' }, { value: 'Sell', label: 'Sell' }, { value: 'Strong Sell', label: 'Strong Sell' },
  ] },
];
const aiBacktestPresets = [
  'Find the 10 most reliable ordinary shares with positive OOS expectancy, at least 15 OOS trades, positive OOS return, and drawdown below 25%.',
  'Find liquid ordinary shares where robust score is at least 65, OOS Sharpe is positive, and latest volume is above 10,000. Rank by robust score.',
  'Show the best low-drawdown strategies across all cached stocks with at least 20 historical trades and profitable walk-forward stability.',
  'Which strategy family performs most consistently across commercial banks? Return the strongest 10 stock-strategy combinations.',
  'Find newer ordinary shares with listing age below 1,825 days, at least 10 OOS trades, positive expectancy, and high data completeness.',
];
const defaultOpportunityFilterOperator = (field: typeof opportunityFilterFields[number]) => field.defaultOperator || (field.type === 'number' ? 'gte' : 'contains');
const defaultOpportunityFilters = { minimum_trades: '5', minimum_win_rate: '', minimum_confidence: '', minimum_sharpe: '', minimum_profit_factor: '', maximum_drawdown: '', minimum_return: '', minimum_volume: '', category: '', current_signal: 'buy' };
const optionalNumber = (value: string) => value.trim() === '' ? null : Number(value);
const runStrategyCount = (run: Run) => {
  const mode = run.configuration?.strategy_mode || 'presets';
  if (mode === 'custom') return 1;
  if (mode === 'discovery') return Number(run.configuration?.discovery_budget || 0);
  return Array.isArray(run.configuration?.preset_ids) ? run.configuration.preset_ids.length : 0;
};
const runScansDone = (run: Run) => Math.max(
  Number(run.combinations_completed || 0),
  Number(run.symbols_completed || 0) * runStrategyCount(run),
);
const isIpoRun = (run: Run | null) => Boolean(
  run && (
    run.run_type === 'ipo_research'
    || (run.configuration?.preset_ids?.length && run.configuration.preset_ids.every((id) => id.startsWith('ipo_')))
  ),
);
const defaultTradesFilter = (ipo: boolean): ResultAdvancedFilter => ({
  id: 1, field: 'total_trades', operator: 'gte', value: ipo ? '1' : '20',
});
const needsIpoTradeFloor = (filters: ResultAdvancedFilter[]) => {
  if (!filters.length) return true;
  const tradeFilter = filters.find((item) => item.field === 'total_trades' && item.operator === 'gte');
  if (!tradeFilter) return true;
  const minimum = Number(tradeFilter.value);
  return !Number.isFinite(minimum) || minimum < 1 || minimum >= 20;
};
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
    chart.setOption({ animation: false, tooltip: { trigger: 'axis' }, legend: { data: ['Equity', 'Trade P/L', 'Drawdown %'], selected: { 'Drawdown %': false } }, grid: { left: 58, right: 45, top: 45, bottom: 50 }, xAxis: { type: 'category', data: labels, axisLabel: { hideOverlap: true } }, yAxis: [{ type: 'value', name: 'NPR' }, { type: 'value', name: 'DD %', show: false }], dataZoom: [{ type: 'inside' }, { type: 'slider', height: 18 }], series: [{ name: 'Equity', type: 'line', data: equity, showSymbol: false, lineStyle: { color: '#176da6', width: 2 } }, { name: 'Trade P/L', type: 'bar', data: profits, itemStyle: { color: (params: any) => Number(params.value) >= 0 ? '#1a9b5f' : '#d44848' } }, { name: 'Drawdown %', type: 'line', yAxisIndex: 1, data: drawdown, showSymbol: false, lineStyle: { color: '#e0932d' }, areaStyle: { color: 'rgba(224,147,45,.12)' } }] });
    const onLegendSelection = (event: any) => {
      chart.setOption({ yAxis: [{}, { show: Boolean(event.selected?.['Drawdown %']) }] });
    };
    chart.on('legendselectchanged', onLegendSelection);
    const observer = new ResizeObserver(() => chart.resize()); observer.observe(ref.current);
    return () => { observer.disconnect(); chart.off('legendselectchanged', onLegendSelection); chart.dispose(); };
  }, [trades]);
  return <div className="strong-buy-chart" ref={ref} aria-label="Equity, trade profit and drawdown chart" />;
};

const IpoResearchCharts: React.FC<{ summary: IpoStrategySummary }> = ({ summary }) => {
  const patternRef = useRef<HTMLDivElement | null>(null);
  const strategyRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!patternRef.current) return undefined;
    const chart = echarts.init(patternRef.current);
    const common = summary.common_pattern || [];
    chart.setOption({
      animation: false,
      tooltip: { trigger: 'axis' },
      legend: { data: ['Cross-stock median', '25th percentile', '75th percentile'], top: 4 },
      grid: { left: 55, right: 24, top: 48, bottom: 52 },
      xAxis: { type: 'value', name: 'Trading sessions since first data', min: 0 },
      yAxis: { type: 'value', name: 'Normalized price', axisLabel: { formatter: '{value}' } },
      dataZoom: [{ type: 'inside' }, { type: 'slider', height: 18 }],
      series: [
        ...(summary.ipo_price_paths || []).map((path) => ({
          name: path.symbol, type: 'line', data: path.points.map((point) => [point.session, point.normalized_close]),
          showSymbol: false, silent: true, lineStyle: { width: 1, opacity: .16, color: '#6f88a1' },
          emphasis: { disabled: true },
        })),
        { name: '25th percentile', type: 'line', data: common.map((point) => [point.session, point.p25]), showSymbol: false, lineStyle: { color: '#d18b3d', type: 'dashed', width: 1.5 } },
        { name: '75th percentile', type: 'line', data: common.map((point) => [point.session, point.p75]), showSymbol: false, lineStyle: { color: '#d18b3d', type: 'dashed', width: 1.5 } },
        { name: 'Cross-stock median', type: 'line', data: common.map((point) => [point.session, point.median]), showSymbol: false, lineStyle: { color: '#087f6b', width: 3 }, z: 5 },
      ],
    });
    const observer = new ResizeObserver(() => chart.resize()); observer.observe(patternRef.current);
    return () => { observer.disconnect(); chart.dispose(); };
  }, [summary.common_pattern, summary.ipo_price_paths]);
  useEffect(() => {
    if (!strategyRef.current) return undefined;
    const chart = echarts.init(strategyRef.current);
    const ranked = [...(summary.items || [])].sort((a, b) => b.pooled_win_rate_pct - a.pooled_win_rate_pct || b.pooled_trades - a.pooled_trades);
    chart.setOption({
      animation: false,
      tooltip: { trigger: 'axis' },
      legend: { data: ['Pooled win rate', 'Trades', '80% research target'], top: 4 },
      grid: { left: 55, right: 55, top: 48, bottom: 150 },
      xAxis: { type: 'category', data: ranked.map((item) => item.strategy_name), axisLabel: { interval: 0, rotate: 48, fontSize: 9 } },
      yAxis: [{ type: 'value', name: 'Win %', min: 0, max: 100 }, { type: 'value', name: 'Trades', min: 0 }],
      dataZoom: [{ type: 'inside' }, { type: 'slider', height: 18, bottom: 8 }],
      series: [
        { name: 'Pooled win rate', type: 'bar', data: ranked.map((item) => ({ value: item.pooled_win_rate_pct, itemStyle: { color: item.cross_stock_qualified ? '#16866f' : '#91a5b7' } })) },
        { name: 'Trades', type: 'line', yAxisIndex: 1, data: ranked.map((item) => item.pooled_trades), showSymbol: true, lineStyle: { color: '#345f8c' } },
        { name: '80% research target', type: 'line', data: ranked.map(() => 80), showSymbol: false, silent: true, lineStyle: { color: '#d45454', type: 'dashed', width: 1.5 } },
      ],
    });
    const observer = new ResizeObserver(() => chart.resize()); observer.observe(strategyRef.current);
    return () => { observer.disconnect(); chart.dispose(); };
  }, [summary.items]);
  return <div className="ipo-research-charts">
    <article><h3>All IPO price paths</h3><p>Each stock starts at 100. Thin lines are individual IPOs; the bold line is their median.</p><div ref={patternRef} aria-label="Normalized price paths for every IPO stock" /></article>
    <article><h3>Strategy evidence graph</h3><p>Win rate is shown with its pooled trade count. The 80% line is a research target, not a pass created by weakening sample requirements.</p><div ref={strategyRef} aria-label="IPO strategy win rates and pooled trade counts" /></article>
  </div>;
};

const IpoStockPathGrid: React.FC<{ paths: IpoStrategySummary['ipo_price_paths'] }> = ({ paths }) => {
  const [stage, setStage] = useState<'all' | IpoStrategySummary['ipo_price_paths'][number]['stage']>('all');
  const visible = stage === 'all' ? paths : paths.filter((path) => path.stage === stage);
  const stageLabel = (value: string) => ({
    markup: 'Markup / new high', selloff: 'Near post-peak low',
    base_or_recovery: 'Base / recovery', recovered: 'Recovered near peak',
  }[value] || value);
  return <section className="research-panel ipo-stock-paths">
    <div className="ipo-stock-path-heading"><div><h3>Every IPO lifecycle chart</h3><p>Price is normalized to 100 at the first stored session. Peak and post-peak trough are marked without using future data in any trade signal.</p></div><label>Lifecycle now<select value={stage} onChange={(event) => setStage(event.target.value as typeof stage)}><option value="all">All stages</option><option value="markup">Markup / new high</option><option value="selloff">Near post-peak low</option><option value="base_or_recovery">Base / recovery</option><option value="recovered">Recovered near peak</option></select></label></div>
    <div className="ipo-stock-path-grid">{visible.map((path) => {
      const width = 260; const height = 92; const pad = 7;
      const values = path.points.map((point) => point.normalized_close);
      const min = Math.min(...values); const max = Math.max(...values);
      const x = (session: number) => pad + session / Math.max(1, path.points[path.points.length - 1].session) * (width - pad * 2);
      const y = (value: number) => height - pad - (value - min) / Math.max(1, max - min) * (height - pad * 2);
      const polyline = path.points.map((point) => `${x(point.session).toFixed(1)},${y(point.normalized_close).toFixed(1)}`).join(' ');
      return <article key={path.symbol}>
        <header><b>{path.symbol}</b><span className={`ipo-stage ${path.stage}`}>{stageLabel(path.stage)}</span></header>
        <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${path.symbol} normalized IPO lifecycle`}>
          <line x1={pad} x2={width - pad} y1={y(100)} y2={y(100)} className="ipo-baseline" />
          <polyline points={polyline} className="ipo-path-line" />
          <circle cx={x(path.peak_session)} cy={y(path.peak_normalized)} r="3" className="ipo-peak-point"><title>Peak {path.peak_date}</title></circle>
          <circle cx={x(path.trough_session)} cy={y(path.trough_normalized)} r="3" className="ipo-trough-point"><title>Post-peak trough {path.trough_date}</title></circle>
        </svg>
        <dl><div><dt>Peak → trough</dt><dd>{path.peak_to_trough_drawdown_pct.toFixed(2)}%</dd></div><div><dt>Trough recovery</dt><dd>+{path.recovery_from_trough_pct.toFixed(2)}%</dd></div><div><dt>Current vs peak</dt><dd>{path.current_from_peak_pct.toFixed(2)}%</dd></div></dl>
      </article>;
    })}</div>
    {visible.length === 0 && <div className="research-empty">No IPO currently matches this lifecycle stage.</div>}
  </section>;
};

const IpoStrategyTradeGallery: React.FC<{
  detail: IpoStrategyDetail;
  paths: IpoStrategySummary['ipo_price_paths'];
  horizon: 30 | 60 | 90 | 180;
}> = ({ detail, paths, horizon }) => {
  const cards = paths.map((path) => {
    const result = detail.stock_results.find((item) => item.symbol === path.symbol);
    const firstTrade = result?.trades.find((trade) => {
      const signalDate = trade.signal_date || trade.entry_date;
      const point = path.points.find((candidate) => candidate.date === signalDate);
      return point && point.listing_age_days <= horizon;
    });
    return { path, result, trade: firstTrade };
  }).filter((item) => item.trade);
  return <section className="ipo-trade-gallery">
    <div className="ipo-trade-gallery-heading"><div><h4>First qualifying trade on every covered IPO</h4><p>Buy and sell markers are the saved backtest dates. Prices are normalized only to make different stocks comparable; the labels retain exact execution prices when available.</p></div><strong>{cards.length}/{paths.length}<small>stocks traded by day {horizon}</small></strong></div>
    <div className="ipo-trade-chart-grid">{cards.map(({ path, trade }) => {
      const width = 300; const height = 126; const padX = 12; const padY = 17;
      const visiblePoints = path.points.filter((point) => point.listing_age_days <= horizon);
      const entryDate = trade!.entry_date || trade!.signal_date || '';
      const exitDate = trade!.exit_date || '';
      const entryPoint = path.points.find((point) => point.date === entryDate)
        || path.points.find((point) => point.date === trade!.signal_date);
      const exitPoint = path.points.find((point) => point.date === exitDate);
      const values = visiblePoints.map((point) => point.normalized_close);
      if (entryPoint) values.push(entryPoint.normalized_close);
      if (exitPoint) values.push(exitPoint.normalized_close);
      const min = Math.min(...values); const max = Math.max(...values);
      const x = (age: number) => padX + age / horizon * (width - padX * 2);
      const y = (value: number) => height - padY - (value - min) / Math.max(1, max - min) * (height - padY * 2);
      const polyline = visiblePoints.map((point) => `${x(point.listing_age_days).toFixed(1)},${y(point.normalized_close).toFixed(1)}`).join(' ');
      const won = Number(trade!.return_pct) > 0;
      return <article key={path.symbol}>
        <header><b>{path.symbol}</b><span className={won ? 'ipo-trade-win' : 'ipo-trade-loss'}>{won ? 'WIN' : 'LOSS'} {Number(trade!.return_pct) >= 0 ? '+' : ''}{Number(trade!.return_pct).toFixed(2)}%</span></header>
        <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${path.symbol} first ${detail.strategy_name} trade within ${horizon} days`}>
          <polyline points={polyline} className="ipo-path-line" />
          {entryPoint && <g><line x1={x(entryPoint.listing_age_days)} x2={x(entryPoint.listing_age_days)} y1={padY} y2={height - padY} className="ipo-entry-guide" /><circle cx={x(entryPoint.listing_age_days)} cy={y(entryPoint.normalized_close)} r="4" className="ipo-entry-point" /><text x={x(entryPoint.listing_age_days) + 5} y={Math.max(11, y(entryPoint.normalized_close) - 6)} className="ipo-entry-label">BUY</text></g>}
          {exitPoint && <g><line x1={x(exitPoint.listing_age_days)} x2={x(exitPoint.listing_age_days)} y1={padY} y2={height - padY} className="ipo-exit-guide" /><circle cx={x(exitPoint.listing_age_days)} cy={y(exitPoint.normalized_close)} r="4" className="ipo-exit-point" /><text x={Math.min(width - 32, x(exitPoint.listing_age_days) + 5)} y={Math.max(11, y(exitPoint.normalized_close) - 6)} className="ipo-exit-label">SELL</text></g>}
        </svg>
        <dl>
          <div><dt>Buy</dt><dd>{trade!.entry_price != null ? `NPR ${trade!.entry_price.toLocaleString()}` : entryDate} <small>{entryDate}</small></dd></div>
          <div><dt>Sell</dt><dd>{trade!.exit_price != null ? `NPR ${trade!.exit_price.toLocaleString()}` : exitDate} <small>{exitDate}</small></dd></div>
          <div><dt>Held / exit</dt><dd>{trade!.holding_days ?? '—'} sessions · {fmt(trade!.exit_reason, 'exit_reason')}</dd></div>
        </dl>
      </article>;
    })}</div>
    {cards.length === 0 && <div className="research-empty">This strategy did not produce a first eligible trade inside the selected IPO-age window.</div>}
  </section>;
};

const IpoStrategyCards: React.FC<{ summary: IpoStrategySummary; runId: string }> = ({ summary, runId }) => {
  const lifecycleLabels = { '0_30': '0–30d', '31_60': '31–60d', '61_90': '61–90d', '91_180': '91–180d', '181_365': '181–365d' };
  const leaders = summary.items.filter((item) => item.cross_stock_qualified).slice(0, 3);
  const [horizon, setHorizon] = useState<30 | 60 | 90 | 180>(30);
  const horizonKey = String(horizon) as '30' | '60' | '90' | '180';
  const commonLeaders = useMemo(() => [...summary.items]
    .filter((item) => item.cumulative_first_trade_windows?.[horizonKey]?.trades >= summary.minimum_stock_coverage)
    .sort((left, right) => (
      right.cumulative_first_trade_windows[horizonKey].evidence_score
      - left.cumulative_first_trade_windows[horizonKey].evidence_score
      || right.cumulative_first_trade_windows[horizonKey].trades
      - left.cumulative_first_trade_windows[horizonKey].trades
    )), [summary.items, summary.minimum_stock_coverage, horizonKey]);
  const [selectedStrategyId, setSelectedStrategyId] = useState('');
  const [detail, setDetail] = useState<IpoStrategyDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  useEffect(() => {
    const leader = commonLeaders[0];
    if (leader && !commonLeaders.some((item) => item.strategy_id === selectedStrategyId)) {
      setSelectedStrategyId(leader.strategy_id);
    }
  }, [commonLeaders, selectedStrategyId]);
  useEffect(() => {
    if (!selectedStrategyId) { setDetail(null); return; }
    setDetailLoading(true);
    void fetchJson<IpoStrategyDetail>(`/api/backtests/v2/runs/${runId}/ipo-strategy-summary/${encodeURIComponent(selectedStrategyId)}`).then((response) => {
      setDetail(response.ok ? response.data : null);
      setDetailLoading(false);
    });
  }, [runId, selectedStrategyId]);
  const selected = commonLeaders.find((item) => item.strategy_id === selectedStrategyId);
  const selectedWindow = selected?.cumulative_first_trade_windows?.[horizonKey];
  const selectedHasStrongEvidence = Boolean(
    selectedWindow && selectedWindow.trades >= 15
    && selectedWindow.confidence_lower_bound_pct >= 60
    && selectedWindow.stock_coverage_pct >= 25,
  );
  return <section className="research-panel ipo-strategy-summary">
    <section className="ipo-common-trade-study">
      <div className="ipo-common-study-head"><div><span>One common IPO trade study</span><h3>Which first trade worked across the most new listings?</h3><p>Only the first qualifying trade per stock is counted. Select how far after listing the trade was allowed to appear.</p></div><div className="ipo-horizon-switch">{([30, 60, 90, 180] as const).map((days) => <button type="button" className={horizon === days ? 'active' : ''} key={days} onClick={() => setHorizon(days)}>First {days} days</button>)}</div></div>
      {selected && selectedWindow && <div className="ipo-common-winner">
        <div><span>{selectedHasStrongEvidence ? 'Confidence-adjusted winner' : 'Best available · preliminary evidence'} · first {horizon} days</span><h4>{selected.strategy_name}</h4><p>{selectedWindow.wins}/{selectedWindow.trades} first trades won across {selectedWindow.trades}/{selected.stocks_tested} IPOs. {selectedHasStrongEvidence ? 'The sample meets the cross-stock confidence threshold.' : 'The sample does not yet support a high-confidence common strategy.'}</p></div>
        <dl><div><dt>Win rate</dt><dd>{selectedWindow.win_rate_pct.toFixed(2)}%</dd></div><div><dt>Conservative floor</dt><dd>{selectedWindow.confidence_lower_bound_pct.toFixed(2)}%</dd></div><div><dt>Average net return</dt><dd>{selectedWindow.average_return_pct >= 0 ? '+' : ''}{selectedWindow.average_return_pct.toFixed(2)}%</dd></div><div><dt>Coverage</dt><dd>{selectedWindow.stock_coverage_pct.toFixed(2)}%</dd></div></dl>
      </div>}
      <div className="ipo-common-ranking">{commonLeaders.slice(0, 8).map((item, index) => {
        const stats = item.cumulative_first_trade_windows[horizonKey];
        return <button type="button" className={item.strategy_id === selectedStrategyId ? 'active' : ''} key={item.strategy_id} onClick={() => setSelectedStrategyId(item.strategy_id)}><span>#{index + 1}</span><b>{item.strategy_name}</b><strong>{stats.win_rate_pct.toFixed(2)}%</strong><small>{stats.wins}/{stats.trades} · {stats.confidence_lower_bound_pct.toFixed(2)}% floor · {stats.stock_coverage_pct.toFixed(0)}% coverage</small></button>;
      })}</div>
      {!commonLeaders.length && <div className="research-empty">No strategy has first-trade evidence from {summary.minimum_stock_coverage} IPO stocks yet. This is not a zero score: the prior-session red-candle gate has not produced enough valid entries in the completed checkpoints.</div>}
      {detailLoading && <div className="research-empty">Loading saved buy and sell evidence…</div>}
      {detail && !detailLoading && <><div className="ipo-selected-method"><div><span>Buy rule</span><p>{detail.description}</p></div><div><span>Sell and protection</span><p>{[detail.exit_rule_id?.replaceAll('_', ' '), detail.stop_loss_pct != null ? `${detail.stop_loss_pct}% stop` : null, detail.take_profit_pct != null ? `${detail.take_profit_pct}% target` : null, detail.trailing_stop_pct != null ? `${detail.trailing_stop_pct}% trail` : null].filter(Boolean).join(' · ') || 'Saved strategy exit'}</p></div></div><IpoStrategyTradeGallery detail={detail} paths={summary.ipo_price_paths} horizon={horizon} /></>}
    </section>
    <div><h3>Common cross-stock strategy ranking</h3><p>{summary.candidate_rule} {summary.qualification_rule}</p><small>{summary.regime_method}</small></div>
    <div className="ipo-evidence-leaders">{leaders.map((item, index) => <article key={item.strategy_id}><span>#{index + 1} confidence-adjusted</span><b>{item.strategy_name}</b><strong>{item.evidence_score.toFixed(2)}</strong><small>{item.confidence_tier} evidence · {item.confidence_lower_bound_pct.toFixed(2)}% conservative win-rate floor · {item.pooled_trades} trades</small></article>)}</div>
    <div className="ipo-strategy-summary-grid">{summary.items.map((item) => {
      const bullish = item.market_proxy_regimes?.bullish;
      const bearish = item.market_proxy_regimes?.bearish;
      const exitParts = [
        item.exit_rule_id ? item.exit_rule_id.replaceAll('_', ' ') : null,
        item.stop_loss_pct != null ? `${item.stop_loss_pct}% stop` : null,
        item.take_profit_pct != null ? `${item.take_profit_pct}% target` : null,
        item.trailing_stop_pct != null ? `${item.trailing_stop_pct}% trail` : null,
      ].filter(Boolean);
      return <article key={item.strategy_id} className={item.cross_stock_qualified ? 'qualified' : ''}>
        <span>{item.cross_stock_qualified ? 'Cross-stock qualified' : 'Candidate evidence'}</span><b>{item.strategy_name}</b>
        <dl>
          <div><dt>Evidence confidence</dt><dd>{item.evidence_score.toFixed(2)} · {item.confidence_tier}</dd></div>
          <div><dt>Conservative win floor</dt><dd>{item.confidence_lower_bound_pct.toFixed(2)}%</dd></div>
          <div><dt>Pooled win rate</dt><dd>{item.pooled_win_rate_pct.toFixed(2)}%</dd></div>
          <div><dt>Wins / trades</dt><dd>{item.pooled_wins}/{item.pooled_trades}</dd></div>
          <div><dt>Stock coverage</dt><dd>{item.stocks_with_trades}/{item.stocks_tested}</dd></div>
          {(['first', 'second', 'third'] as const).map((occurrence, index) => {
            const stats = item.entry_occurrences?.[occurrence];
            return <div key={occurrence}><dt>{index + 1}{index === 0 ? 'st' : index === 1 ? 'nd' : 'rd'} eligible trade</dt><dd>{stats?.trades ? `${stats.win_rate_pct.toFixed(2)}% · ${stats.trades}` : 'No trades'}</dd></div>;
          })}
          <div><dt>Most repeatable listing age</dt><dd>{item.best_lifecycle_window ? lifecycleLabels[item.best_lifecycle_window] : 'No trades'}</dd></div>
          <div><dt>Best first-trade horizon</dt><dd>{item.best_first_trade_horizon ? `First ${item.best_first_trade_horizon} days` : 'No trades'}</dd></div>
          {Object.entries(item.lifecycle_windows || {}).map(([window, stats]) => <div key={window}><dt>Listed {lifecycleLabels[window as keyof typeof lifecycleLabels]}</dt><dd>{stats.trades ? `${stats.win_rate_pct.toFixed(2)}% · ${stats.trades}` : 'No trades'}</dd></div>)}
          <div><dt>Bull market proxy</dt><dd>{bullish?.trades ? `${bullish.win_rate_pct.toFixed(2)}% · ${bullish.trades}` : 'No trades'}</dd></div>
          <div><dt>Bear market proxy</dt><dd>{bearish?.trades ? `${bearish.win_rate_pct.toFixed(2)}% · ${bearish.trades}` : 'No trades'}</dd></div>
          <div><dt>Hold observed / tested</dt><dd>{item.average_holding_days != null ? `${item.average_holding_days}d` : '—'} / {item.tested_max_holding_days ? `${item.tested_max_holding_days}d` : '—'}</dd></div>
          <div><dt>Sell protection</dt><dd>{exitParts.join(' · ') || 'Saved strategy exit'}</dd></div>
        </dl>
      </article>;
    })}</div>
  </section>;
};

const EMPTY_CANDLES: TradeChartCandle[] = [];
const EMPTY_CHART_TRADES: TradeChartTrade[] = [];
const EMPTY_CHART_SIGNALS: TradeChartSignal[] = [];

const TradeCandlestickChart: React.FC<{ resultId: number; symbol: string; cacheKey?: string }> = ({ resultId, symbol, cacheKey }) => {
  const [payload, setPayload] = useState<ExecutionChartPayload | null>(null);
  const [chartError, setChartError] = useState('');
  const [showZones, setShowZones] = useState(false);
  useEffect(() => {
    setPayload(null); setChartError('');
    const apiResultId = cacheKey ? 0 : resultId;
    const cacheQuery = cacheKey ? `?cache_key=${encodeURIComponent(cacheKey)}` : '';
    void fetchJson<ExecutionChartPayload>(`/api/backtests/v2/results/${apiResultId}/chart${cacheQuery}`).then((response) => {
      if (response.ok) setPayload(response.data); else setChartError(response.error || 'Could not load price history.');
    });
  }, [resultId, cacheKey]);
  return (
    <div className="backtest-trade-chart">
      <div className="backtest-chart-layer-controls">
        <label className="backtest-chart-layer-toggle">
          <input type="checkbox" checked={showZones} onChange={(event) => setShowZones(event.target.checked)} />
          <span>Support &amp; resistance zones</span>
          <small>{payload?.zone_history?.some((snapshot) => snapshot.zones.length) ? 'One prominent support + resistance' : 'No confirmed zones'}</small>
        </label>
        {!!payload?.risk_levels?.length && (
          <div className="backtest-chart-risk-legend" aria-label="Risk-level legend">
            <span className="buy">Buy signal</span>
            <span className="stop">Initial stop</span>
            {payload.risk_levels.some((level) => level.kind === 'trailing_stop') && <span className="trailing">Trailing stop</span>}
            <span className="target">Strategy sell zone</span>
          </div>
        )}
      </div>
      <TradeLightweightChart
        symbol={symbol}
        candles={payload?.candles || EMPTY_CANDLES}
        trades={payload?.trades || EMPTY_CHART_TRADES}
        signals={payload?.signals || EMPTY_CHART_SIGNALS}
        projection={payload?.projection}
        zones={payload?.zones}
        zoneHistory={payload?.zone_history}
        showZones={showZones}
        riskLevels={payload?.risk_levels}
        loading={!payload && !chartError}
        error={chartError}
        emptyMessage="No cached OHLCV candles are available for this result period."
        loadingMessage="Loading the exact daily price and trade history…"
      />
      {payload?.projection?.disclaimer && <p className="chart-projection-disclaimer">{payload.projection.disclaimer}</p>}
    </div>
  );
};

const BacktestV2: React.FC = () => {
  const params = useMemo(() => new URLSearchParams(window.location.search), []);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [runs, setRuns] = useState<Run[]>([]);
  const [ipoRuns, setIpoRuns] = useState<Run[]>([]);
  const [ipoStrategySummary, setIpoStrategySummary] = useState<IpoStrategySummary | null>(null);
  const [activeRun, setActiveRun] = useState<Run | null>(null);
  const [name, setName] = useState('Full NEPSE robustness scan');
  const [historyMode, setHistoryMode] = useState<'all_available' | 'custom'>('all_available');
  const [startDate, setStartDate] = useState(defaultStart);
  const [endDate, setEndDate] = useState(today);
  const [ordinaryOnly, setOrdinaryOnly] = useState(true);
  const [maxListingAgeDays, setMaxListingAgeDays] = useState('');
  const [minHoldingDays, setMinHoldingDays] = useState('5');
  const [maxHoldingDays, setMaxHoldingDays] = useState('90');
  const [ipoResearchMode, setIpoResearchMode] = useState(false);
  const [strategyMode, setStrategyMode] = useState<'presets' | 'custom' | 'discovery'>('presets');
  const [discoveryBudget, setDiscoveryBudget] = useState('1000');
  const [customQuery, setCustomQuery] = useState(defaultCustomQuery);
  const [copyStatus, setCopyStatus] = useState('');
  const [creating, setCreating] = useState(false);
  const [runControlBusy, setRunControlBusy] = useState<'pause' | 'resume' | 'cancel' | 'retry' | null>(null);
  const [runControlMessage, setRunControlMessage] = useState('');
  const [workspaceRefreshBusy, setWorkspaceRefreshBusy] = useState(false);
  const [filteredRefreshBusy, setFilteredRefreshBusy] = useState(false);
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [progressTick, setProgressTick] = useState(0);
  const [archivedRuns, setArchivedRuns] = useState<Run[]>([]);
  const [archiveRetentionDays, setArchiveRetentionDays] = useState(30);
  const [archiveBusyId, setArchiveBusyId] = useState<string | null>(null);
  const [archiveMessage, setArchiveMessage] = useState('');
  const [uniqueConfigurationTotal, setUniqueConfigurationTotal] = useState(0);
  const [runScope, setRunScope] = useState<'all' | 'single'>('all');
  const [stockSearch, setStockSearch] = useState('');
  const [selectedStock, setSelectedStock] = useState<{ symbol: string; company_name: string; sector?: string } | null>(null);
  const [stockSuggestions, setStockSuggestions] = useState<Array<{ symbol: string; company_name: string; sector?: string }>>([]);
  const [error, setError] = useState('');
  const [showHowItWorks, setShowHowItWorks] = useState(false);
  const [columnPickerOpen, setColumnPickerOpen] = useState(false);
  const preferenceUserId = localStorage.getItem('userId') || 'local';
  const [savedResultFilterState] = useState<any>(() => {
    try {
      return JSON.parse(localStorage.getItem(`${BACKTEST_FILTER_HISTORY_KEY}:${preferenceUserId}`) || '{}');
    } catch {
      return {};
    }
  });
  const [visibleResultColumns, setVisibleResultColumns] = useState<string[]>(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(`${BACKTEST_VISIBLE_COLUMNS_KEY}:${preferenceUserId}`) || '[]');
      return Array.isArray(saved) && saved.length ? normalizeVisibleResultColumns(saved.map(String)) : [...DEFAULT_VISIBLE_RESULT_COLUMNS];
    } catch {
      return [...DEFAULT_VISIBLE_RESULT_COLUMNS];
    }
  });
  const [columnPreferenceLoaded, setColumnPreferenceLoaded] = useState(false);
  const activeResultColumns = useMemo(
    () => normalizeVisibleResultColumns(visibleResultColumns)
      .map((key) => RESULT_COLUMNS.find((column) => column.key === key))
      .filter(Boolean) as typeof RESULT_COLUMNS,
    [visibleResultColumns],
  );
  useEffect(() => {
    localStorage.setItem(`${BACKTEST_VISIBLE_COLUMNS_KEY}:${preferenceUserId}`, JSON.stringify(visibleResultColumns));
  }, [preferenceUserId, visibleResultColumns]);
  useEffect(() => {
    void fetchJson<{ columns: string[] }>('/api/backtests/v2/preferences/result-columns').then((response) => {
      if (response.ok && response.data.columns?.length) {
        setVisibleResultColumns(normalizeVisibleResultColumns(response.data.columns));
      }
      setColumnPreferenceLoaded(true);
    });
  }, []);
  useEffect(() => {
    if (!columnPreferenceLoaded) return undefined;
    const timer = window.setTimeout(() => {
      void fetchJson('/api/backtests/v2/preferences/result-columns', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ columns: normalizeVisibleResultColumns(visibleResultColumns) }),
      });
    }, 350);
    return () => window.clearTimeout(timer);
  }, [columnPreferenceLoaded, visibleResultColumns]);
  const [tab, setTab] = useState<'opportunities' | 'combinations' | 'portfolio' | 'ai' | 'quality' | 'ipo'>('combinations');
  const [results, setResults] = useState<ResultPage>({ items: [], page: 1, page_size: 50, total: 0, pages: 0 });
  const initialResultPageRef = useRef(Math.max(1, Number(savedResultFilterState.page || 1)));
  const [resultScope, setResultScope] = useState<'run' | 'all' | 'strategies' | 'holistic'>(() => {
    const requestedScope = params.get('scope');
    if (requestedScope === 'run' || requestedScope === 'all' || requestedScope === 'holistic') return requestedScope;
    return ['run', 'all', 'strategies', 'holistic'].includes(savedResultFilterState.resultScope)
      ? savedResultFilterState.resultScope
      : 'strategies';
  });
  const [allRunsSelected, setAllRunsSelected] = useState(() => {
    const requestedScope = params.get('scope');
    return requestedScope ? requestedScope !== 'run' : savedResultFilterState.resultScope !== 'run';
  });
  const [allIpoRunsSelected, setAllIpoRunsSelected] = useState(false);
  const [ipoShowZeroTrades, setIpoShowZeroTrades] = useState(false);
  const [resultSorts, setResultSorts] = useState<ResultSort[]>(() => (
    Array.isArray(savedResultFilterState.resultSorts) && savedResultFilterState.resultSorts.length
      ? savedResultFilterState.resultSorts
      : [{ field: 'win_rate_pct', direction: 'desc' }]
  ));
  const initialResultSymbol = params.get('stock') || '';
  const defaultResultFilters: ResultAdvancedFilter[] = [
    ...(initialResultSymbol ? [{ id: 1, field: 'symbol', operator: 'eq', value: initialResultSymbol }] : []),
    { id: initialResultSymbol ? 2 : 1, field: 'total_trades', operator: 'gte', value: '20' },
  ];
  const initialResultFilters: ResultAdvancedFilter[] = !initialResultSymbol
    && Array.isArray(savedResultFilterState.filters)
    && savedResultFilterState.filters.length
    ? savedResultFilterState.filters
    : defaultResultFilters;
  const [resultFilterJoin, setResultFilterJoin] = useState<'and' | 'or'>(savedResultFilterState.join === 'or' ? 'or' : 'and');
  const [resultFilterRows, setResultFilterRows] = useState<ResultAdvancedFilter[]>(initialResultFilters);
  const [appliedResultFilters, setAppliedResultFilters] = useState<ResultAdvancedFilter[]>(initialResultFilters);
  const appliedResultFilterSignature = useRef(JSON.stringify(initialResultFilters));
  const nextResultFilterId = useRef(initialResultFilters.length + 1);
  const [resultSectors, setResultSectors] = useState<string[]>([]);
  const [resultSymbolSuggestions, setResultSymbolSuggestions] = useState<Array<{ symbol: string; company_name: string; sector?: string }>>([]);
  const [includeNonEquities, setIncludeNonEquities] = useState(Boolean(savedResultFilterState.includeNonEquities));
  const [resultsBusy, setResultsBusy] = useState(false);
  const [resultFilterStatus, setResultFilterStatus] = useState('');
  const [resultHeaderCategoricalFilters, setResultHeaderCategoricalFilters] = useState<Record<string, string>>({});
  const resultRequestId = useRef(0);
  const resultAbortRef = useRef<AbortController | null>(null);
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);
  const [aiQuestion, setAiQuestion] = useState('Top 10 reliable ordinary shares with positive out-of-sample return, at least 10 out-of-sample trades, and low drawdown');
  const [aiAnswer, setAiAnswer] = useState<any>(null);
  const [aiBusy, setAiBusy] = useState(false);
  const [aiScope, setAiScope] = useState<'all' | 'run'>('all');
  const [exporting, setExporting] = useState(false);
  const [exportScope, setExportScope] = useState<'run' | 'all'>('run');
  const [exportStatus, setExportStatus] = useState('');
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
  const [filterPreferenceLoaded, setFilterPreferenceLoaded] = useState(false);
  const fullPageDetail = params.get('detail') === 'full';

  useEffect(() => {
    void fetchJson<{ state: Record<string, any> }>('/api/backtests/v2/preferences/result-filters').then((response) => {
      const state = response.ok ? response.data.state || {} : {};
      if (Object.keys(state).length && !initialResultSymbol) {
        const filters = Array.isArray(state.filters) ? state.filters : [];
        if (filters.length) {
          setResultFilterRows(filters);
          setAppliedResultFilters(filters);
          appliedResultFilterSignature.current = JSON.stringify(filters);
          nextResultFilterId.current = Math.max(...filters.map((item: any) => Number(item.id) || 0), 0) + 1;
        }
        setResultFilterJoin(state.join === 'or' ? 'or' : 'and');
        if (Array.isArray(state.resultSorts) && state.resultSorts.length) setResultSorts(state.resultSorts);
        if (['run', 'all', 'strategies', 'holistic'].includes(state.resultScope)) {
          setResultScope(state.resultScope);
          setAllRunsSelected(state.resultScope !== 'run');
        }
        setIncludeNonEquities(Boolean(state.includeNonEquities));
        initialResultPageRef.current = Math.max(1, Number(state.page || 1));
        if ([25, 50, 100].includes(Number(state.pageSize))) {
          setResults((current) => ({ ...current, page_size: Number(state.pageSize) }));
        }
        if (state.resultHeaderCategoricalFilters && typeof state.resultHeaderCategoricalFilters === 'object') {
          setResultHeaderCategoricalFilters(state.resultHeaderCategoricalFilters);
        }
        if (state.opportunityFilters && typeof state.opportunityFilters === 'object') {
          setOpportunityFilters({ ...defaultOpportunityFilters, ...state.opportunityFilters });
        }
        if (Array.isArray(state.opportunitySorts) && state.opportunitySorts.length) setOpportunitySorts(state.opportunitySorts);
        if (Array.isArray(state.opportunityFilterRows)) {
          setOpportunityFilterRows(state.opportunityFilterRows);
          nextOpportunityFilterId.current = Math.max(...state.opportunityFilterRows.map((item: any) => Number(item.id) || 0), 0) + 1;
        }
        if (Array.isArray(state.appliedOpportunityFilters)) setAppliedOpportunityFilters(state.appliedOpportunityFilters);
        if (['opportunities', 'combinations', 'portfolio', 'ai', 'quality', 'ipo'].includes(state.tab)) setTab(state.tab);
      }
      setFilterPreferenceLoaded(true);
    });
  }, [initialResultSymbol]);

    const loadRuns = async () => {
    const response = await fetchJson<{ items: Run[]; ipo_items?: Run[]; unique_configuration_total?: number }>('/api/backtests/v2/runs?page=1&page_size=50');
    if (!response.ok) return;
    setRuns(response.data.items);
    setIpoRuns(response.data.ipo_items || []);
    setUniqueConfigurationTotal(Number(response.data.unique_configuration_total || 0));
    void fetchJson<{ items: Run[]; retention_days?: number }>('/api/backtests/v2/runs/archived').then((archived) => {
      if (!archived.ok) return;
      setArchivedRuns(archived.data.items || []);
      setArchiveRetentionDays(Number(archived.data.retention_days || 30));
    });
    const requested = params.get('run');
    const catalog = [...response.data.items, ...(response.data.ipo_items || [])];
    const matched = requested
      ? catalog.find((item) => item.run_id === requested) || null
      : null;
    setActiveRun((current) => {
      if (current) {
        return catalog.find((item) => item.run_id === current.run_id) || current;
      }
      return matched || response.data.items[0] || null;
    });
    if (matched && isIpoRun(matched)) {
      setAllRunsSelected(false);
      setAllIpoRunsSelected(false);
      setResultScope('run');
    }
  };

  useEffect(() => {
    if (!activeRun || !isIpoRun(activeRun)) {
      setIpoStrategySummary(null);
      return;
    }
    void fetchJson<IpoStrategySummary>(`/api/backtests/v2/runs/${activeRun.run_id}/ipo-strategy-summary`).then((response) => {
      setIpoStrategySummary(response.ok ? response.data : null);
    });
  }, [activeRun?.run_id, activeRun?.status, activeRun?.combinations_completed]);

  useEffect(() => {
    if (activeRun && isIpoRun(activeRun) && resultScope !== 'run') {
      setResultScope('run');
      setAllRunsSelected(false);
    }
  }, [activeRun?.run_id, resultScope]);

  useEffect(() => {
    if (!activeRun || !isIpoRun(activeRun)) {
      setIpoShowZeroTrades(false);
      return;
    }
    // IPO histories rarely reach 20 trades; keep a 1+ floor so win-rate
    // ranking is never padded with empty zero-trade simulations — unless the
    // researcher explicitly opens the raw cache view.
    if (ipoShowZeroTrades) return;
    setAppliedResultFilters((current) => {
      if (!needsIpoTradeFloor(current)) return current;
      const defaults = [defaultTradesFilter(true)];
      appliedResultFilterSignature.current = JSON.stringify(defaults);
      nextResultFilterId.current = 2;
      setResultFilterRows(defaults);
      setResultFilterJoin('and');
      return defaults;
    });
  }, [activeRun?.run_id, ipoShowZeroTrades]);

  const refreshActiveWorkspace = async () => {
    if (!activeRun) { await loadRuns(); return; }
    setWorkspaceRefreshBusy(true);
    setError('');
    const response = await fetchJson<Run>(`/api/backtests/v2/runs/${activeRun.run_id}/refresh`, {
      method: 'POST',
    });
    setWorkspaceRefreshBusy(false);
    if (!response.ok) {
      setError(response.error || 'Could not queue the incremental refresh.');
      return;
    }
    setActiveRun(response.data);
    setRuns((current) => current.map((run) => (
      run.run_id === response.data.run_id ? response.data : run
    )));
    setRunControlMessage(
      response.data.status === 'running' || response.data.status === 'queued'
        ? 'Checking for new market sessions. Unchanged stock and strategy results will be reused.'
        : 'Workspace is already up to date.',
    );
  };

  const loadArchivedRuns = async () => {
    const response = await fetchJson<{ items: Run[]; retention_days?: number }>('/api/backtests/v2/runs/archived');
    if (!response.ok) {
      setError(response.error || 'Could not load archived workspaces.');
      return;
    }
    setArchivedRuns(response.data.items || []);
    setArchiveRetentionDays(Number(response.data.retention_days || 30));
  };

  const openArchiveModal = async () => {
    setArchiveOpen(true);
    setArchiveMessage('');
    await loadArchivedRuns();
  };

  const moveRunToArchive = async (runId: string) => {
    setArchiveBusyId(runId);
    setArchiveMessage('');
    const response = await fetchJson<{ items: Run[]; retention_days?: number }>(`/api/backtests/v2/runs/${runId}/archive`, { method: 'POST' });
    setArchiveBusyId(null);
    if (!response.ok) {
      setError(response.error || 'Could not archive that workspace.');
      return;
    }
    setArchivedRuns(response.data.items || []);
    setArchiveRetentionDays(Number(response.data.retention_days || 30));
    setArchiveMessage('Workspace moved to archive. Its results are excluded until restored.');
    await loadRuns();
    setActiveRun((current) => (current?.run_id === runId ? null : current));
    setAllRunsSelected(true);
    setResultScope('strategies');
  };

  const restoreArchivedRun = async (runId: string) => {
    setArchiveBusyId(runId);
    setArchiveMessage('');
    const response = await fetchJson<{ items: Run[]; retention_days?: number }>(`/api/backtests/v2/runs/${runId}/restore`, { method: 'POST' });
    setArchiveBusyId(null);
    if (!response.ok) {
      setError(response.error || 'Could not restore that workspace.');
      return;
    }
    setArchivedRuns(response.data.items || []);
    setArchiveMessage('Workspace restored. Its results are included again.');
    await loadRuns();
  };

  const permanentlyDeleteArchivedRun = async (runId: string) => {
    if (!window.confirm('Permanently delete this archived workspace and all of its results? This cannot be undone.')) return;
    setArchiveBusyId(runId);
    setArchiveMessage('');
    const response = await fetchJson<{ items: Run[]; retention_days?: number }>(`/api/backtests/v2/runs/${runId}`, { method: 'DELETE' });
    setArchiveBusyId(null);
    if (!response.ok) {
      setError(response.error || 'Could not permanently delete that workspace.');
      return;
    }
    setArchivedRuns(response.data.items || []);
    setArchiveMessage('Workspace permanently deleted.');
    await loadRuns();
  };

  const deleteIpoRun = async (runId: string, runName?: string) => {
    const label = runName ? `"${runName}"` : 'this IPO workspace';
    if (!window.confirm(`Permanently delete ${label} and all of its IPO scan outcomes from the database? This cannot be undone.`)) return;
    setArchiveBusyId(runId);
    setError('');
    const response = await fetchJson<{ items: Run[]; deleted_run_id?: string }>(`/api/backtests/v2/runs/${runId}/ipo`, { method: 'DELETE' });
    setArchiveBusyId(null);
    if (!response.ok) {
      setError(response.error || 'Could not delete that IPO workspace.');
      return;
    }
    const remaining = response.data.items || [];
    setIpoRuns(remaining);
    setActiveRun((current) => {
      if (current?.run_id !== runId) return current;
      return remaining[0] || null;
    });
    if (!remaining.length) {
      setAllIpoRunsSelected(false);
      setTab('combinations');
    }
    await loadRuns();
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
      if (response.ok) {
        setActiveRun(response.data);
        setRuns((current) => current.map((run) => (
          run.run_id === response.data.run_id ? response.data : run
        )));
        setProgressTick((value) => value + 1);
      }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [activeRun?.run_id, activeRun?.status]);

  const scanEta = useMemo(
    () => estimateScanRemaining(allRunsSelected ? null : activeRun),
    [activeRun, allRunsSelected, progressTick],
  );

  useEffect(() => {
    if (!activeRun) return;
    if (activeRun.status === 'paused') setRunControlMessage(`Paused successfully at ${activeRun.symbols_completed}/${activeRun.symbols_total} stocks. Resume will continue from this checkpoint.`);
    if (activeRun.status === 'cancelled') setRunControlMessage(`Cancelled successfully. ${activeRun.combinations_completed.toLocaleString()} completed results remain available.`);
    if (activeRun.status === 'running' && !activeRun.pause_requested && !activeRun.cancel_requested) {
      setRunControlMessage((current) => current.startsWith('Run queued') ? 'Run resumed successfully.' : current);
    }
  }, [activeRun?.cancel_requested, activeRun?.combinations_completed, activeRun?.pause_requested, activeRun?.status, activeRun?.symbols_completed, activeRun?.symbols_total]);

  const filterAst = useMemo(() => ({
    join: resultFilterJoin,
    conditions: appliedResultFilters.map(({ field, operator, value }) => ({
      field, operator,
      value: resultFilterFields.find((item) => item.field === field)?.type === 'number' ? Number(value) : value,
    })),
  }), [appliedResultFilters, resultFilterJoin]);
  const visibleResultRows = useMemo(() => results.items.filter((row) => (
    Object.entries(resultHeaderCategoricalFilters).every(([key, value]) => (
      !value || String(row[key] ?? '') === value
    ))
  )), [resultHeaderCategoricalFilters, results.items]);

  useEffect(() => {
    const state = {
      filters: appliedResultFilters,
      join: resultFilterJoin,
      resultSorts,
      resultScope,
      includeNonEquities,
      page: results.page,
      pageSize: results.page_size,
      opportunityFilters,
      opportunitySorts,
      opportunityFilterRows,
      appliedOpportunityFilters,
      resultHeaderCategoricalFilters,
      tab,
    };
    localStorage.setItem(`${BACKTEST_FILTER_HISTORY_KEY}:${preferenceUserId}`, JSON.stringify(state));
    if (!filterPreferenceLoaded || fullPageDetail) return undefined;
    const timer = window.setTimeout(() => {
      void fetchJson('/api/backtests/v2/preferences/result-filters', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ state }),
      });
    }, 350);
    return () => window.clearTimeout(timer);
  }, [appliedOpportunityFilters, appliedResultFilters, filterPreferenceLoaded, fullPageDetail, includeNonEquities, opportunityFilterRows, opportunityFilters, opportunitySorts, preferenceUserId, resultFilterJoin, resultHeaderCategoricalFilters, resultScope, resultSorts, results.page, results.page_size, tab]);

  useEffect(() => {
    void fetchJson<{ sectors: string[] }>('/api/backtests/v2/filter-options').then((response) => {
      if (response.ok) setResultSectors(response.data.sectors || []);
    });
  }, []);

  useEffect(() => {
    const completeFilters = resultFilterRows
      .filter((item) => item.value.trim())
      .map((item) => ({ ...item, value: item.value.trim() }));
    const signature = JSON.stringify(completeFilters);
    if (signature === appliedResultFilterSignature.current) return undefined;
    const timer = window.setTimeout(() => {
      appliedResultFilterSignature.current = signature;
      setError('');
      setResultFilterStatus('Applying filters…');
      setAppliedResultFilters(completeFilters);
    }, 350);
    return () => window.clearTimeout(timer);
  }, [resultFilterRows]);

  const refreshFilteredResults = async () => {
    if (!activeRun) return;
    setFilteredRefreshBusy(true);
    setError('');
    setRunControlMessage('Resolving finalized filters and queuing only matching symbols…');
    const targetRun = resultScope === 'run' ? activeRun.run_id : 'all';
    const response = await fetchJson<{ symbol_count: number; strategy_count: number; runs_queued: number; run_ids: string[] }>(
      `/api/backtests/v2/runs/${targetRun}/refresh-filtered`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          filters: filterAst,
          include_non_equities: includeNonEquities,
          sorts: resultSorts,
          unique_by_symbol: resultScope === 'holistic',
          unique_by_strategy: resultScope === 'strategies',
          preferred_run_id: activeRun.run_id,
          page: 1,
          page_size: 100,
        }),
      },
      120000,
    );
    if (!response.ok) {
      setFilteredRefreshBusy(false);
      setError(response.error || 'Could not queue the filtered refresh.');
      return;
    }
    setRunControlMessage(`Refreshing ${response.data.strategy_count.toLocaleString()} filtered strategies on the same workspace…`);
    const pending = new Set(response.data.run_ids || []);
    for (let attempt = 0; pending.size && attempt < 300; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 2000));
      const checkpoints = await Promise.all(Array.from(pending).map(async (runId) => ({
        runId,
        response: await fetchJson<Run>(`/api/backtests/v2/runs/${runId}`),
      })));
      checkpoints.forEach(({ runId, response: checkpoint }) => {
        if (!checkpoint.ok || !['queued', 'running', 'paused'].includes(checkpoint.data.status)) pending.delete(runId);
      });
      setRunControlMessage(`Live refresh: ${response.data.runs_queued - pending.size}/${response.data.runs_queued} workspaces completed · ${response.data.strategy_count.toLocaleString()} filtered strategies`);
    }
    await loadRuns();
    await loadResults(1);
    setFilteredRefreshBusy(false);
    setRunControlMessage(`Filtered data is live on the same workspace. Rechecked ${response.data.strategy_count.toLocaleString()} strategies and loaded any new BUY signals.`);
  };

  const loadResults = async (page = 1) => {
    if (!activeRun) return;
    resultAbortRef.current?.abort();
    const controller = new AbortController();
    resultAbortRef.current = controller;
    const requestId = ++resultRequestId.current;
    setResultsBusy(true);
    setResultFilterStatus('Applying filters and ranking matching simulations…');
    const targetRun = resultScope === 'run' ? activeRun.run_id : 'all';
    const response = await fetchJson<ResultPage>(`/api/backtests/v2/runs/${targetRun}/results/query`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      signal: controller.signal,
      body: JSON.stringify({
        filters: filterAst,
        include_non_equities: includeNonEquities,
        include_zero_trade_simulations: isIpoRun(activeRun) && ipoShowZeroTrades,
        sorts: resultSorts,
        unique_by_symbol: resultScope === 'holistic',
        unique_by_strategy: resultScope === 'strategies',
        page,
        page_size: results.page_size,
      }),
    });
    if (requestId !== resultRequestId.current) return;
    resultAbortRef.current = null;
    setResultsBusy(false);
    if (response.ok) {
      setResults(response.data);
      setResultFilterStatus(`${response.data.total.toLocaleString()} matching simulations ready`);
      // Brand-new IPO listings often finish first with only zero-trade rows.
      // Open the raw cache automatically so the live table is not blank while
      // longer-history stocks are still scanning.
      if (
        isIpoRun(activeRun)
        && !ipoShowZeroTrades
        && response.data.total === 0
        && Number(response.data.cached_total || 0) > 0
        && Number(response.data.trade_outcomes || 0) === 0
      ) {
        appliedResultFilterSignature.current = JSON.stringify([]);
        nextResultFilterId.current = 1;
        setResultFilterRows([]);
        setAppliedResultFilters([]);
        setIpoShowZeroTrades(true);
      }
    } else {
      setResultFilterStatus('Filter could not be applied');
      setError(response.error || 'Could not load results.');
    }
  };

  useEffect(() => {
    const page = initialResultPageRef.current;
    initialResultPageRef.current = 1;
    void loadResults(page);
    // IPO research rarely retains normal rows, so symbols_completed is the
    // reliable checkpoint signal that new cache outcomes are ready to load.
  }, [
    activeRun?.run_id,
    activeRun?.symbols_completed,
    activeRun?.combinations_completed,
    filterAst,
    includeNonEquities,
    ipoShowZeroTrades,
    resultScope,
    resultSorts,
    results.page_size,
  ]);

  useEffect(() => {
    if (!activeRun || tab !== 'portfolio') return;
    void fetchJson<{ items: Portfolio[] }>(`/api/backtests/v2/runs/${activeRun.run_id}/portfolios`).then((response) => response.ok && setPortfolios(response.data.items));
  }, [activeRun?.run_id, activeRun?.status, tab]);

  const loadOpportunities = async (page = 1) => {
    const numericFilters = {
      minimum_trades: optionalNumber(opportunityFilters.minimum_trades) ?? 0,
      minimum_win_rate: optionalNumber(opportunityFilters.minimum_win_rate) ?? 0,
      minimum_confidence: optionalNumber(opportunityFilters.minimum_confidence) ?? 0,
      minimum_sharpe: optionalNumber(opportunityFilters.minimum_sharpe) ?? -999,
      minimum_profit_factor: optionalNumber(opportunityFilters.minimum_profit_factor) ?? 0,
      maximum_drawdown: optionalNumber(opportunityFilters.maximum_drawdown) ?? 100,
      minimum_return: optionalNumber(opportunityFilters.minimum_return) ?? 0,
    };
    const response = await fetchJson<OpportunityPage>('/api/backtests/v2/runs/all/strong-buys/query', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...opportunityFilters, ...numericFilters, sorts: opportunitySorts, filters: appliedOpportunityFilters.map(({ field, operator, value }) => ({ field, operator, value })), minimum_volume: opportunityFilters.minimum_volume ? Number(opportunityFilters.minimum_volume) : null, category: opportunityFilters.category || null, include_non_equities: includeNonEquities, page, page_size: opportunities.page_size }),
    });
    if (response.ok) setOpportunities(response.data); else setError(response.error || 'Could not load current opportunities.');
  };

  useEffect(() => { if (tab === 'opportunities') void loadOpportunities(1); }, [activeRun?.run_id, activeRun?.combinations_completed, tab, opportunityFilters, opportunitySorts, appliedOpportunityFilters, includeNonEquities, opportunities.page_size]);

  useEffect(() => {
    if (!showHowItWorks && !columnPickerOpen && !archiveOpen) return undefined;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      if (archiveOpen) setArchiveOpen(false);
      else if (columnPickerOpen) setColumnPickerOpen(false);
      else setShowHowItWorks(false);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [archiveOpen, columnPickerOpen, showHowItWorks]);

  useEffect(() => {
    if (!selectedOpportunity || fullPageDetail) return undefined;
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') setSelectedOpportunity(null); };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [fullPageDetail, selectedOpportunity]);

  const openOpportunity = async (row: Opportunity & { cache_key?: string }) => {
    setDetailBusy(true); setTradeFilter('all'); setError('');
    const cacheKey = row.cache_key || undefined;
    const cacheParam = cacheKey ? `cache_key=${encodeURIComponent(cacheKey)}` : '';
    // Synthetic IPO result ids are negative; always address cache rows via result 0 + cache_key.
    const tradesResultId = cacheKey ? 0 : row.result_id;
    const [detailResponse, tradesResponse] = await Promise.all([
      cacheKey
        ? fetchJson<any>(`/api/backtests/v2/results/0?${cacheParam}`)
        : fetchJson<any>(`/api/backtests/v2/runs/all/strong-buys/${row.symbol}?result_id=${row.result_id}`),
      fetchJson<TradePage>(`/api/backtests/v2/results/${tradesResultId}/trades?page=1&page_size=100&result_filter=all${cacheParam ? `&${cacheParam}` : ''}`),
    ]);
    setDetailBusy(false);
    if (detailResponse.ok && tradesResponse.ok) {
      setSelectedOpportunity(cacheKey ? { best: { ...detailResponse.data, result_id: row.result_id || 0, cache_key: cacheKey }, alternatives: [], disclaimer: 'Cached IPO research evidence is not a recommendation.' } : detailResponse.data);
      setDetailTrades(tradesResponse.data);
    }
    else setError((!detailResponse.ok && detailResponse.error) || (!tradesResponse.ok && tradesResponse.error) || 'Could not load recommendation details.');
  };
  const openOpportunityPage = (row: Opportunity & { cache_key?: string }) => {
    // IPO rows are cache-backed; open in-place so we never lose cache_key across a reload
    // that previously only searched normal (non-IPO) run lists.
    if (row.cache_key || isIpoRun(activeRun)) {
      void openOpportunity(row);
      return;
    }
    sessionStorage.setItem('backtest-lab-return-scroll', String(window.scrollY));
    const runId = row.run_id || activeRun?.run_id || 'all';
    const cached = row.cache_key ? `&cache_key=${encodeURIComponent(row.cache_key)}` : '';
    window.location.assign(`/dashboard/backtest?run=${encodeURIComponent(runId)}&stock=${encodeURIComponent(row.symbol)}&result=${row.result_id}&detail=full&from=backtest-lab${cached}`);
  };
  useEffect(() => {
    if (fullPageDetail || resultsBusy || results.items.length === 0) return;
    const savedScroll = sessionStorage.getItem('backtest-lab-return-scroll');
    if (savedScroll == null) return;
    sessionStorage.removeItem('backtest-lab-return-scroll');
    window.requestAnimationFrame(() => window.scrollTo({ top: Number(savedScroll) || 0 }));
  }, [fullPageDetail, results.items.length, resultsBusy]);

  const linkedDetailOpened = useRef(false);
  useEffect(() => {
    const resultId = Number(params.get('result') || 0);
    const symbol = String(params.get('stock') || '').toUpperCase();
    const cacheKey = params.get('cache_key') || undefined;
    if (!activeRun || !symbol || linkedDetailOpened.current) return;
    if (!cacheKey && !resultId) return;
    linkedDetailOpened.current = true;
    void openOpportunity({ result_id: resultId || 0, symbol, cache_key: cacheKey } as Opportunity & { cache_key?: string });
  }, [activeRun?.run_id]);

  const detailCacheKey = selectedOpportunity?.best?.cache_key as string | undefined;
  const detailApiResultId = detailCacheKey ? 0 : selectedOpportunity?.best?.result_id;

  const filterDetailTrades = async (filter: string) => {
    if (detailApiResultId == null && !detailCacheKey) return;
    setTradeFilter(filter);
    const cacheQuery = detailCacheKey ? `&cache_key=${encodeURIComponent(detailCacheKey)}` : '';
    const response = await fetchJson<TradePage>(`/api/backtests/v2/results/${detailApiResultId || 0}/trades?page=1&page_size=100&result_filter=${filter}${cacheQuery}`);
    if (response.ok) setDetailTrades(response.data);
  };

  const loadDetailTradePage = async (page: number) => {
    if ((detailApiResultId == null && !detailCacheKey) || page < 1 || page > detailTrades.pages) return;
    const cacheQuery = detailCacheKey ? `&cache_key=${encodeURIComponent(detailCacheKey)}` : '';
    const response = await fetchJson<TradePage>(`/api/backtests/v2/results/${detailApiResultId || 0}/trades?page=${page}&page_size=${detailTrades.page_size || 100}&result_filter=${tradeFilter}${cacheQuery}`);
    if (response.ok) setDetailTrades(response.data);
  };

  const startRun = async (event: FormEvent) => {
    event.preventDefault(); setCreating(true); setError('');
    const parsedMinHold = optionalNumber(minHoldingDays) ?? 5;
    const parsedMaxHold = optionalNumber(maxHoldingDays) ?? 90;
    const parsedMaxListingAge = optionalNumber(maxListingAgeDays);
    if (!Number.isInteger(parsedMinHold) || parsedMinHold < 0 || parsedMinHold > 365) { setCreating(false); setError('Minimum holding days must be a whole number from 0 to 365.'); return; }
    if (!Number.isInteger(parsedMaxHold) || parsedMaxHold < 1 || parsedMaxHold > 365) { setCreating(false); setError('Maximum holding days must be a whole number from 1 to 365. A blank field uses the 90-day default.'); return; }
    if (parsedMaxListingAge != null && (!Number.isInteger(parsedMaxListingAge) || parsedMaxListingAge < 1 || parsedMaxListingAge > 36500)) { setCreating(false); setError('Maximum listing age must be a whole number from 1 to 36,500 days.'); return; }
    if (ipoResearchMode && parsedMaxListingAge == null) { setCreating(false); setError('Choose a listing-age limit for the separate IPO research workspace.'); return; }
    if (runScope === 'single' && !selectedStock) { setCreating(false); setError('Choose one stock from the symbol suggestions before running.'); return; }
    if (strategyMode === 'custom' && customQuery.trim().length < 20) { setCreating(false); setError('Enter a complete Strategy Language query.'); return; }
    if (strategyMode === 'presets' && selected.size === 0) { setCreating(false); setError('Select at least one strategy preset.'); return; }
    const parsedDiscoveryBudget = optionalNumber(discoveryBudget);
    if (strategyMode === 'discovery' && (selected.size < 2 || parsedDiscoveryBudget == null || !Number.isInteger(parsedDiscoveryBudget) || parsedDiscoveryBudget < 10 || parsedDiscoveryBudget > 10000)) { setCreating(false); setError('Discovery requires at least two base strategies and a whole candidate budget from 10 to 10,000.'); return; }
    if (parsedMaxHold != null && parsedMinHold > parsedMaxHold) { setCreating(false); setError('Minimum holding days cannot exceed maximum holding days.'); return; }
    const response = await fetchJson<Run>('/api/backtests/v2/runs', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, history_mode: historyMode, start_date: historyMode === 'all_available' ? allHistoryStart : startDate, end_date: historyMode === 'all_available' ? today : endDate, strategy_mode: strategyMode, custom_query_text: strategyMode === 'custom' ? customQuery : null, preset_ids: strategyMode === 'presets' ? Array.from(selected) : [], discovery_budget: strategyMode === 'discovery' ? parsedDiscoveryBudget : 1000, discovery_seed: 20260718, discovery_base_ids: strategyMode === 'discovery' ? Array.from(selected) : [], symbols: runScope === 'single' && selectedStock ? [selectedStock.symbol] : null, ordinary_shares_only: ordinaryOnly, max_listing_age_days: parsedMaxListingAge, min_holding_days: parsedMinHold, max_holding_days: parsedMaxHold, use_preset_holding_days: ipoResearchMode, data_source: 'merolagani', worker_policy: 'adaptive_market_hours', run_type: ipoResearchMode ? 'ipo_research' : runScope === 'single' ? 'single_stock' : 'market_scan' }),
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
    setRunControlBusy(action);
    setRunControlMessage(`${action === 'pause' ? 'Pausing' : action === 'cancel' ? 'Cancelling' : action === 'resume' ? 'Resuming' : 'Retrying'}…`);
    const response = await fetchJson<Run>(`/api/backtests/v2/runs/${activeRun.run_id}/${action}`, { method: 'POST' });
    setRunControlBusy(null);
    if (response.ok) {
      setActiveRun(response.data);
      setRunControlMessage(
        action === 'pause' ? 'Pause requested · finishing the current stock checkpoint safely.'
          : action === 'cancel' ? 'Cancellation requested · completed results remain saved.'
            : action === 'resume' ? 'Run queued to resume from its saved checkpoint.'
              : 'Failed symbols queued for retry.',
      );
      void loadRuns();
    } else {
      setRunControlMessage('');
      setError(response.error || `Could not ${action} this run.`);
    }
  };

  const askAi = async (promptOverride?: string) => {
    const question = String(promptOverride || aiQuestion).trim();
    if (!activeRun || !question) return;
    if (promptOverride) setAiQuestion(question);
    setAiBusy(true); setAiAnswer(null);
    const targetRun = aiScope === 'all' ? 'all' : activeRun.run_id;
    const response = await fetchJson<any>(`/api/backtests/v2/runs/${targetRun}/ai-query`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: question, include_non_equities: includeNonEquities }),
    }, 120000);
    setAiBusy(false);
    if (response.ok) setAiAnswer(response.data); else setError(response.error || 'AI analysis failed.');
  };

  const downloadCsv = async (scope: 'run' | 'all' = 'run') => {
    if (!activeRun) return;
    setExporting(true); setError(''); setExportStatus(scope === 'all' ? 'Preparing all cached results…' : 'Preparing filtered run results…');
    try {
      const token = localStorage.getItem('accessToken');
      const targetRun = scope === 'all' ? 'all' : activeRun.run_id;
      const response = await fetch(`${getApiUrl()}/api/backtests/v2/runs/${targetRun}/results/export.csv`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({
          filters: scope === 'all' ? { join: 'and', conditions: [] } : filterAst,
          include_non_equities: includeNonEquities,
          include_zero_trade_simulations: isIpoRun(activeRun) && ipoShowZeroTrades,
          sorts: resultSorts, page: 1, page_size: 100,
        }),
      });
      if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail || 'CSV export failed.');
      const blob = await response.blob();
      if (!blob.size) throw new Error('The server returned an empty CSV file.');
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a'); link.href = url;
      const disposition = response.headers.get('Content-Disposition') || '';
      const serverName = disposition.match(/filename="?([^";]+)"?/i)?.[1];
      link.download = serverName || (scope === 'all' ? 'all-my-backtest-results.csv' : `${activeRun.name.replace(/[^a-z0-9]+/gi, '-').replace(/^-|-$/g, '') || 'backtest'}-all-results.csv`);
      link.style.display = 'none'; document.body.appendChild(link); link.click(); link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 30000);
      setExportStatus(`Downloaded ${link.download} · ${(blob.size / 1024 / 1024).toFixed(1)} MB`);
    } catch (exportError) { const message = exportError instanceof Error ? exportError.message : 'CSV export failed.'; setError(message); setExportStatus('Download failed'); }
    finally { setExporting(false); }
  };

  const grouped = useMemo(() => Object.entries(presets.reduce<Record<string, Preset[]>>((all, preset) => {
    (all[preset.category] ||= []).push(preset); return all;
  }, {})), [presets]);
  const newIpoPresetIds = useMemo(
    () => presets.filter((preset) => preset.category === 'New IPO aftermarket research').map((preset) => preset.id),
    [presets],
  );
  const tier1IpoPresetIds = useMemo(
    () => presets.filter((preset) => preset.tier === 'ipo_tier1_research').map((preset) => preset.id),
    [presets],
  );
  const totalRunStrategySelections = useMemo(
    () => runs.reduce((total, run) => total + runStrategyCount(run), 0),
    [runs],
  );
  const totalScansDone = useMemo(
    () => runs.reduce((total, run) => total + runScansDone(run), 0),
    [runs],
  );
  const useNewIpoResearchSetup = () => {
    setIpoResearchMode(true);
    setName('New IPO aftermarket strategy scan');
    setHistoryMode('all_available');
    setOrdinaryOnly(true);
    setMaxListingAgeDays('730');
    setRunScope('all');
    setSelectedStock(null);
    setStockSearch('');
    setStrategyMode('presets');
    setSelected(new Set(newIpoPresetIds));
    setMinHoldingDays('3');
    setMaxHoldingDays('45');
  };
  const applyTier1IpoResearchSetup = (listingAgeDays = '365') => {
    setIpoResearchMode(true);
    setName(`IPO Tier-1 research · ≤${listingAgeDays}d`);
    setHistoryMode('all_available');
    setOrdinaryOnly(true);
    setMaxListingAgeDays(listingAgeDays);
    setRunScope('all');
    setSelectedStock(null);
    setStockSearch('');
    setStrategyMode('presets');
    setSelected(new Set(tier1IpoPresetIds.length ? tier1IpoPresetIds : newIpoPresetIds));
    setMinHoldingDays('3');
    setMaxHoldingDays('45');
  };

  const toggleResultSort = (field: string, additive: boolean) => setResultSorts((current) => (
    nextBacktestSortRules(current, field, additive)
  ));
  const resultSortMarker = (field: string) => {
    const index = resultSorts.findIndex((item) => item.field === field);
    return index < 0 ? '↕' : `${resultSorts[index].direction === 'desc' ? '↓' : '↑'} ${index + 1}`;
  };
  const addResultFilter = (fieldName = 'symbol', value = '', operatorOverride?: string) => {
    const field = resultFilterFields.find((item) => item.field === fieldName) || resultFilterFields[0];
    setResultFilterRows((current) => [...current, { id: nextResultFilterId.current++, field: field.field, operator: operatorOverride || (field.type === 'number' ? 'gte' : field.field === 'sector' ? 'eq' : 'contains'), value }]);
  };
  const updateResultFilter = (id: number, update: Partial<ResultAdvancedFilter>) => {
    setResultFilterRows((current) => current.map((item) => item.id === id ? { ...item, ...update } : item));
  };
  const suggestResultSymbols = (value: string) => {
    if (!value.trim()) { setResultSymbolSuggestions([]); return; }
    void fetchJson<{ items: Array<{ symbol: string; company_name: string; sector?: string }> }>(`/api/backtests/v2/symbols?search=${encodeURIComponent(value.trim())}&include_non_equities=${includeNonEquities ? 'true' : 'false'}`).then((response) => {
      if (response.ok) setResultSymbolSuggestions(response.data.items || []);
    });
  };
  const resetResultFilters = () => {
    const defaults: ResultAdvancedFilter[] = [defaultTradesFilter(isIpoRun(activeRun))];
    appliedResultFilterSignature.current = JSON.stringify(defaults);
    nextResultFilterId.current = 2;
    setIpoShowZeroTrades(false);
    setResultFilterRows(defaults); setAppliedResultFilters(defaults); setResultFilterJoin('and'); setResultSorts([{ field: 'win_rate_pct', direction: 'desc' }]);
  };
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

  return <div className={`research-page ${fullPageDetail ? 'detail-page' : ''}`}>
    <header className="research-hero">
      <div><span className="research-kicker">NEPSE Research Lab · Daily data</span><h1>Backtesting workspace</h1><p>Reproducible out-of-sample rankings, shared-capital simulation, and persistent background scans.</p></div>
      <div className="research-hero-actions"><button type="button" onClick={() => setShowHowItWorks(true)}>How it works</button><a href="/dashboard/backtest?legacy=1">Custom strategy language</a><span>Research only · no broker orders</span></div>
    </header>

    {error && <div className="research-alert" role="alert">{error}<button onClick={() => setError('')}>Dismiss</button></div>}

    {columnPickerOpen && <ColumnPickerModal
      open={columnPickerOpen}
      title="Backtest result columns"
      subtitle="Choose which result fields to show and drag them into your preferred order."
      columns={RESULT_COLUMNS}
      selectedKeys={visibleResultColumns}
      defaultKeys={DEFAULT_VISIBLE_RESULT_COLUMNS}
      onClose={() => setColumnPickerOpen(false)}
      onChange={(keys) => setVisibleResultColumns(normalizeVisibleResultColumns(keys))}
    />}
    {archiveOpen && <div className="backtest-help-backdrop" role="presentation" onClick={() => setArchiveOpen(false)}>
      <section className="backtest-help-modal research-archive-modal" role="dialog" aria-modal="true" aria-labelledby="research-archive-title" onClick={(event) => event.stopPropagation()}>
        <header>
          <div>
            <span>Workspace archive</span>
            <h2 id="research-archive-title">Archived scan workspaces</h2>
            <p>Archived runs are excluded from combined results. Restore them anytime, or permanently delete. Unrestored archives auto-delete after {archiveRetentionDays} days.</p>
          </div>
          <button type="button" className="backtest-help-close" onClick={() => setArchiveOpen(false)} aria-label="Close archive">×</button>
        </header>
        <div className="backtest-help-body research-archive-body">
          {archiveMessage && <p className="research-archive-message" role="status">{archiveMessage}</p>}
          <section>
            <h3>Active workspaces</h3>
            <p>Move a workspace here to hide its results from All runs and recommendations.</p>
            {runs.length === 0 ? <p className="research-archive-empty">No active workspaces.</p> : (
              <ul className="research-archive-list">
                {runs.map((run) => (
                  <li key={run.run_id}>
                    <div>
                      <b>{run.name}</b>
                      <span>{run.status} · {run.symbols_completed}/{run.symbols_total} stocks · {run.combinations_completed.toLocaleString()} results</span>
                    </div>
                    <button type="button" disabled={archiveBusyId === run.run_id} onClick={() => void moveRunToArchive(run.run_id)}>
                      {archiveBusyId === run.run_id ? 'Archiving…' : 'Move to archive'}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section>
            <h3>Archived ({archivedRuns.length})</h3>
            {archivedRuns.length === 0 ? <p className="research-archive-empty">No archived workspaces yet.</p> : (
              <ul className="research-archive-list">
                {archivedRuns.map((run) => (
                  <li key={run.run_id}>
                    <div>
                      <b>{run.name}</b>
                      <span>
                        {run.combinations_completed.toLocaleString()} results · auto-deletes in {run.archive_days_remaining ?? archiveRetentionDays} day{(run.archive_days_remaining ?? archiveRetentionDays) === 1 ? '' : 's'}
                      </span>
                    </div>
                    <div className="research-archive-actions">
                      <button type="button" disabled={archiveBusyId === run.run_id} onClick={() => void restoreArchivedRun(run.run_id)}>
                        {archiveBusyId === run.run_id ? 'Working…' : 'Restore'}
                      </button>
                      <button type="button" className="danger" disabled={archiveBusyId === run.run_id} onClick={() => void permanentlyDeleteArchivedRun(run.run_id)}>
                        Delete permanently
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
        <footer><span>Press <kbd>Esc</kbd> or use × to close.</span><button type="button" onClick={() => setArchiveOpen(false)}>Done</button></footer>
      </section>
    </div>}
    {showHowItWorks && <div className="backtest-help-backdrop" role="presentation">
      <section className="backtest-help-modal" role="dialog" aria-modal="true" aria-labelledby="backtest-help-title">
        <header><div><span>NEPSE Research Lab guide</span><h2 id="backtest-help-title">How this backtest and table work</h2><p>Use this page to compare historical research results—not as a promise of future performance.</p></div><button type="button" className="backtest-help-close" onClick={() => setShowHowItWorks(false)} aria-label="Close how it works">×</button></header>
        <div className="backtest-help-body">
          <section><h3>1. What a backtest does</h3><p>Your entry conditions are evaluated after each completed daily session. A matching BUY signal enters at the next available session open. One single-stock backtest holds one position at a time and never places a broker order.</p><div className="backtest-help-flow"><span>Daily close signal</span><b>→</b><span>Next open entry</span><b>→</b><span>Risk-managed exit</span><b>→</b><span>Net result</span></div></section>
          <section><h3>2. How selling works</h3><p>The current engine is long-only: the strategy creates the BUY entry; exits are managed by the selected risk settings.</p><ol><li><b>Minimum holding period first.</b> By default, no strategy, target, or protective-stop sale is simulated before five completed holding days. A user-entered run setting can override five days.</li><li><b>Stop loss / trailing stop has priority after the minimum.</b> If both stop and target are touched in one daily candle, the stop is used first as the conservative assumption.</li><li><b>Maximum holding days</b> forces an exit at day 90 by default.</li><li><b>End of history</b> closes a remaining position only after its minimum holding period; a newer entry remains open when history ends too early.</li></ol><p className="backtest-help-note">A gap below a stop exits at the weaker opening price after the configured minimum hold. Buy and sell slippage are included.</p></section>
          <section><h3>3. Net profit includes Nepal-market costs</h3><div className="backtest-help-grid"><article><b>On buy</b><span>Broker commission, SEBON fee, buy slippage.</span></article><article><b>On sell</b><span>Broker commission, SEBON fee, DP charge, sell slippage and CGT on profitable sales.</span></article><article><b>Position limits</b><span>Cash, selected sizing, and maximum volume participation can reject an order.</span></article></div><p>Every saved result keeps the exact charge model, sizing, stop, target and holding settings used for that run.</p></section>
          <section><h3>4. Reading the Recommendations table</h3><p>It shows one best-matching historical strategy per stock. By default, ordinary shares are included; change the instrument filter only if you intentionally want funds, debentures, promoter shares, or other classes.</p><div className="backtest-help-score"><b>Combined score = 45% win rate + 30% net return + 15% trade sample + 10% reliability</b><span>Trade sample reaches its maximum at 50 trades. Net return is capped at 100 before scoring so one extreme result cannot dominate.</span></div><p><b>Robust score is different:</b> it favours locked out-of-sample expectancy and return, Sharpe, drawdown protection, walk-forward stability, and enough out-of-sample trades. Use Robust score when comparing strategies; use Combined score to quickly rank recommendation candidates.</p></section>
          <section><h3>5. Finding the result you want</h3><ul><li>Click any column heading to sort it. Hold <kbd>Shift</kbd> while clicking another heading to add a secondary sort.</li><li>Use the quick filters for trades, win rate, return, liquidity and signal state.</li><li>Use Advanced stock filters for exact multiple conditions. All chosen conditions must match.</li><li><b>Strong buy today</b> means the saved strategy condition matched on the latest completed daily session; <b>Historical leader</b> means it ranked well historically but has no new entry today.</li></ul></section>
          <section className="backtest-help-disclaimer"><h3>Important</h3><p>Historical performance, rankings and current signals are research tools. They can be affected by data gaps, liquidity, fees, execution assumptions and market conditions. Review the trades, sample size, drawdown, current signal conditions and your own risk limits before using a paper or live strategy.</p></section>
        </div>
        <footer><span>Press <kbd>Esc</kbd> anytime to close.</span><button type="button" onClick={() => setShowHowItWorks(false)}>Yes, I understand</button></footer>
      </section>
    </div>}

    <section className="research-run-library" aria-label="Saved backtest runs">
      <div className="research-run-library-head"><span><small>Continuous research</small><h2>Scan workspaces</h2><p>Identical stock and strategy scans update one workspace. Refresh checks only missing market-data tails and reuses unchanged results.</p></span><div><strong>{runs.length}</strong><span>unique</span><button type="button" className="research-archive-button" onClick={() => void openArchiveModal()} title="Open archived workspaces"><span aria-hidden="true">🗄</span> Archive{archivedRuns.length ? ` (${archivedRuns.length})` : ''}</button><button disabled={workspaceRefreshBusy} onClick={() => void refreshActiveWorkspace()}>{workspaceRefreshBusy ? 'Checking…' : 'Refresh new data'}</button></div></div>
      <div className="research-run-strip">{runs.length > 0 && <button className={`all-runs-card ${allRunsSelected ? 'active' : ''}`} onClick={() => { setAllRunsSelected(true); setAllIpoRunsSelected(false); setResultScope('strategies'); setTab('combinations'); }}><span className="research-run-card-top"><b>All runs</b><em>combined</em></span><span className="research-run-card-metrics"><small><strong>{runs.length}</strong> workspaces</small><small><strong>{uniqueConfigurationTotal.toLocaleString()}</strong> eligible · {totalScansDone.toLocaleString()} scans done · {totalRunStrategySelections.toLocaleString()} strategies</small></span><span className="research-run-card-progress"><i style={{ width: '100%' }} /></span></button>}{runs.length === 0 ? <p>No v2 research runs yet.</p> : runs.map((run) => <div key={run.run_id} className={`research-run-card-wrap ${!allRunsSelected && !allIpoRunsSelected && activeRun?.run_id === run.run_id ? 'active' : ''}`}><button type="button" className={!allRunsSelected && !allIpoRunsSelected && activeRun?.run_id === run.run_id ? 'active' : ''} onClick={() => { setAllRunsSelected(false); setAllIpoRunsSelected(false); setResultScope('run'); setActiveRun(run); }}><span className="research-run-card-top"><b>{run.name}</b><em className={`run-${run.status}`}>{run.status}</em></span><span className="research-run-card-metrics"><small><strong>{run.symbols_completed}/{run.symbols_total}</strong> stocks</small><small><strong>{run.combinations_completed.toLocaleString()}</strong> eligible · {runScansDone(run).toLocaleString()} scans done · {runStrategyCount(run).toLocaleString()} strategies</small></span><span className="research-run-card-progress"><i style={{ width: `${Math.max(0, Math.min(100, run.progress_pct || 0))}%` }} /></span></button></div>)}</div>
    </section>
    {ipoRuns.length > 0 && <section className="research-run-library ipo-run-library" aria-label="New IPO research runs">
      <div className="research-run-library-head"><span><small>Separate sparse-history research</small><h2>New IPO strategy testing</h2><p>Excluded from All runs and normal recommendations. One-trade outcomes contribute only to pooled cross-stock validation.</p></span><div><strong>{ipoRuns.length}</strong><span>IPO workspaces</span></div></div>
      <div className="research-run-strip"><button className={`all-runs-card ${allIpoRunsSelected ? 'active' : ''}`} onClick={() => { setAllRunsSelected(false); setAllIpoRunsSelected(true); setResultScope('run'); if (ipoRuns[0]) setActiveRun(ipoRuns[0]); setTab('ipo'); }}><span className="research-run-card-top"><b>All IPO runs</b><em>overview</em></span><span className="research-run-card-metrics"><small><strong>{ipoRuns.length}</strong> workspaces</small><small><strong>{ipoRuns.reduce((total, run) => total + runScansDone(run), 0).toLocaleString()}</strong> scans · {ipoRuns.reduce((total, run) => total + runStrategyCount(run), 0).toLocaleString()} strategy selections</small></span><span className="research-run-card-progress"><i style={{ width: '100%' }} /></span></button>{ipoRuns.map((run) => <div key={run.run_id} className={`research-run-card-wrap ${!allRunsSelected && !allIpoRunsSelected && activeRun?.run_id === run.run_id ? 'active' : ''}`}><button type="button" className={!allRunsSelected && !allIpoRunsSelected && activeRun?.run_id === run.run_id ? 'active' : ''} onClick={() => { setAllRunsSelected(false); setAllIpoRunsSelected(false); setResultScope('run'); setActiveRun(run); setTab('ipo'); }}><span className="research-run-card-top"><b>{run.name}</b><em className={`run-${run.status}`}>{run.status}</em></span><span className="research-run-card-metrics"><small><strong>{run.symbols_completed}/{run.symbols_total}</strong> IPO stocks</small><small><strong>{runScansDone(run).toLocaleString()}</strong> scans · {runStrategyCount(run)} strategies</small></span><span className="research-run-card-progress"><i style={{ width: `${Math.max(0, Math.min(100, run.progress_pct || 0))}%` }} /></span></button><button type="button" className="research-run-delete-action" disabled={archiveBusyId === run.run_id} onClick={(event) => { event.stopPropagation(); void deleteIpoRun(run.run_id, run.name); }}>{archiveBusyId === run.run_id ? 'Deleting…' : 'Delete'}</button></div>)}</div>
    </section>}

    <section className="research-layout">
      <main className="research-main">
        <details className="research-new-run" open={!activeRun}>
          <summary><span><b>New research run</b><small>Name it, select the universe and strategies, then leave it running safely in the background.</small></span><strong>Configure</strong></summary>
          <form onSubmit={startRun}>
            <div className="research-form-grid"><label>Run name<input value={name} onChange={(e) => setName(e.target.value)} required /></label><label>History<select value={historyMode} onChange={(e) => setHistoryMode(e.target.value as 'all_available' | 'custom')}><option value="all_available">All available history (default)</option><option value="custom">Custom date range</option></select><small>{historyMode === 'all_available' ? 'Uses up to 20 years and each stock’s earliest available session.' : 'Use only when comparing an exact market period.'}</small></label>{historyMode === 'custom' && <><label>Start<input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} required /></label><label>End<input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} required /></label></>}<label>Universe<select value={ordinaryOnly ? 'ordinary' : 'all'} onChange={(e) => setOrdinaryOnly(e.target.value === 'ordinary')}><option value="ordinary">Ordinary shares only</option><option value="all">All instrument classes</option></select></label><label>Listing age<select value={maxListingAgeDays} onChange={(e) => { setMaxListingAgeDays(e.target.value); if (e.target.value) setOrdinaryOnly(true); }}><option value="">All listing ages</option><option value="30">Brand new · up to 30 days</option><option value="60">First two months · up to 60 days</option><option value="90">Newly listed · up to 90 days</option><option value="180">Early aftermarket · up to 180 days</option><option value="365">Recent IPO · up to 1 year</option><option value="730">Young listing · up to 2 years</option><option value="1095">Up to 3 years</option></select><small>You choose the age window. Tier-1 strategies recommend 90 / 180 / 365 / 730 — change freely and re-queue to compare.</small></label><label>Stocks to test<select value={runScope} onChange={(e) => { setRunScope(e.target.value as 'all' | 'single'); setSelectedStock(null); setStockSearch(''); }}><option value="all">All stocks in universe</option><option value="single">One particular stock</option></select></label><label>Strategy source<select value={strategyMode} onChange={(e) => setStrategyMode(e.target.value as 'presets' | 'custom' | 'discovery')}><option value="presets">Professional presets</option><option value="discovery">Adaptive combination discovery</option><option value="custom">One custom query</option></select></label>{strategyMode === 'discovery' && <label>Candidate budget<input type="number" min="10" max="10000" step="1" value={discoveryBudget} onChange={(e) => setDiscoveryBudget(e.target.value)} /><small>Reproducible sample from a 50M+ search space.</small></label>}<label>Minimum hold (days)<input type="number" min="0" max="365" step="1" value={minHoldingDays} onChange={(e) => setMinHoldingDays(e.target.value)} /><small>Default 5 days; type another value to override it for this run.</small></label><label>Maximum hold (days)<input type="number" min="1" max="365" step="1" value={maxHoldingDays} onChange={(e) => setMaxHoldingDays(e.target.value)} /><small>Default 90 days; you can change it.</small></label></div>
            <div className={`ipo-research-setup ${ipoResearchMode ? 'active' : ''}`}>
              <span>
                <b>New IPO aftermarket research {ipoResearchMode ? '· separate workspace active' : ''}</b>
                <small>Buy rule is fixed for every IPO strategy: wait for a completed red candle (close &lt; open), then allow entries only on later sessions — never on that red day. Listing age, holds, and which Tier-1 strategies to run are yours to choose.</small>
              </span>
              <div>
                <button type="button" className={ipoResearchMode ? 'active' : ''} onClick={() => {
                  setIpoResearchMode((current) => !current);
                  if (!ipoResearchMode && !maxListingAgeDays) { setMaxListingAgeDays('365'); setOrdinaryOnly(true); }
                }}>{ipoResearchMode ? 'Use standard workspace' : 'Use separate IPO workspace'}</button>
                <button type="button" disabled={tier1IpoPresetIds.length === 0} onClick={() => applyTier1IpoResearchSetup(maxListingAgeDays || '365')}>Load Tier-1 pack · {tier1IpoPresetIds.length || 4}</button>
                <button type="button" disabled={newIpoPresetIds.length === 0} onClick={useNewIpoResearchSetup}>Load all IPO presets · {newIpoPresetIds.length}</button>
              </div>
              {ipoResearchMode && <div className="ipo-age-quick-picks" role="group" aria-label="IPO listing age shortcuts">
                <span>Listing age</span>
                {(['90', '180', '365', '730'] as const).map((days) => (
                  <button
                    type="button"
                    key={days}
                    className={maxListingAgeDays === days ? 'active' : ''}
                    onClick={() => { setMaxListingAgeDays(days); setOrdinaryOnly(true); }}
                  >≤{days}d</button>
                ))}
              </div>}
            </div>
            {runScope === 'single' && <div className="stock-picker"><label>Find stock by symbol or company name<input value={stockSearch} onChange={(e) => { setStockSearch(e.target.value.toUpperCase()); setSelectedStock(null); }} placeholder="Type NABIL or Nabil Bank…" autoComplete="off" required /></label>{selectedStock && <div className="selected-stock"><b>{selectedStock.symbol}</b><span>{selectedStock.company_name}</span><em>{selectedStock.sector || 'Sector unavailable'}</em></div>}{stockSuggestions.length > 0 && <div className="stock-suggestions" role="listbox">{stockSuggestions.map((item) => <button type="button" role="option" aria-selected={selectedStock?.symbol === item.symbol} key={item.symbol} onClick={() => { setSelectedStock(item); setStockSearch(item.symbol); setStockSuggestions([]); setName(`${item.symbol} strategy research`); }}><b>{item.symbol}</b><span>{item.company_name}</span><em>{item.sector || ''}</em></button>)}</div>}<small>All selected presets will run only on the chosen stock. This does not affect saved all-market runs.</small></div>}
            {strategyMode !== 'custom' ? <><div className="research-preset-head"><span><b>{strategyMode === 'discovery' ? 'Base signal catalog' : 'Preset catalog'}</b><small>{selected.size}/{presets.length} selected · grouped by family</small></span><div><button type="button" onClick={() => setSelected(new Set(presets.map((item) => item.id)))}>All {presets.length}</button><button type="button" onClick={() => setSelected(new Set())}>Clear</button></div></div>{strategyMode === 'discovery' && <div className="research-alert">Combines two or three selected signals and searches stop, target, minimum-hold, and maximum-hold settings. Stable hashes prevent duplicate testing.</div>}<div className="research-preset-groups">{grouped.map(([category, items]) => <details key={category}><summary>{category}<span>{items.filter((item) => selected.has(item.id)).length}/{items.length}</span></summary><div>{items.map((preset) => <label key={preset.id} title={preset.description}><input type="checkbox" checked={selected.has(preset.id)} onChange={() => setSelected((current) => { const next = new Set(current); next.has(preset.id) ? next.delete(preset.id) : next.add(preset.id); return next; })} /><span>{preset.name}</span></label>)}</div></details>)}</div></> : <div className="research-custom-query"><div><span><b>Custom Strategy Language</b><small>The symbol in this query is a template. For an all-stock run, the server safely retargets only the symbol and keeps every condition, risk setting, charge, and order-sizing rule unchanged.</small></span><button type="button" onClick={() => void copyGptPrompt()}>Copy prompt for GPT</button>{copyStatus && <em>{copyStatus}</em>}</div><textarea value={customQuery} onChange={(e) => setCustomQuery(e.target.value)} rows={20} spellCheck={false} /></div>}
            <div className="research-submit"><p>History is cached per stock. Scans use a low-priority background worker so normal trading and dashboard requests stay responsive. The exact versioned query is stored with every result and can be promoted to paper, then separately confirmed for live scheduling.</p><button disabled={creating || (strategyMode === 'custom' ? customQuery.trim().length < 20 : selected.size === 0)}>{creating ? 'Queuing…' : strategyMode === 'custom' ? `Queue query on ${runScope === 'all' ? 'all stocks' : selectedStock?.symbol || 'one stock'}` : strategyMode === 'discovery' ? `Discover ${Number(discoveryBudget || 0).toLocaleString()} combinations` : `Queue ${selected.size} strategies`}</button></div>
          </form>
        </details>

        {activeRun && <>
          <section className="research-run-head"><div><span className={allRunsSelected ? 'run-completed' : `run-${activeRun.status}`}>{allRunsSelected ? 'combined research' : activeRun.cancel_requested ? 'cancelling' : activeRun.pause_requested ? 'pausing' : activeRun.status}</span><h2>{allRunsSelected ? 'All runs · unique simulation configurations' : activeRun.name}</h2><p>{allRunsSelected ? 'Every workspace combined · only exact symbol, strategy, risk, holding, cost, sizing, and engine configurations are merged' : `${activeRun.configuration.start_date} → ${activeRun.configuration.end_date} · ordinary shares ${activeRun.configuration.ordinary_shares_only ? 'default' : 'not restricted'}${activeRun.configuration.max_listing_age_days ? ` · listing age ≤${activeRun.configuration.max_listing_age_days} days` : ''}`}</p>{!allRunsSelected && runControlMessage && <span role="status" aria-live="polite" className={`run-control-feedback ${activeRun.status === 'paused' || activeRun.status === 'cancelled' ? 'confirmed' : ''}`}>{runControlMessage}</span>}</div>{!allRunsSelected && <div className="research-controls">{activeRun.status === 'running' && <button disabled={Boolean(runControlBusy || activeRun.pause_requested || activeRun.cancel_requested)} onClick={() => void control('pause')}>{runControlBusy === 'pause' || activeRun.pause_requested ? 'Pausing…' : 'Pause'}</button>}{activeRun.status === 'paused' && <button disabled={Boolean(runControlBusy || activeRun.cancel_requested)} onClick={() => void control('resume')}>{runControlBusy === 'resume' ? 'Resuming…' : 'Resume'}</button>}{activeRun.status === 'failed' && <button disabled={Boolean(runControlBusy)} onClick={() => void control('retry')}>{runControlBusy === 'retry' ? 'Retrying…' : 'Retry failed'}</button>}{['queued', 'running', 'paused'].includes(activeRun.status) && <button disabled={Boolean(runControlBusy || activeRun.cancel_requested)} className="danger" onClick={() => void control('cancel')}>{runControlBusy === 'cancel' || activeRun.cancel_requested ? 'Cancelling…' : 'Cancel'}</button>}{isIpoRun(activeRun) && <button disabled={Boolean(runControlBusy || archiveBusyId === activeRun.run_id)} className="danger" onClick={() => void deleteIpoRun(activeRun.run_id, activeRun.name)}>{archiveBusyId === activeRun.run_id ? 'Deleting…' : 'Delete from DB'}</button>}</div>}</section>
          {!allRunsSelected && activeRun && <section className={`research-progress ${['running', 'queued'].includes(activeRun.status) ? 'is-active' : ''}`}>
            <div className="research-progress-meta">
              <b>{Number(activeRun.progress_pct || 0).toFixed(1)}%</b>
              <span>{activeRun.symbols_completed}/{activeRun.symbols_total} stocks</span>
              <span>{isIpoRun(activeRun)
                ? `${runScansDone(activeRun).toLocaleString()} scans done · ${activeRun.combinations_completed.toLocaleString()} cached`
                : `${activeRun.combinations_completed.toLocaleString()} persisted results`}</span>
              <span className="research-progress-symbol">{activeRun.current_symbol || 'Waiting for next checkpoint'}</span>
              <span className="research-progress-eta" title={scanEta.detail || undefined}>
                <strong>{scanEta.label}</strong>
                {scanEta.detail ? <small>{scanEta.detail}</small> : null}
              </span>
            </div>
            <div
              className="research-progress-track"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.max(0, Math.min(100, Number(activeRun.progress_pct || 0)))}
              aria-label="Scan progress"
            >
              <i style={{ width: `${Math.max(0, Math.min(100, Number(activeRun.progress_pct || 0)))}%` }} />
            </div>
            <small>Scan progress updates in the background. Estimated time updates as each stock finishes. The result table stays stable while you analyse it; use Refresh new scan results when you want the latest checkpoint.</small>
          </section>}
          <nav className="research-tabs">{([
            ['combinations', 'All results'],
            ...(isIpoRun(activeRun) ? [['ipo', 'IPO testing']] : []),
            ['portfolio', 'Portfolio'], ['ai', 'Ask AI'], ['quality', 'Data quality'],
          ] as Array<[typeof tab, string]>).map(([key, label]) => <button key={key} className={tab === key ? 'active' : ''} onClick={() => setTab(key)}>{label}</button>)}<a href="/dashboard/recommendations">Open live recommendations ↗</a></nav>

          {tab === 'opportunities' && <section className="research-panel strong-buy-panel">
            <div className="research-panel-title recommendation-title"><div><span className="current-session-badge">Fresh, deduplicated market view</span><h3>Best stock recommendations across all research</h3><p>One best strategy per stock across every compatible run. Duplicate stock/strategy results are merged and older trading sessions are excluded.</p></div><div className="freshness-card"><small>Latest completed trading session</small><strong>{opportunities.freshness?.latest_completed_session || 'Checking…'}</strong><span>Refreshes at 10:00 and 11:00 Nepal time</span></div></div>
            {activeRun?.symbols_total === 1 && <div className="single-stock-explainer"><span><b>{activeRun.combinations_completed.toLocaleString()} strategies were tested for this stock.</b> Recommendations keeps its best strategy; Combinations contains every result.</span><button type="button" onClick={() => setTab('combinations')}>View all {activeRun.combinations_completed.toLocaleString()} strategies</button></div>}
            <details className="recommendation-tools">
              <summary><span><b>Filters and sorting</b><small>Open when you want to narrow the fresh market list.</small></span><strong>{appliedOpportunityFilters.length ? `${appliedOpportunityFilters.length} active` : 'Optional'}</strong></summary>
              <div className="strong-buy-filters">
              <label>Min trades<input type="number" min="0" value={opportunityFilters.minimum_trades} onChange={(e) => setOpportunityFilters((v) => ({ ...v, minimum_trades: e.target.value }))} /></label>
              <label>Min historical win %<input type="number" min="0" max="100" value={opportunityFilters.minimum_win_rate} onChange={(e) => setOpportunityFilters((v) => ({ ...v, minimum_win_rate: e.target.value }))} /></label>
              <label>Min confidence<input type="number" min="0" max="100" value={opportunityFilters.minimum_confidence} onChange={(e) => setOpportunityFilters((v) => ({ ...v, minimum_confidence: e.target.value }))} /></label>
              <label>Min Sharpe<input type="number" step=".1" value={opportunityFilters.minimum_sharpe} onChange={(e) => setOpportunityFilters((v) => ({ ...v, minimum_sharpe: e.target.value }))} /></label>
              <label>Min profit factor<input type="number" step=".1" min="0" value={opportunityFilters.minimum_profit_factor} onChange={(e) => setOpportunityFilters((v) => ({ ...v, minimum_profit_factor: e.target.value }))} /></label>
              <label>Max drawdown %<input type="number" min="0" max="100" value={opportunityFilters.maximum_drawdown} onChange={(e) => setOpportunityFilters((v) => ({ ...v, maximum_drawdown: e.target.value }))} /></label>
              <label>Min return %<input type="number" value={opportunityFilters.minimum_return} onChange={(e) => setOpportunityFilters((v) => ({ ...v, minimum_return: e.target.value }))} /></label>
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
            <div className="research-table-wrap strong-buy-table"><table><thead><tr>{opportunityColumns.map((column) => { const sortIndex = opportunitySorts.findIndex((item) => item.field === column.sortKey); const ariaSort = sortIndex === 0 ? (opportunitySorts[0].direction === 'desc' ? 'descending' : 'ascending') : undefined; return <th key={column.key} aria-sort={ariaSort}>{column.sortKey ? <button type="button" className={`recommendation-sort-button ${sortIndex >= 0 ? 'active' : ''}`} title="Click for primary sort; Shift-click to add a sorting rule" onClick={(event) => toggleOpportunitySort(column.sortKey!, event.shiftKey)}>{column.label}<span>{opportunitySortMarker(column.sortKey)}</span></button> : column.label}</th>; })}</tr></thead><tbody>{opportunities.items.map((row) => <tr key={row.result_id}><td>{row.rank}</td><td><div className="stock-chart-links"><button className="symbol-link" onClick={() => openOpportunityPage(row)}>{row.symbol}</button><NepseAlphaSymbolLink symbol={row.symbol}>Chart ↗</NepseAlphaSymbolLink></div></td><td><span className={`signal-pill ${row.current_signal_status}`}>{signalLabel(row.current_signal_status)}</span></td><td><button type="button" className="result-detail-link" onClick={() => openOpportunityPage(row)}>{row.preset_name}</button></td><td><b>{fmt(row.recommendation_score, 'score')}</b></td><td className="price-zone buy-zone">{row.buy_zone_low ? `NPR ${fmt(row.buy_zone_low, 'money')}–${fmt(row.buy_zone_high, 'money')}` : 'No current entry'}</td><td className="price-zone stop-zone">{row.protective_stop ? `NPR ${fmt(row.protective_stop, 'money')}` : '—'}</td><td className="price-zone sell-zone">{row.sell_zone_low ? `NPR ${fmt(row.sell_zone_low, 'money')}–${fmt(row.sell_zone_high, 'money')}` : '—'}</td><td>{fmt(row.ltp, 'ltp')}</td><td>{row.signal_date}</td><td><b>{fmt(row.win_rate_pct, 'percent')}%</b></td><td>{row.total_trades}</td><td>{fmt(row.average_holding_days, 'days')} days</td><td>{fmt(row.net_return_pct, 'percent')}%</td><td>{fmt(row.max_drawdown_pct, 'percent')}%</td><td>{fmt(row.average_volume_20, 'average_volume_20')}</td><td>{fmt(row.latest_volume, 'latest_volume')}</td><td><button className="view-evidence" onClick={() => openOpportunityPage(row)}>Details</button></td></tr>)}</tbody></table>{opportunities.items.length === 0 && <div className="research-empty">No fresh ordinary-share recommendation matches these exact filters. The application does not substitute older trading sessions or silently weaken filters.</div>}</div>
            <div className="research-pagination"><button disabled={opportunities.page <= 1} onClick={() => void loadOpportunities(opportunities.page - 1)}>Previous</button><span>Page {opportunities.page} of {opportunities.pages || 1}</span><button disabled={opportunities.page >= opportunities.pages} onClick={() => void loadOpportunities(opportunities.page + 1)}>Next</button></div>
            <p className="strong-buy-disclaimer">Backtested historical performance does not guarantee future results. This is research, not financial advice, and never places a broker order.</p>
          </section>}

          {tab === 'combinations' && <section className="research-panel">
            <section className="result-filter-builder" aria-label="Custom backtest result filters">
              <div className="result-filter-heading"><div><h3>Find the best results</h3><p>{isIpoRun(activeRun) ? 'Only IPO simulations with at least one completed trade are ranked here. Zero-trade rows are hidden because a 0% win rate with no trades is not meaningful. They remain excluded from normal recommendations.' : 'Every scanned combination in this workspace is shown by default. Filters update automatically; click a table heading to rank the matches.'}</p></div><div><label>View<select value={resultScope} onChange={(event) => { const scope = event.target.value as 'run' | 'all' | 'strategies' | 'holistic'; setResultScope(scope); setAllRunsSelected(scope !== 'run'); }}><option value="run">Selected scan · all results</option>{!isIpoRun(activeRun) && <><option value="strategies">All runs · unique configurations</option><option value="all">All runs · complete history</option><option value="holistic">All runs · best per stock</option></>}</select></label><label>Logic<select value={resultFilterJoin} onChange={(event) => setResultFilterJoin(event.target.value as 'and' | 'or')}><option value="and">Match all</option><option value="or">Match any</option></select></label><label>Stocks<select value={includeNonEquities ? 'all' : 'ordinary'} onChange={(e) => setIncludeNonEquities(e.target.value === 'all')}><option value="ordinary">Ordinary shares</option><option value="all">All instruments</option></select></label><label>Show<select value={results.page_size} onChange={(e) => setResults((current) => ({ ...current, page_size: Number(e.target.value) }))}><option>25</option><option>50</option><option>100</option></select></label></div></div>
              <datalist id="result-symbol-suggestions">{resultSymbolSuggestions.map((item) => <option key={item.symbol} value={item.symbol}>{item.company_name}{item.sector ? ` · ${item.sector}` : ''}</option>)}</datalist>
              <div className="result-quick-filters"><span>Add filter</span><button type="button" onClick={() => addResultFilter('symbol')}>Stock</button><button type="button" onClick={() => addResultFilter('current_signal_status', '', 'eq')}>Signal</button><button type="button" onClick={() => addResultFilter('sector')}>Sector</button><button type="button" onClick={() => addResultFilter('preset_name', '', 'eq')}>Strategy preset</button><button type="button" onClick={() => addResultFilter('total_trades')}>Trades</button><button type="button" onClick={() => addResultFilter('min_holding_days', '5', 'eq')}>Min hold</button><button type="button" onClick={() => addResultFilter('max_holding_days', '90', 'eq')}>Max hold</button><button type="button" onClick={() => addResultFilter('latest_volume')}>Volume</button></div>
              <div className="result-filter-presets"><span>Popular rules</span>{isIpoRun(activeRun) ? <button type="button" onClick={() => addResultFilter('total_trades', '1')}>1+ trades</button> : <button type="button" onClick={() => addResultFilter('total_trades', '20')}>20+ trades</button>}<button type="button" onClick={() => addResultFilter('oos_trades', '10')}>10+ OOS trades</button><button type="button" onClick={() => addResultFilter('robust_score', '60')}>Robust 60+</button><button type="button" onClick={() => addResultFilter('win_rate_pct', '55')}>Win rate 55%+</button><button type="button" onClick={() => addResultFilter('profit_factor', '1.5')}>Profit factor 1.5+</button><button type="button" onClick={() => addResultFilter('max_drawdown_pct', '25', 'lte')}>Drawdown ≤25%</button></div>
              {resultFilterRows.length === 0 ? <p className="result-filter-empty">No custom conditions. All matching ordinary-share simulations are shown.</p> : <div className="result-filter-rows">{resultFilterRows.map((item) => {
                const field = resultFilterFields.find((candidate) => candidate.field === item.field) || resultFilterFields[0];
                const operators = field.type === 'number' ? numericFilterOperators : textFilterOperators;
                return <div className="result-filter-row" key={item.id}>
                  <select aria-label="Filter field" value={item.field} onChange={(event) => { const next = resultFilterFields.find((candidate) => candidate.field === event.target.value) || resultFilterFields[0]; updateResultFilter(item.id, { field: next.field, operator: next.type === 'number' ? 'gte' : 'contains', value: '' }); }}><optgroup label="Available backtest fields">{resultFilterFields.map((candidate) => <option key={candidate.field} value={candidate.field}>{candidate.label}</option>)}</optgroup></select>
                  <select aria-label="Filter operator" value={item.operator} onChange={(event) => updateResultFilter(item.id, { operator: event.target.value })}>{operators.map((operator) => <option key={operator.value} value={operator.value}>{operator.label}</option>)}</select>
                  {field.field === 'sector' ? <select aria-label="Sector value" value={item.value} onChange={(event) => updateResultFilter(item.id, { value: event.target.value })}><option value="">Select sector…</option>{resultSectors.map((sector) => <option key={sector} value={sector}>{sector}</option>)}</select> : field.field === 'preset_name' ? <select aria-label="Strategy preset value" value={item.value} onChange={(event) => updateResultFilter(item.id, { value: event.target.value })}><option value="">Select strategy preset…</option>{presets.map((preset) => <option key={preset.id} value={preset.name}>{preset.name} · {preset.family}</option>)}</select> : field.options ? <select aria-label={`${field.label} value`} value={item.value} onChange={(event) => updateResultFilter(item.id, { value: event.target.value })}><option value="">Select value…</option>{field.options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select> : <input aria-label={`${field.label} value`} type={field.type === 'number' ? 'number' : 'text'} list={field.field === 'symbol' ? 'result-symbol-suggestions' : undefined} value={item.value} placeholder={field.field === 'symbol' ? 'Type symbol or company name…' : 'Enter value…'} onChange={(event) => { updateResultFilter(item.id, { value: event.target.value }); if (field.field === 'symbol') suggestResultSymbols(event.target.value); }} />}
                  <button type="button" className="remove-filter" aria-label={`Remove ${field.label} filter`} onClick={() => setResultFilterRows((current) => current.filter((row) => row.id !== item.id))}>×</button>
                </div>;
              })}</div>}
              {resultsBusy && <div className="result-filter-progress" role="status" aria-live="polite"><i /><span>{resultFilterStatus}</span></div>}
              <footer>{!resultsBusy && <span>{`${appliedResultFilters.length} active condition${appliedResultFilters.length === 1 ? '' : 's'} · ${resultFilterJoin.toUpperCase()} · stable at this checkpoint`}</span>}<div><button type="button" className="secondary" disabled={resultsBusy || filteredRefreshBusy} onClick={() => void refreshFilteredResults()}>{filteredRefreshBusy ? 'Queuing filtered refresh…' : 'Refresh filtered data'}</button><button type="button" className="secondary" disabled={resultsBusy} onClick={() => void loadResults(1)}>Reload scan results</button><button type="button" className="secondary" disabled={resultsBusy} onClick={resetResultFilters}>Reset filters</button></div></footer>
            </section>
            <div className="recommendation-sort-guide"><span><b>Multi-column ranking:</b> click a heading to make it primary and toggle ↓/↑. Hold Shift while clicking to add or change a secondary rule.</span><button type="button" onClick={() => setResultSorts([{ field: 'win_rate_pct', direction: 'desc' }])}>Reset to win rate</button></div>
            <div className="research-table-summary"><div><b>{results.total.toLocaleString()} {isIpoRun(activeRun) ? (ipoShowZeroTrades ? 'IPO cached simulations' : 'IPO outcomes with trades') : resultScope === 'holistic' ? 'unique stocks across all runs' : resultScope === 'strategies' ? 'unique simulation configurations across all runs' : resultScope === 'all' ? 'historical results across all runs' : 'results from this run'}</b><span>{isIpoRun(activeRun) ? (ipoShowZeroTrades ? `Raw IPO cache view · ${(results.trade_outcomes || 0).toLocaleString()} with trades · ${(results.zero_trade_outcomes || 0).toLocaleString()} with zero trades. Use Reset filters to return to the 1+ trade ranking.` : `Zero-trade simulations are hidden from this ranking${results.cached_total ? ` · ${(results.cached_total || 0).toLocaleString()} cached · ${(results.trade_outcomes || 0).toLocaleString()} with trades` : ''}. Remaining sparse outcomes are research-only and are not retained recommendations.`) : resultScope === 'holistic' ? 'Best validated result per stock · duplicate runs removed' : resultScope === 'strategies' ? 'Exact duplicates only: symbol + complete entry/exit strategy + holding/risk/cost/sizing settings + engine versions' : resultScope === 'all' ? 'Complete cached stock × strategy history across every run' : 'Every scanned stock × strategy combination in the selected workspace'} · {resultSorts.map((item, index) => `${index + 1}. ${resultColumnLabel(item.field)} ${item.direction === 'desc' ? '↓' : '↑'}`).join(' · ')}</span></div><div className="research-table-actions"><button type="button" className="research-columns-button" onClick={() => setColumnPickerOpen(true)}>Columns <b>{activeResultColumns.length}/{RESULT_COLUMNS.length}</b></button>{isIpoRun(activeRun) ? <button type="button" className="csv-download-icon" aria-label={exporting ? 'Preparing CSV download' : 'Download IPO results CSV'} title={exporting ? 'Preparing…' : 'Download CSV'} disabled={exporting || results.total <= 0} onClick={() => void downloadCsv('run')}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v10.2M8.2 9.8 12 13.6l3.8-3.8M5 18.5h14" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" /></svg>{exporting ? '…' : null}</button> : <div className="csv-export-control"><label><span>CSV dataset</span><select value={exportScope} onChange={(event) => setExportScope(event.target.value as 'run' | 'all')}><option value="run">This run · current filters</option><option value="all">All my cached backtests</option></select></label><button type="button" disabled={exporting} onClick={() => void downloadCsv(exportScope)}>{exporting ? 'Preparing download…' : '↓ Download CSV'}</button>{exportStatus && <small>{exportStatus}</small>}</div>}</div></div>
            <div className={`research-table-wrap ${resultsBusy ? 'is-loading' : ''}`} aria-busy={resultsBusy}><table><thead><tr>{activeResultColumns.map(({ key, label }) => { const sortIndex = resultSorts.findIndex((item) => item.field === key); const categorical = isCategoricalColumn(results.items, key); return <th key={key} aria-sort={!categorical && sortIndex === 0 ? (resultSorts[0].direction === 'desc' ? 'descending' : 'ascending') : undefined}>{categorical ? <CategoricalHeaderFilter label={label} values={uniqueCategoricalValues(results.items, key)} selectedValue={resultHeaderCategoricalFilters[key]} disabled={resultsBusy} onChange={(value) => setResultHeaderCategoricalFilters((current) => ({ ...current, [key]: value }))} /> : <button type="button" className={`recommendation-sort-button ${sortIndex >= 0 ? 'active' : ''}`} disabled={resultsBusy} title="Click for primary sort; Shift-click to add a sorting rule" onClick={(event) => toggleResultSort(key, event.shiftKey)}>{label}<span>{resultSortMarker(key)}</span></button>}</th>; })}</tr></thead><tbody>{visibleResultRows.map((row) => { return <tr key={row.result_id} className={row.recommendation_status === 'recommended' ? 'recommended' : ''}>{activeResultColumns.map(({ key }) => <td key={key}>{key === 'symbol' ? <div className="stock-chart-links"><button type="button" className="symbol-link" title={`View ${row.symbol} backtest details`} onClick={() => openOpportunityPage(row as Opportunity & { cache_key?: string })}>{row.symbol}</button><NepseAlphaSymbolLink symbol={row.symbol}>Chart ↗</NepseAlphaSymbolLink></div> : key === 'preset_name' ? <button type="button" className="result-detail-link" title={`View ${row.preset_name} details`} onClick={() => openOpportunityPage(row as Opportunity & { cache_key?: string })}>{row.preset_name}</button> : key === 'current_signal_status' ? <span className={`signal-pill ${row.current_signal_status}`}>{signalLabel(row.current_signal_status)}</span> : key === 'robust_score' ? <span className={`score score-${Math.floor(Number(row[key] || 0) / 20)}`}>{fmt(row[key], key)}</span> : fmt(row[key], key)}</td>)}</tr>; })}</tbody></table>{resultsBusy && <div className="result-table-loading"><span className="filter-spinner" />Ranking exact matches…</div>}{!resultsBusy && visibleResultRows.length === 0 && <div className="research-empty">{results.items.length ? 'No rows on this page match the selected header values.' : isIpoRun(activeRun) && Number(results.cached_total || 0) > 0 && Number(results.trade_outcomes || 0) === 0 ? <><p>{Number(results.cached_total || 0).toLocaleString()} simulations are cached, but every completed stock so far produced zero trades (for example a brand-new listing with only a few sessions). Trade-bearing rows appear as longer-history IPO stocks finish.</p><button type="button" className="secondary" onClick={() => { appliedResultFilterSignature.current = JSON.stringify([]); nextResultFilterId.current = 1; setResultFilterRows([]); setAppliedResultFilters([]); setIpoShowZeroTrades(true); }}>Show cached zero-trade simulations</button></> : 'No result matches these exact filters. Filters were not silently weakened.'}</div>}</div>
            <div className="research-pagination"><button disabled={resultsBusy || results.page <= 1} onClick={() => void loadResults(results.page - 1)}>Previous</button><span>{resultsBusy ? 'Loading exact page…' : `Page ${results.page} of ${results.pages || 1}`}</span><button disabled={resultsBusy || results.page >= results.pages} onClick={() => void loadResults(results.page + 1)}>Next</button></div>
          </section>}

          {tab === 'portfolio' && <section className="research-panel"><div className="research-panel-title"><div><h3>Shared-capital strategy leaderboard</h3><p>One cash balance · max 10 positions · 10% per stock · 30% per sector · 5% reserve.</p></div></div><div className="portfolio-grid">{portfolios.map((item) => <article key={item.preset_id}><span>{item.preset_name}</span><strong className={item.summary.net_return_pct >= 0 ? 'positive' : 'negative'}>{fmt(item.summary.net_return_pct, 'return')}%</strong><dl><div><dt>Final equity</dt><dd>NPR {fmt(item.summary.final_equity, 'money')}</dd></div><div><dt>Drawdown</dt><dd>{fmt(item.summary.max_drawdown_pct, 'percent')}%</dd></div><div><dt>Accepted</dt><dd>{item.summary.accepted_signals}</dd></div><div><dt>Rejected</dt><dd>{item.summary.rejected_signals}</dd></div></dl></article>)}</div>{portfolios.length === 0 && <div className="research-empty">Portfolio results are finalized after the stock scan completes.</div>}</section>}

          {tab === 'ai' && <section className="research-panel"><div className="research-panel-title"><div><h3>Ask AI for the top 10</h3><p>Search every cached strategy result using a validated, column-selecting SQL query.</p></div><label>Search scope<select value={aiScope} onChange={(e) => setAiScope(e.target.value as 'all' | 'run')}><option value="all">All my backtest data</option><option value="run">Current run only</option></select></label></div><div className="ai-backtest-presets" aria-label="AI backtest prompt presets">{aiBacktestPresets.map((prompt, index) => <button type="button" key={prompt} onClick={() => setAiQuestion(prompt)}><b>Preset {index + 1}</b><span>{prompt}</span></button>)}</div><div className="ai-query"><textarea rows={4} value={aiQuestion} onChange={(e) => setAiQuestion(e.target.value)} placeholder="Describe the stocks, strategies, columns, risk limits, and ranking you want…" /><button disabled={aiBusy} onClick={() => void askAi()}>{aiBusy ? 'Validating…' : 'Run AI SQL + top 10'}</button></div>{aiAnswer && <><p>{aiAnswer.explanation}</p><p><b>{aiAnswer.recommendation_summary}</b></p>{aiAnswer.total_matches === 0 && <div className="research-alert">No exact matches. {aiAnswer.suggested_relaxations.join(' ')}</div>}<div className="research-table-wrap"><table><thead><tr>{(aiAnswer.selected_columns || []).map((key: string) => <th key={key}>{columns.find((item) => item.key === key)?.label || key.replaceAll('_', ' ')}</th>)}<th>Why it matched</th></tr></thead><tbody>{aiAnswer.items.map((row: ResultRow) => <tr key={row.result_id}>{(aiAnswer.selected_columns || []).map((key: string) => <td key={key}>{fmt(row[key], key)}</td>)}<td>{(row.match_reasons || []).join(' · ')}</td></tr>)}</tbody></table></div></>}</section>}

          {tab === 'ipo' && <section className="ipo-testing-tab">
            <header className="ipo-testing-header"><div><span>Separate IPO research workspace</span><h2>New IPO common-pattern laboratory</h2><p>Compare every young listing on one normalized graph, then require a strategy to repeat across stocks, lifecycle stages, and its first three eligible entries.</p></div><strong>{ipoStrategySummary?.ipo_price_paths?.length || activeRun.symbols_total}<small> IPO paths</small></strong></header>
            {allIpoRunsSelected && <section className="research-panel ipo-all-runs-view"><div className="ipo-stock-path-heading"><div><h3>All IPO runs</h3><p>Every IPO workspace remains separate so different constraints are never blended. Open a run to inspect its exact strategy version and trade charts.</p></div><strong>{ipoRuns.length}<small> workspaces</small></strong></div><div className="ipo-all-runs-grid">{ipoRuns.map((run) => <button type="button" key={run.run_id} className={activeRun.run_id === run.run_id ? 'active' : ''} onClick={() => setActiveRun(run)}><span><b>{run.name}</b><em className={`run-${run.status}`}>{run.status}</em></span><small>{run.symbols_completed}/{run.symbols_total} IPO stocks · {runScansDone(run).toLocaleString()} scans · {runStrategyCount(run)} strategies</small><i><u style={{ width: `${Math.max(0, Math.min(100, run.progress_pct || 0))}%` }} /></i></button>)}</div></section>}
            {ipoStrategySummary ? <><IpoResearchCharts summary={ipoStrategySummary} /><IpoStockPathGrid paths={ipoStrategySummary.ipo_price_paths} /><IpoStrategyCards summary={ipoStrategySummary} runId={activeRun.run_id} /></> : <div className="research-empty">IPO charts and pooled rankings appear as the separate scan checkpoints its trade evidence.</div>}
            <p className="strong-buy-disclaimer">Common historical behavior is probabilistic evidence, not a prediction or guaranteed profit. Never promote an IPO strategy using win rate alone; review stock coverage, trade count, costs, drawdown, and regime stability.</p>
          </section>}

          {tab === 'quality' && <><section className="research-panel quality-grid"><article><b>Universe snapshot</b><strong>{activeRun.symbols_total}</strong><p>Instrument membership is frozen when the run starts.</p></article><article><b>Completed symbols</b><strong>{activeRun.symbols_completed}</strong><p>Each completion is checkpointed for restart recovery.</p></article><article><b>Ordinary-share enforcement</b><strong>{activeRun.configuration.ordinary_shares_only ? 'On' : 'Explicitly off'}</strong><p>Non-equities stay excluded at the API unless explicitly requested.</p></article><article><b>Validation split</b><strong>70 / 30</strong><p>The newest 30% of sessions are locked for out-of-sample metrics.</p></article></section>{isIpoRun(activeRun) && ipoStrategySummary && <section className="research-panel ipo-strategy-summary"><div><h3>Cross-stock IPO strategy ranking</h3><p>{ipoStrategySummary.candidate_rule} {ipoStrategySummary.qualification_rule}</p><small>{ipoStrategySummary.regime_method}</small></div><div className="ipo-strategy-summary-grid">{ipoStrategySummary.items.map((item) => {
            const bullish = item.market_proxy_regimes?.bullish;
            const bearish = item.market_proxy_regimes?.bearish;
            const exitParts = [
              item.exit_rule_id ? item.exit_rule_id.replaceAll('_', ' ') : null,
              item.stop_loss_pct != null ? `${item.stop_loss_pct}% stop` : null,
              item.take_profit_pct != null ? `${item.take_profit_pct}% target` : null,
              item.trailing_stop_pct != null ? `${item.trailing_stop_pct}% trail` : null,
            ].filter(Boolean);
            const lifecycleLabels = { '0_30': '0–30d', '31_60': '31–60d', '61_90': '61–90d', '91_180': '91–180d', '181_365': '181–365d' };
            const lifecycle = item.lifecycle_windows || {};
            return <article key={item.strategy_id} className={item.cross_stock_qualified ? 'qualified' : ''}><span>{item.cross_stock_qualified ? 'Cross-stock qualified' : 'Candidate evidence'}</span><b>{item.strategy_name}</b><dl><div><dt>Pooled win rate</dt><dd>{item.pooled_win_rate_pct.toFixed(2)}%</dd></div><div><dt>Trades</dt><dd>{item.pooled_wins}/{item.pooled_trades} wins</dd></div><div><dt>Stock coverage</dt><dd>{item.stocks_with_trades}/{item.stocks_tested}</dd></div><div><dt>Most repeatable listing age</dt><dd>{item.best_lifecycle_window ? lifecycleLabels[item.best_lifecycle_window] : 'No trades'}</dd></div>{Object.entries(lifecycle).map(([window, stats]) => <div key={window}><dt>Listed {lifecycleLabels[window as keyof typeof lifecycleLabels]}</dt><dd>{stats.trades ? `${stats.win_rate_pct.toFixed(2)}% · ${stats.trades}` : 'No trades'}</dd></div>)}<div><dt>Bull market proxy</dt><dd>{bullish?.trades ? `${bullish.win_rate_pct.toFixed(2)}% · ${bullish.trades}` : 'No trades'}</dd></div><div><dt>Bear market proxy</dt><dd>{bearish?.trades ? `${bearish.win_rate_pct.toFixed(2)}% · ${bearish.trades}` : 'No trades'}</dd></div><div><dt>Hold observed / tested</dt><dd>{item.average_holding_days != null ? `${item.average_holding_days}d` : '—'} / {item.tested_max_holding_days ? `${item.tested_max_holding_days}d` : '—'}</dd></div><div><dt>Sell protection</dt><dd>{exitParts.join(' · ') || 'Saved strategy exit'}</dd></div></dl></article>;
          })}</div></section>}</>}
        </>}
      </main>
    </section>
    {detailBusy && <div className="detail-loading">Loading complete signal and trade evidence…</div>}
    {selectedOpportunity && <div className={`strong-buy-overlay ${fullPageDetail ? 'full-page' : ''}`} role={fullPageDetail ? undefined : 'dialog'} aria-modal={fullPageDetail ? undefined : 'true'} aria-label="Backtest recommendation details"><div className="strong-buy-drawer">
      <header className="strategy-detail-header"><div className="strategy-detail-identity">{fullPageDetail && <button type="button" className="strategy-detail-back" onClick={() => window.history.back()} aria-label="Return to Backtest Lab">‹ Backtest Lab</button>}<span className="strategy-detail-kicker">Backtest result</span><div className="strategy-detail-title"><h1>{selectedOpportunity.best.symbol}</h1><span className={`signal-pill ${selectedOpportunity.best.current_signal_status}`}>{fmt(selectedOpportunity.best.current_signal_status, 'status')}</span></div><p className="strategy-detail-name">{selectedOpportunity.best.preset_name}</p><p className="strategy-detail-session">Latest completed session: {selectedOpportunity.best.current_signal_date || 'not available'}</p></div><div className="drawer-header-actions"><NepseAlphaSymbolLink symbol={selectedOpportunity.best.symbol} className="drawer-nepse-chart">View chart on NEPSE Alpha ↗</NepseAlphaSymbolLink>{!fullPageDetail && <button type="button" aria-label="Close details" onClick={() => setSelectedOpportunity(null)}>×</button>}</div></header>
      <section className="detail-score-row"><article><span>Reliability score</span><strong>{fmt(selectedOpportunity.best.reliability_score, 'score')}</strong></article><article><span>Strategy win rate</span><strong>{fmt(selectedOpportunity.best.win_rate_pct, 'percent')}%</strong></article><article><span>Current technical score</span><strong>{fmt(selectedOpportunity.best.current_technical_score, 'score')}</strong></article><article><span>Current LTP</span><strong>NPR {fmt(selectedOpportunity.best.ltp, 'ltp')}</strong></article><article><span>Latest volume</span><strong>{fmt(selectedOpportunity.best.latest_volume, 'latest_volume')}</strong></article></section>
      <section className="detail-section"><h3>Strategy price, entry and exit chart</h3><p>See the recommended buy range, exact stop level, anticipated sell timing and price zone, plus every saved historical entry and exit. Trade returns include brokerage, SEBON fees, DP charge, CGT, and slippage.</p><TradeCandlestickChart resultId={selectedOpportunity.best.result_id} symbol={selectedOpportunity.best.symbol} cacheKey={selectedOpportunity.best.cache_key} /></section>
      <section className="detail-section"><h3>Equity, profit and drawdown</h3><StrongBuyCharts trades={detailTrades.items} /></section>
      <section className="detail-section"><div className="trade-heading"><div><h3>Complete wins and losses</h3><p>{detailTrades.total} historical trades · net results include brokerage, SEBON, DP, CGT, and slippage</p></div><select value={tradeFilter} onChange={(e) => void filterDetailTrades(e.target.value)}><option value="all">All trades</option><option value="wins">Wins only</option><option value="losses">Losses only</option><option value="stop_loss">Stop-loss exits</option><option value="take_profit">Take-profit exits</option></select></div><div className="research-table-wrap detail-trades"><table><thead><tr>{['Result','Strategy','Signal','Entry date','Entry price','Exit date','Exit price','Qty','Held','Exit reason','Gross return','Net return','Brokerage','SEBON','DP','CGT','Total charges','P/L','Running equity','Drawdown'].map((item) => <th key={item}>{item}</th>)}</tr></thead><tbody>{detailTrades.items.map((trade) => <tr key={trade.trade_id}><td><span className={`trade-${trade.result}`}>{trade.result}</span></td><td>{selectedOpportunity.best.preset_name}</td><td>{trade.signal_date || '—'}</td><td>{trade.entry_date}</td><td>{fmt(trade.entry_price, 'money')}</td><td>{trade.exit_date}</td><td>{fmt(trade.exit_price, 'money')}</td><td>{trade.quantity}</td><td>{trade.holding_days}d</td><td>{fmt(trade.exit_reason, 'reason')}</td><td>{trade.gross_return_pct}%</td><td>{trade.return_pct}%</td><td>NPR {fmt(trade.broker_commission, 'money')}</td><td>NPR {fmt(trade.sebon_fee, 'money')}</td><td>NPR {fmt(trade.dp_charge, 'money')}</td><td>NPR {fmt(trade.capital_gains_tax, 'money')}<small>{fmt(trade.capital_gains_tax_rate_pct, 'percent')}%</small></td><td>NPR {fmt(trade.total_charges, 'money')}</td><td className={Number(trade.pnl || 0) >= 0 ? 'positive' : 'negative'}>NPR {fmt(trade.pnl, 'money')}</td><td>NPR {fmt(trade.running_equity, 'money')}</td><td>{trade.drawdown_after_trade_pct}%</td></tr>)}</tbody></table></div><div className="research-pagination"><button type="button" disabled={detailTrades.page <= 1} onClick={() => void loadDetailTradePage(detailTrades.page - 1)}>Previous 100 trades</button><span>Showing {detailTrades.total ? (detailTrades.page - 1) * detailTrades.page_size + 1 : 0}–{Math.min(detailTrades.page * detailTrades.page_size, detailTrades.total)} of {detailTrades.total} · page {detailTrades.page} of {detailTrades.pages || 1}</span><button type="button" disabled={detailTrades.page >= detailTrades.pages} onClick={() => void loadDetailTradePage(detailTrades.page + 1)}>Next 100 trades</button></div></section>
      <section className="detail-section strategy-price-plan"><h3>Strategy planning prices</h3><p>These zones use the saved strategy’s stop, target, and ATR volatility. They are planning levels; the backtest still models entry at the next available open.</p><div><article><span>Buy zone</span><strong>{selectedOpportunity.best.buy_zone_low ? `NPR ${fmt(selectedOpportunity.best.buy_zone_low, 'money')}–${fmt(selectedOpportunity.best.buy_zone_high, 'money')}` : 'No current entry signal'}</strong></article><article><span>Protective stop</span><strong>{selectedOpportunity.best.protective_stop ? `NPR ${fmt(selectedOpportunity.best.protective_stop, 'money')}` : '—'}</strong></article><article><span>Strategy sell zone</span><strong>{selectedOpportunity.best.sell_zone_low ? `NPR ${fmt(selectedOpportunity.best.sell_zone_low, 'money')}–${fmt(selectedOpportunity.best.sell_zone_high, 'money')}` : '—'}</strong></article><article><span>20-day average volume</span><strong>{fmt(selectedOpportunity.best.average_volume_20, 'average_volume_20')}</strong></article></div></section>
      <section className="detail-section protection-champion"><div className="protection-champion-heading"><div><h3>Selected sell and stop strategy</h3><p>One champion is selected for this stock + entry strategy from the locked out-of-sample period. Raw win rate is not the only selection criterion.</p></div>{selectedOpportunity.best.assumptions?.protection_optimization && <span>OOS selected</span>}</div><div className="protection-champion-cards"><article><span>Sell rule</span><strong>{fmt(selectedOpportunity.best.assumptions?.exit_rule_id || 'saved preset exit', 'exit_rule')}</strong></article><article><span>Stop method</span><strong>{fmt(selectedOpportunity.best.assumptions?.protection_optimization?.champion?.stop?.label || selectedOpportunity.best.assumptions?.risk_strategy || 'fixed', 'stop')}</strong></article><article><span>Sell-zone basis</span><strong>{selectedOpportunity.best.planning_range_basis?.sell_zone_basis || `Saved +${selectedOpportunity.best.assumptions?.take_profit_pct}% target`}</strong></article><article><span>Combinations evaluated</span><strong>{selectedOpportunity.best.assumptions?.protection_optimization?.total_evaluations || 1}</strong></article></div>{selectedOpportunity.best.assumptions?.protection_optimization?.leaderboard?.length > 0 && <details><summary>Compare leading sell/stop combinations</summary><div className="research-table-wrap"><table><thead><tr><th>Sell rule</th><th>Stop</th><th>OOS score</th><th>Trades</th><th>Win rate</th><th>Profit factor</th><th>Expectancy</th><th>Drawdown</th></tr></thead><tbody>{selectedOpportunity.best.assumptions.protection_optimization.leaderboard.map((candidate: any, index: number) => <tr key={`${candidate.exit_rule_id}-${candidate.stop?.id}`} className={index === 0 ? 'recommended' : ''}><td>{fmt(candidate.exit_rule_id, 'exit')}</td><td>{candidate.stop?.label}</td><td>{fmt(candidate.selection_score, 'score')}</td><td>{candidate.summary?.total_trades}</td><td>{fmt(candidate.summary?.win_rate_pct, 'percent')}%</td><td>{fmt(candidate.summary?.profit_factor, 'ratio')}</td><td>{fmt(candidate.summary?.expectancy_pct, 'percent')}%</td><td>{fmt(candidate.summary?.max_drawdown_pct, 'percent')}%</td></tr>)}</tbody></table></div></details>}</section>
      <section className="detail-section"><h3>Latest strategy signal evidence</h3><p className="evidence-reason">{selectedOpportunity.best.current_evidence?.reason}</p><code>{selectedOpportunity.best.current_evidence?.strategy_condition}</code>{selectedOpportunity.best.current_evidence?.conditions_total > 0 && <p><b>{selectedOpportunity.best.current_evidence.conditions_passed}/{selectedOpportunity.best.current_evidence.conditions_total}</b> entry conditions currently pass ({fmt(selectedOpportunity.best.current_evidence.condition_progress_pct, 'percent')}%). “Near trigger” is readiness evidence, not a forecast.</p>}<div className="latest-values">{Object.entries(selectedOpportunity.best.current_evidence?.latest_values || {}).map(([key, value]) => <div key={key}><span>{key.replaceAll('_', ' ')}</span><b>{fmt(value, key)}</b></div>)}</div><h4>Condition checks</h4><div className="condition-checks">{(selectedOpportunity.best.current_evidence?.conditions || []).map((condition: any, index: number) => <div className={condition.matched ? 'passed' : 'failed'} key={`${condition.expression}-${index}`}><b>{condition.matched ? 'Passed' : 'Failed'}</b><span>{condition.expression}</span>{condition.message && <small>{condition.message}</small>}</div>)}</div></section>
      <section className="detail-section"><h3>How reliability was calculated</h3><div className="score-breakdown">{Object.entries(selectedOpportunity.best.current_evidence?.reliability?.components || {}).map(([key, value]) => <div key={key}><span>{key.replaceAll('_', ' ')}</span><b>+{fmt(value, key)}</b></div>)}</div>{(selectedOpportunity.best.current_evidence?.reliability?.penalties || []).map((penalty: any) => <p className="score-penalty" key={penalty.code}>−{penalty.points} · {penalty.code.replaceAll('_', ' ')}</p>)}</section>
      <section className="detail-section"><h3>Complete historical backtest summary</h3><div className="historical-summary">{Object.entries(selectedOpportunity.best.assumptions?.summary || {}).map(([key, value]) => <div key={key}><span>{key.replaceAll('_', ' ')}</span><b>{fmt(value, key)}</b></div>)}</div><div className="risk-config"><span>Protection {fmt(selectedOpportunity.best.assumptions?.risk_strategy || 'fixed', 'risk_strategy')}</span><span>Initial stop {selectedOpportunity.best.assumptions?.stop_loss_pct}%</span>{selectedOpportunity.best.assumptions?.trailing_stop_pct != null && <span>Trailing stop {selectedOpportunity.best.assumptions.trailing_stop_pct}%</span>}<span>Take profit {selectedOpportunity.best.assumptions?.take_profit_pct}%</span><span>Min hold {selectedOpportunity.best.assumptions?.min_holding_days || 0} days</span><span>Max hold {selectedOpportunity.best.assumptions?.max_holding_days} days</span>{String(selectedOpportunity.best.assumptions?.charge_model || '').startsWith('nepse_equity') ? <><span>NEPSE tiered brokerage</span><span>SEBON 0.015% each side</span><span>DP NPR 25 per sale</span><span>CGT by holding period</span></> : <span>Legacy flat-fee result · rerun for official Nepal charges</span>}<span>Strategy {selectedOpportunity.best.assumptions?.preset_version}</span><span>{selectedOpportunity.best.assumptions?.period?.start} → {selectedOpportunity.best.assumptions?.period?.end}</span></div></section>
      <section className="detail-section execution-promotion"><h3>Use the same query for trading</h3><p>The stored query—not a rewritten approximation—creates a paper draft first. Live scheduling remains a separate action with current account, balance, holdings, and risk checks.</p><div><label>TMS client ID<input value={paperClientId} onChange={(e) => setPaperClientId(e.target.value)} placeholder="Client ID" /></label><button disabled={promotionBusy || !paperClientId.trim()} onClick={() => void promoteToPaper()}>{promotionBusy ? 'Creating paper draft…' : 'Promote exact query to paper'}</button><a href="/dashboard/schedule-order">Open Schedule Order</a></div>{promotionMessage && <strong>{promotionMessage}</strong>}</section>
      <p className="strong-buy-disclaimer">Backtested historical performance does not guarantee future results. No broker order is placed or scheduled from this view.</p>
    </div></div>}
  </div>;
};

export default BacktestV2;
