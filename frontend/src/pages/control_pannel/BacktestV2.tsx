import React, { FormEvent, useEffect, useMemo, useRef, useState } from 'react';
import * as echarts from 'echarts/core';
import { BarChart, CandlestickChart, LineChart, ScatterChart } from 'echarts/charts';
import { AxisPointerComponent, DataZoomComponent, GridComponent, LegendComponent, TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type SeriesMarker,
  type Time,
} from 'lightweight-charts';
import { fetchJson, getApiUrl } from '../../utils/api';
import NepseAlphaSymbolLink from '../../components/NepseAlphaSymbolLink';
import { nextBacktestSortRules } from './backtestSort';
import './BacktestV2.css';
import './BacktestV2Filters.css';
import './BacktestV2Strategy.css';
import './StrongBuy.css';
import './StockScopePicker.css';

echarts.use([BarChart, CandlestickChart, LineChart, ScatterChart, AxisPointerComponent, DataZoomComponent, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);

const toChartTime = (value: string): string => String(value || '').slice(0, 10);

const timeKey = (value: Time): string => {
  if (typeof value === 'string') return value.slice(0, 10);
  if (typeof value === 'number') return new Date(value * 1000).toISOString().slice(0, 10);
  return `${value.year}-${String(value.month).padStart(2, '0')}-${String(value.day).padStart(2, '0')}`;
};

const snapToCandleTime = (dates: string[], value: string): string | null => {
  const target = toChartTime(value);
  if (!target || !dates.length) return null;
  if (dates.includes(target)) return target;
  let best: string | null = null;
  for (const date of dates) {
    if (date <= target) best = date;
    else break;
  }
  return best ?? dates[0];
};

type Preset = { id: string; name: string; category: string; family: string; description: string };
type Run = {
  run_id: string; name: string; status: string; progress_pct: number; symbols_completed: number;
  symbols_total: number; combinations_completed: number; current_symbol?: string; created_at?: string;
  configuration: { start_date: string; end_date: string; preset_ids: string[]; ordinary_shares_only: boolean; history_mode?: 'all_available' | 'custom'; strategy_mode?: 'presets' | 'custom' | 'discovery'; custom_query_text?: string };
  error_summary?: string;
  pause_requested?: boolean;
  cancel_requested?: boolean;
};
type ResultRow = Record<string, any> & { result_id: number; symbol: string; preset_name: string };
type ResultPage = { items: ResultRow[]; page: number; page_size: number; total: number; pages: number };
type ResultAdvancedFilter = { id: number; field: string; operator: string; value: string };
type ResultSort = { field: string; direction: 'asc' | 'desc' };
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
const columns = [
  ['symbol', 'Symbol'], ['preset_name', 'Strategy'], ['current_signal_status', 'Signal'], ['current_signal_date', 'Signal session'], ['sector', 'Sector'], ['robust_score', 'Robust'],
  ['oos_return_pct', 'OOS return %'], ['oos_expectancy_pct', 'OOS expectancy %'], ['oos_trades', 'OOS trades'],
  ['win_rate_pct', 'Win rate %'], ['total_trades', 'Trades'], ['max_drawdown_pct', 'Drawdown %'],
  ['min_holding_days', 'Min hold'], ['max_holding_days', 'Max hold'],
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
  const shellRef = useRef<HTMLDivElement | null>(null);
  const bandRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const rangeDragRef = useRef<{ startX: number; pointerId: number } | null>(null);
  const [payload, setPayload] = useState<ExecutionChartPayload | null>(null);
  const [activeCandleIndex, setActiveCandleIndex] = useState<number | null>(null);
  const [chartError, setChartError] = useState('');
  const zoomModifierLabel = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent) ? '⌘+drag' : 'Ctrl+drag';
  useEffect(() => {
    setPayload(null); setActiveCandleIndex(null); setChartError('');
    void fetchJson<ExecutionChartPayload>(`/api/backtests/v2/results/${resultId}/chart`).then((response) => {
      if (response.ok) setPayload(response.data); else setChartError(response.error || 'Could not load price history.');
    });
  }, [resultId]);
  useEffect(() => {
    if (!ref.current || !payload?.candles?.length) return undefined;
    const el = ref.current;
    const shell = shellRef.current;
    const dates = payload.candles.map((bar) => toChartTime(bar.date)).filter(Boolean);
    const indexByDate = new Map(dates.map((date, index) => [date, index]));
    const candleData = payload.candles.map((bar) => ({
      time: toChartTime(bar.date) as Time,
      open: Number(bar.open),
      high: Number(bar.high),
      low: Number(bar.low),
      close: Number(bar.close),
    }));
    const volumeData = payload.candles.map((bar) => ({
      time: toChartTime(bar.date) as Time,
      value: Number(bar.volume || 0),
      color: Number(bar.close) >= Number(bar.open) ? 'rgba(33,166,111,.55)' : 'rgba(224,82,82,.55)',
    }));
    const npr = (value: number) => `${value >= 0 ? '+' : '−'}NPR ${Math.abs(value).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
    const markers: SeriesMarker<Time>[] = [];
    payload.trades.forEach((trade) => {
      const entry = snapToCandleTime(dates, String(trade.entry_date || ''));
      const exit = snapToCandleTime(dates, String(trade.exit_date || ''));
      if (entry) markers.push({ time: entry as Time, position: 'belowBar', color: '#42d392', shape: 'arrowUp', text: 'BUY' });
      if (exit) {
        const pnl = Number(trade.pnl || 0);
        markers.push({ time: exit as Time, position: 'aboveBar', color: pnl >= 0 ? '#34d399' : '#ff5e66', shape: 'arrowDown', text: npr(pnl) });
      }
    });
    markers.sort((a, b) => timeKey(a.time).localeCompare(timeKey(b.time)));

    const chart = createChart(el, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: '#131722' },
        textColor: '#a7b0c0',
        fontSize: 11,
        attributionLogo: true,
      },
      grid: {
        vertLines: { color: '#1e2330' },
        horzLines: { color: '#1e2330' },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: '#8493a8', width: 1, style: LineStyle.Dashed, labelBackgroundColor: '#2962ff' },
        horzLine: { color: '#8493a8', width: 1, style: LineStyle.Dashed, labelBackgroundColor: '#2962ff' },
      },
      rightPriceScale: { borderColor: '#2a2e39', scaleMargins: { top: 0.08, bottom: 0.08 } },
      timeScale: {
        borderColor: '#2a2e39',
        rightOffset: 6,
        barSpacing: 7,
        minBarSpacing: 2,
        timeVisible: false,
      },
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: true },
      handleScale: { axisPressedMouseMove: { time: true, price: true }, mouseWheel: true, pinch: true },
    });
    chartRef.current = chart;

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#20b27a',
      downColor: '#e45454',
      borderUpColor: '#20b27a',
      borderDownColor: '#e45454',
      wickUpColor: '#20b27a',
      wickDownColor: '#e45454',
    });
    candleSeries.setData(candleData);
    createSeriesMarkers(candleSeries, markers);

    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    }, 1);
    volumeSeries.setData(volumeData);
    chart.priceScale('volume').applyOptions({
      borderColor: '#2a2e39',
      scaleMargins: { top: 0.15, bottom: 0 },
    });
    const panes = chart.panes();
    if (panes[0]) panes[0].setStretchFactor(3.2);
    if (panes[1]) panes[1].setStretchFactor(1);

    const showRecent = () => {
      const from = Math.max(0, candleData.length - 260);
      chart.timeScale().setVisibleLogicalRange({ from: from - 0.5, to: candleData.length - 0.5 });
    };
    showRecent();

    const setScrollEnabled = (enabled: boolean) => {
      chart.applyOptions({
        handleScroll: { mouseWheel: true, pressedMouseMove: enabled, horzTouchDrag: enabled, vertTouchDrag: enabled },
      });
    };
    const setRangeBand = (left: number | null, width = 0) => {
      const band = bandRef.current;
      if (!band) return;
      if (left == null) {
        band.hidden = true;
        band.style.width = '0px';
        return;
      }
      band.hidden = false;
      band.style.left = `${left}px`;
      band.style.width = `${Math.max(0, width)}px`;
    };
    const clearRangeDrag = () => {
      rangeDragRef.current = null;
      setRangeBand(null);
      el.classList.remove('range-selecting');
      setScrollEnabled(true);
    };
    const syncModifierArm = (armed: boolean) => {
      shell?.classList.toggle('range-zoom-armed', armed);
      el.classList.toggle('range-zoom-armed', armed);
      if (!rangeDragRef.current) setScrollEnabled(!armed);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Meta' || event.key === 'Control') syncModifierArm(true);
    };
    const onKeyUp = (event: KeyboardEvent) => {
      if (event.key === 'Meta' || event.key === 'Control') {
        if (rangeDragRef.current) return;
        syncModifierArm(false);
      }
    };
    const onBlur = () => { clearRangeDrag(); syncModifierArm(false); };
    const onPointerDown = (event: PointerEvent) => {
      if (event.button !== 0 || !(event.metaKey || event.ctrlKey)) return;
      event.preventDefault();
      event.stopPropagation();
      rangeDragRef.current = { startX: event.clientX, pointerId: event.pointerId };
      setScrollEnabled(false);
      el.classList.add('range-selecting');
      const localX = event.clientX - el.getBoundingClientRect().left;
      setRangeBand(localX, 0);
      el.setPointerCapture(event.pointerId);
    };
    const onPointerMove = (event: PointerEvent) => {
      const drag = rangeDragRef.current;
      if (!drag || drag.pointerId !== event.pointerId) return;
      const rect = el.getBoundingClientRect();
      const startLocal = drag.startX - rect.left;
      const currentLocal = event.clientX - rect.left;
      setRangeBand(Math.min(startLocal, currentLocal), Math.abs(currentLocal - startLocal));
    };
    const onPointerUp = (event: PointerEvent) => {
      const drag = rangeDragRef.current;
      if (!drag || drag.pointerId !== event.pointerId) return;
      const startX = drag.startX;
      const endX = event.clientX;
      clearRangeDrag();
      syncModifierArm(event.metaKey || event.ctrlKey);
      if (Math.abs(endX - startX) < 8) return;
      const rect = el.getBoundingClientRect();
      const fromTime = chart.timeScale().coordinateToTime(startX - rect.left);
      const toTime = chart.timeScale().coordinateToTime(endX - rect.left);
      if (fromTime == null || toTime == null) return;
      const a = timeKey(fromTime);
      const b = timeKey(toTime);
      const from = a <= b ? a : b;
      const to = a <= b ? b : a;
      if (from === to) return;
      chart.timeScale().setVisibleRange({ from: from as Time, to: to as Time });
    };
    const onCrosshair = (param: { time?: Time }) => {
      if (param.time == null) return;
      const nextIndex = indexByDate.get(timeKey(param.time));
      if (nextIndex != null) setActiveCandleIndex(nextIndex);
    };

    chart.subscribeCrosshairMove(onCrosshair);
    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('keyup', onKeyUp);
    window.addEventListener('blur', onBlur);
    el.addEventListener('pointerdown', onPointerDown, true);
    el.addEventListener('pointermove', onPointerMove);
    el.addEventListener('pointerup', onPointerUp);
    el.addEventListener('pointercancel', onPointerUp);

    return () => {
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('keyup', onKeyUp);
      window.removeEventListener('blur', onBlur);
      el.removeEventListener('pointerdown', onPointerDown, true);
      el.removeEventListener('pointermove', onPointerMove);
      el.removeEventListener('pointerup', onPointerUp);
      el.removeEventListener('pointercancel', onPointerUp);
      chart.unsubscribeCrosshairMove(onCrosshair);
      chart.remove();
      chartRef.current = null;
    };
  }, [payload, symbol]);
  if (chartError) return <div className="research-alert">{chartError}</div>;
  if (!payload) return <div className="trade-chart-loading">Loading the exact daily price and trade history…</div>;
  if (!payload.candles.length) return <div className="research-alert">No cached OHLCV candles are available for this result period.</div>;
  const resetView = () => {
    if (!chartRef.current || !payload?.candles?.length) return;
    const from = Math.max(0, payload.candles.length - 260);
    chartRef.current.timeScale().setVisibleLogicalRange({ from: from - 0.5, to: payload.candles.length - 0.5 });
  };
  const activeCandle = payload.candles[activeCandleIndex ?? payload.candles.length - 1];
  const price = (value: number) => Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const rising = Number(activeCandle.close) >= Number(activeCandle.open);
  return <div className="backtest-trade-chart">
    <div className="trade-chart-toolbar">
      <span className="trade-chart-symbol"><i />{symbol} <small>1D</small></span>
      <span className={`trade-chart-ohlc ${rising ? 'up' : 'down'}`} aria-live="polite">
        <span>O <b>{price(activeCandle.open)}</b></span>
        <span>H <b>{price(activeCandle.high)}</b></span>
        <span>L <b>{price(activeCandle.low)}</b></span>
        <span>C <b>{price(activeCandle.close)}</b></span>
      </span>
      <span className="trade-chart-gesture">{zoomModifierLabel} to zoom · Drag to pan · Scroll to zoom</span>
      <a className="trade-chart-tv" href="https://www.tradingview.com/" target="_blank" rel="noreferrer">TradingView</a>
      <button type="button" onClick={resetView}>Reset view</button>
    </div>
    <div className="trade-chart-shell" ref={shellRef}>
      <div ref={ref} className="trade-chart-canvas" aria-label={`${symbol} candlestick chart with every simulated buy and sell. ${zoomModifierLabel} selects a range to zoom, drag to pan, and use the mouse wheel to zoom.`} />
      <div ref={bandRef} className="trade-chart-range-band" hidden aria-hidden="true" />
    </div>
  </div>;
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
  const [minHoldingDays, setMinHoldingDays] = useState('5');
  const [maxHoldingDays, setMaxHoldingDays] = useState('90');
  const [strategyMode, setStrategyMode] = useState<'presets' | 'custom' | 'discovery'>('presets');
  const [discoveryBudget, setDiscoveryBudget] = useState('1000');
  const [customQuery, setCustomQuery] = useState(defaultCustomQuery);
  const [copyStatus, setCopyStatus] = useState('');
  const [creating, setCreating] = useState(false);
  const [runControlBusy, setRunControlBusy] = useState<'pause' | 'resume' | 'cancel' | 'retry' | null>(null);
  const [runControlMessage, setRunControlMessage] = useState('');
  const [uniqueConfigurationTotal, setUniqueConfigurationTotal] = useState(0);
  const [runScope, setRunScope] = useState<'all' | 'single'>('all');
  const [stockSearch, setStockSearch] = useState('');
  const [selectedStock, setSelectedStock] = useState<{ symbol: string; company_name: string; sector?: string } | null>(null);
  const [stockSuggestions, setStockSuggestions] = useState<Array<{ symbol: string; company_name: string; sector?: string }>>([]);
  const [error, setError] = useState('');
  const [showHowItWorks, setShowHowItWorks] = useState(false);
  const [tab, setTab] = useState<'opportunities' | 'combinations' | 'portfolio' | 'ai' | 'quality'>('combinations');
  const [results, setResults] = useState<ResultPage>({ items: [], page: 1, page_size: 50, total: 0, pages: 0 });
  const [resultScope, setResultScope] = useState<'run' | 'all' | 'strategies' | 'holistic'>(() => {
    const requestedScope = params.get('scope');
    return requestedScope === 'run' || requestedScope === 'all' || requestedScope === 'holistic'
      ? requestedScope
      : 'strategies';
  });
  const [allRunsSelected, setAllRunsSelected] = useState(() => params.get('scope') !== 'run');
  const [resultSorts, setResultSorts] = useState<ResultSort[]>([{ field: 'win_rate_pct', direction: 'desc' }]);
  const initialResultSymbol = params.get('stock') || '';
  const initialResultFilters: ResultAdvancedFilter[] = [
    ...(initialResultSymbol ? [{ id: 1, field: 'symbol', operator: 'eq', value: initialResultSymbol }] : []),
    { id: initialResultSymbol ? 2 : 1, field: 'total_trades', operator: 'gte', value: '20' },
  ];
  const [resultFilterJoin, setResultFilterJoin] = useState<'and' | 'or'>('and');
  const [resultFilterRows, setResultFilterRows] = useState<ResultAdvancedFilter[]>(initialResultFilters);
  const [appliedResultFilters, setAppliedResultFilters] = useState<ResultAdvancedFilter[]>(initialResultFilters);
  const appliedResultFilterSignature = useRef(JSON.stringify(initialResultFilters));
  const nextResultFilterId = useRef(initialResultFilters.length + 1);
  const [resultSectors, setResultSectors] = useState<string[]>([]);
  const [resultSymbolSuggestions, setResultSymbolSuggestions] = useState<Array<{ symbol: string; company_name: string; sector?: string }>>([]);
  const [includeNonEquities, setIncludeNonEquities] = useState(false);
  const [resultsBusy, setResultsBusy] = useState(false);
  const [resultFilterStatus, setResultFilterStatus] = useState('');
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
  const fullPageDetail = params.get('detail') === 'full';

  const loadRuns = async () => {
    const response = await fetchJson<{ items: Run[]; unique_configuration_total?: number }>('/api/backtests/v2/runs?page=1&page_size=50');
    if (!response.ok) return;
    setRuns(response.data.items);
    setUniqueConfigurationTotal(Number(response.data.unique_configuration_total || 0));
    const requested = params.get('run');
    setActiveRun((current) => current
      ? response.data.items.find((item) => item.run_id === current.run_id) || current
      : response.data.items.find((item) => item.run_id === requested) || response.data.items[0] || null);
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
      }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [activeRun?.run_id, activeRun?.status]);

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
      body: JSON.stringify({ filters: filterAst, include_non_equities: includeNonEquities, sorts: resultSorts, unique_by_symbol: resultScope === 'holistic', unique_by_strategy: resultScope === 'strategies', page, page_size: results.page_size }),
    });
    if (requestId !== resultRequestId.current) return;
    resultAbortRef.current = null;
    setResultsBusy(false);
    if (response.ok) {
      setResults(response.data);
      setResultFilterStatus(`${response.data.total.toLocaleString()} matching simulations ready`);
    } else {
      setResultFilterStatus('Filter could not be applied');
      setError(response.error || 'Could not load results.');
    }
  };

  useEffect(() => { void loadResults(1); }, [activeRun?.run_id, filterAst, includeNonEquities, resultScope, resultSorts, results.page_size]);

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
    if (!showHowItWorks) return undefined;
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') setShowHowItWorks(false); };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [showHowItWorks]);

  useEffect(() => {
    if (!selectedOpportunity || fullPageDetail) return undefined;
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') setSelectedOpportunity(null); };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [fullPageDetail, selectedOpportunity]);

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

  const loadDetailTradePage = async (page: number) => {
    const resultId = selectedOpportunity?.best?.result_id;
    if (!resultId || page < 1 || page > detailTrades.pages) return;
    const response = await fetchJson<TradePage>(`/api/backtests/v2/results/${resultId}/trades?page=${page}&page_size=${detailTrades.page_size || 100}&result_filter=${tradeFilter}`);
    if (response.ok) setDetailTrades(response.data);
  };

  const startRun = async (event: FormEvent) => {
    event.preventDefault(); setCreating(true); setError('');
    const parsedMinHold = optionalNumber(minHoldingDays) ?? 5;
    const parsedMaxHold = optionalNumber(maxHoldingDays) ?? 90;
    if (!Number.isInteger(parsedMinHold) || parsedMinHold < 0 || parsedMinHold > 365) { setCreating(false); setError('Minimum holding days must be a whole number from 0 to 365.'); return; }
    if (!Number.isInteger(parsedMaxHold) || parsedMaxHold < 1 || parsedMaxHold > 365) { setCreating(false); setError('Maximum holding days must be a whole number from 1 to 365. A blank field uses the 90-day default.'); return; }
    if (runScope === 'single' && !selectedStock) { setCreating(false); setError('Choose one stock from the symbol suggestions before running.'); return; }
    if (strategyMode === 'custom' && customQuery.trim().length < 20) { setCreating(false); setError('Enter a complete Strategy Language query.'); return; }
    if (strategyMode === 'presets' && selected.size === 0) { setCreating(false); setError('Select at least one strategy preset.'); return; }
    const parsedDiscoveryBudget = optionalNumber(discoveryBudget);
    if (strategyMode === 'discovery' && (selected.size < 2 || parsedDiscoveryBudget == null || !Number.isInteger(parsedDiscoveryBudget) || parsedDiscoveryBudget < 10 || parsedDiscoveryBudget > 10000)) { setCreating(false); setError('Discovery requires at least two base strategies and a whole candidate budget from 10 to 10,000.'); return; }
    if (parsedMaxHold != null && parsedMinHold > parsedMaxHold) { setCreating(false); setError('Minimum holding days cannot exceed maximum holding days.'); return; }
    const response = await fetchJson<Run>('/api/backtests/v2/runs', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, history_mode: historyMode, start_date: historyMode === 'all_available' ? allHistoryStart : startDate, end_date: historyMode === 'all_available' ? today : endDate, strategy_mode: strategyMode, custom_query_text: strategyMode === 'custom' ? customQuery : null, preset_ids: strategyMode === 'presets' ? Array.from(selected) : [], discovery_budget: strategyMode === 'discovery' ? parsedDiscoveryBudget : 1000, discovery_seed: 20260718, discovery_base_ids: strategyMode === 'discovery' ? Array.from(selected) : [], symbols: runScope === 'single' && selectedStock ? [selectedStock.symbol] : null, ordinary_shares_only: ordinaryOnly, min_holding_days: parsedMinHold, max_holding_days: parsedMaxHold, data_source: 'merolagani', max_workers: 2, run_type: runScope === 'single' ? 'single_stock' : 'market_scan' }),
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
        body: JSON.stringify({ filters: scope === 'all' ? { join: 'and', conditions: [] } : filterAst, include_non_equities: includeNonEquities, sorts: resultSorts, page: 1, page_size: 100 }),
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
    const defaults: ResultAdvancedFilter[] = [{ id: 1, field: 'total_trades', operator: 'gte', value: '20' }];
    appliedResultFilterSignature.current = JSON.stringify(defaults);
    nextResultFilterId.current = 2;
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
      <div className="research-run-library-head"><span><small>Continuous research</small><h2>Scan workspaces</h2><p>Identical stock and strategy scans update one workspace instead of creating duplicates.</p></span><div><strong>{runs.length}</strong><span>unique</span><button onClick={() => void loadRuns()}>Refresh</button></div></div>
      <div className="research-run-strip">{runs.length > 0 && <button className={`all-runs-card ${allRunsSelected ? 'active' : ''}`} onClick={() => { setAllRunsSelected(true); setResultScope('strategies'); setTab('combinations'); }}><span className="research-run-card-top"><b>All runs</b><em>combined</em></span><span className="research-run-card-metrics"><small><strong>{runs.length}</strong> workspaces</small><small><strong>{uniqueConfigurationTotal.toLocaleString()}</strong> unique configurations</small></span><span className="research-run-card-progress"><i style={{ width: '100%' }} /></span></button>}{runs.length === 0 ? <p>No v2 research runs yet.</p> : runs.map((run) => <button key={run.run_id} className={!allRunsSelected && activeRun?.run_id === run.run_id ? 'active' : ''} onClick={() => { setAllRunsSelected(false); setResultScope('run'); setActiveRun(run); }}><span className="research-run-card-top"><b>{run.name}</b><em className={`run-${run.status}`}>{run.status}</em></span><span className="research-run-card-metrics"><small><strong>{run.symbols_completed}/{run.symbols_total}</strong> stocks</small><small><strong>{run.combinations_completed.toLocaleString()}</strong> results</small></span><span className="research-run-card-progress"><i style={{ width: `${Math.max(0, Math.min(100, run.progress_pct || 0))}%` }} /></span></button>)}</div>
    </section>

    <section className="research-layout">
      <main className="research-main">
        <details className="research-new-run" open={!activeRun}>
          <summary><span><b>New research run</b><small>Name it, select the universe and strategies, then leave it running safely in the background.</small></span><strong>Configure</strong></summary>
          <form onSubmit={startRun}>
            <div className="research-form-grid"><label>Run name<input value={name} onChange={(e) => setName(e.target.value)} required /></label><label>History<select value={historyMode} onChange={(e) => setHistoryMode(e.target.value as 'all_available' | 'custom')}><option value="all_available">All available history (default)</option><option value="custom">Custom date range</option></select><small>{historyMode === 'all_available' ? 'Uses up to 20 years and each stock’s earliest available session.' : 'Use only when comparing an exact market period.'}</small></label>{historyMode === 'custom' && <><label>Start<input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} required /></label><label>End<input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} required /></label></>}<label>Universe<select value={ordinaryOnly ? 'ordinary' : 'all'} onChange={(e) => setOrdinaryOnly(e.target.value === 'ordinary')}><option value="ordinary">Ordinary shares only</option><option value="all">All instrument classes</option></select></label><label>Stocks to test<select value={runScope} onChange={(e) => { setRunScope(e.target.value as 'all' | 'single'); setSelectedStock(null); setStockSearch(''); }}><option value="all">All stocks in universe</option><option value="single">One particular stock</option></select></label><label>Strategy source<select value={strategyMode} onChange={(e) => setStrategyMode(e.target.value as 'presets' | 'custom' | 'discovery')}><option value="presets">Professional presets</option><option value="discovery">Adaptive combination discovery</option><option value="custom">One custom query</option></select></label>{strategyMode === 'discovery' && <label>Candidate budget<input type="number" min="10" max="10000" step="1" value={discoveryBudget} onChange={(e) => setDiscoveryBudget(e.target.value)} /><small>Reproducible sample from a 50M+ search space.</small></label>}<label>Minimum hold (days)<input type="number" min="0" max="365" step="1" value={minHoldingDays} onChange={(e) => setMinHoldingDays(e.target.value)} /><small>Default 5 days; type another value to override it for this run.</small></label><label>Maximum hold (days)<input type="number" min="1" max="365" step="1" value={maxHoldingDays} onChange={(e) => setMaxHoldingDays(e.target.value)} /><small>Default 90 days; you can change it.</small></label></div>
            {runScope === 'single' && <div className="stock-picker"><label>Find stock by symbol or company name<input value={stockSearch} onChange={(e) => { setStockSearch(e.target.value.toUpperCase()); setSelectedStock(null); }} placeholder="Type NABIL or Nabil Bank…" autoComplete="off" required /></label>{selectedStock && <div className="selected-stock"><b>{selectedStock.symbol}</b><span>{selectedStock.company_name}</span><em>{selectedStock.sector || 'Sector unavailable'}</em></div>}{stockSuggestions.length > 0 && <div className="stock-suggestions" role="listbox">{stockSuggestions.map((item) => <button type="button" role="option" aria-selected={selectedStock?.symbol === item.symbol} key={item.symbol} onClick={() => { setSelectedStock(item); setStockSearch(item.symbol); setStockSuggestions([]); setName(`${item.symbol} strategy research`); }}><b>{item.symbol}</b><span>{item.company_name}</span><em>{item.sector || ''}</em></button>)}</div>}<small>All selected presets will run only on the chosen stock. This does not affect saved all-market runs.</small></div>}
            {strategyMode !== 'custom' ? <><div className="research-preset-head"><span><b>{strategyMode === 'discovery' ? 'Base signal catalog' : 'Preset catalog'}</b><small>{selected.size}/{presets.length} selected · grouped by family</small></span><div><button type="button" onClick={() => setSelected(new Set(presets.map((item) => item.id)))}>All {presets.length}</button><button type="button" onClick={() => setSelected(new Set())}>Clear</button></div></div>{strategyMode === 'discovery' && <div className="research-alert">Combines two or three selected signals and searches stop, target, minimum-hold, and maximum-hold settings. Stable hashes prevent duplicate testing.</div>}<div className="research-preset-groups">{grouped.map(([category, items]) => <details key={category}><summary>{category}<span>{items.filter((item) => selected.has(item.id)).length}/{items.length}</span></summary><div>{items.map((preset) => <label key={preset.id} title={preset.description}><input type="checkbox" checked={selected.has(preset.id)} onChange={() => setSelected((current) => { const next = new Set(current); next.has(preset.id) ? next.delete(preset.id) : next.add(preset.id); return next; })} /><span>{preset.name}</span></label>)}</div></details>)}</div></> : <div className="research-custom-query"><div><span><b>Custom Strategy Language</b><small>The symbol in this query is a template. For an all-stock run, the server safely retargets only the symbol and keeps every condition, risk setting, charge, and order-sizing rule unchanged.</small></span><button type="button" onClick={() => void copyGptPrompt()}>Copy prompt for GPT</button>{copyStatus && <em>{copyStatus}</em>}</div><textarea value={customQuery} onChange={(e) => setCustomQuery(e.target.value)} rows={20} spellCheck={false} /></div>}
            <div className="research-submit"><p>History is cached per stock. Scans use a low-priority background worker so normal trading and dashboard requests stay responsive. The exact versioned query is stored with every result and can be promoted to paper, then separately confirmed for live scheduling.</p><button disabled={creating || (strategyMode === 'custom' ? customQuery.trim().length < 20 : selected.size === 0)}>{creating ? 'Queuing…' : strategyMode === 'custom' ? `Queue query on ${runScope === 'all' ? 'all stocks' : selectedStock?.symbol || 'one stock'}` : strategyMode === 'discovery' ? `Discover ${Number(discoveryBudget || 0).toLocaleString()} combinations` : `Queue ${selected.size} strategies`}</button></div>
          </form>
        </details>

        {activeRun && <>
          <section className="research-run-head"><div><span className={allRunsSelected ? 'run-completed' : `run-${activeRun.status}`}>{allRunsSelected ? 'combined research' : activeRun.cancel_requested ? 'cancelling' : activeRun.pause_requested ? 'pausing' : activeRun.status}</span><h2>{allRunsSelected ? 'All runs · unique simulation configurations' : activeRun.name}</h2><p>{allRunsSelected ? 'Every workspace combined · only exact symbol, strategy, risk, holding, cost, sizing, and engine configurations are merged' : `${activeRun.configuration.start_date} → ${activeRun.configuration.end_date} · ordinary shares ${activeRun.configuration.ordinary_shares_only ? 'default' : 'not restricted'}`}</p>{!allRunsSelected && runControlMessage && <span role="status" aria-live="polite" className={`run-control-feedback ${activeRun.status === 'paused' || activeRun.status === 'cancelled' ? 'confirmed' : ''}`}>{runControlMessage}</span>}</div>{!allRunsSelected && <div className="research-controls">{activeRun.status === 'running' && <button disabled={Boolean(runControlBusy || activeRun.pause_requested || activeRun.cancel_requested)} onClick={() => void control('pause')}>{runControlBusy === 'pause' || activeRun.pause_requested ? 'Pausing…' : 'Pause'}</button>}{activeRun.status === 'paused' && <button disabled={Boolean(runControlBusy || activeRun.cancel_requested)} onClick={() => void control('resume')}>{runControlBusy === 'resume' ? 'Resuming…' : 'Resume'}</button>}{activeRun.status === 'failed' && <button disabled={Boolean(runControlBusy)} onClick={() => void control('retry')}>{runControlBusy === 'retry' ? 'Retrying…' : 'Retry failed'}</button>}{['queued', 'running', 'paused'].includes(activeRun.status) && <button disabled={Boolean(runControlBusy || activeRun.cancel_requested)} className="danger" onClick={() => void control('cancel')}>{runControlBusy === 'cancel' || activeRun.cancel_requested ? 'Cancelling…' : 'Cancel'}</button>}</div>}</section>
          {!allRunsSelected && <section className="research-progress"><div><b>{activeRun.progress_pct}%</b><span>{activeRun.symbols_completed}/{activeRun.symbols_total} stocks</span><span>{activeRun.combinations_completed.toLocaleString()} persisted results</span><span>{activeRun.current_symbol || 'Waiting for next checkpoint'}</span></div><progress value={activeRun.progress_pct} max="100" /><small>Scan progress updates in the background. The result table stays stable while you analyse it; use Refresh new scan results when you want the latest checkpoint.</small></section>}
          <nav className="research-tabs">{([['combinations', 'All results'], ['portfolio', 'Portfolio'], ['ai', 'Ask AI'], ['quality', 'Data quality']] as const).map(([key, label]) => <button key={key} className={tab === key ? 'active' : ''} onClick={() => setTab(key)}>{label}</button>)}<a href="/dashboard/recommendations">Open live recommendations ↗</a></nav>

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
            <div className="research-table-wrap strong-buy-table"><table><thead><tr>{opportunityColumns.map((column) => { const sortIndex = opportunitySorts.findIndex((item) => item.field === column.sortKey); const ariaSort = sortIndex === 0 ? (opportunitySorts[0].direction === 'desc' ? 'descending' : 'ascending') : undefined; return <th key={column.key} aria-sort={ariaSort}>{column.sortKey ? <button type="button" className={`recommendation-sort-button ${sortIndex >= 0 ? 'active' : ''}`} title="Click for primary sort; Shift-click to add a sorting rule" onClick={(event) => toggleOpportunitySort(column.sortKey!, event.shiftKey)}>{column.label}<span>{opportunitySortMarker(column.sortKey)}</span></button> : column.label}</th>; })}</tr></thead><tbody>{opportunities.items.map((row) => <tr key={row.result_id}><td>{row.rank}</td><td><div className="stock-chart-links"><button className="symbol-link" onClick={() => void openOpportunity(row)}>{row.symbol}</button><NepseAlphaSymbolLink symbol={row.symbol}>Chart ↗</NepseAlphaSymbolLink></div></td><td><span className={`signal-pill ${row.current_signal_status}`}>{signalLabel(row.current_signal_status)}</span></td><td>{row.preset_name}</td><td><b>{fmt(row.recommendation_score, 'score')}</b></td><td className="price-zone buy-zone">{row.buy_zone_low ? `NPR ${fmt(row.buy_zone_low, 'money')}–${fmt(row.buy_zone_high, 'money')}` : 'No current entry'}</td><td className="price-zone stop-zone">{row.protective_stop ? `NPR ${fmt(row.protective_stop, 'money')}` : '—'}</td><td className="price-zone sell-zone">{row.sell_zone_low ? `NPR ${fmt(row.sell_zone_low, 'money')}–${fmt(row.sell_zone_high, 'money')}` : '—'}</td><td>{fmt(row.ltp, 'ltp')}</td><td>{row.signal_date}</td><td><b>{fmt(row.win_rate_pct, 'percent')}%</b></td><td>{row.total_trades}</td><td>{fmt(row.average_holding_days, 'days')} days</td><td>{fmt(row.net_return_pct, 'percent')}%</td><td>{fmt(row.max_drawdown_pct, 'percent')}%</td><td>{fmt(row.average_volume_20, 'average_volume_20')}</td><td>{fmt(row.latest_volume, 'latest_volume')}</td><td><button className="view-evidence" onClick={() => void openOpportunity(row)}>Details</button></td></tr>)}</tbody></table>{opportunities.items.length === 0 && <div className="research-empty">No fresh ordinary-share recommendation matches these exact filters. The application does not substitute older trading sessions or silently weaken filters.</div>}</div>
            <div className="research-pagination"><button disabled={opportunities.page <= 1} onClick={() => void loadOpportunities(opportunities.page - 1)}>Previous</button><span>Page {opportunities.page} of {opportunities.pages || 1}</span><button disabled={opportunities.page >= opportunities.pages} onClick={() => void loadOpportunities(opportunities.page + 1)}>Next</button></div>
            <p className="strong-buy-disclaimer">Backtested historical performance does not guarantee future results. This is research, not financial advice, and never places a broker order.</p>
          </section>}

          {tab === 'combinations' && <section className="research-panel">
            <section className="result-filter-builder" aria-label="Custom backtest result filters">
              <div className="result-filter-heading"><div><h3>Find the best results</h3><p>Every scanned combination in this workspace is shown by default. Filters update automatically; click a table heading to rank the matches.</p></div><div><label>View<select value={resultScope} onChange={(event) => { const scope = event.target.value as 'run' | 'all' | 'strategies' | 'holistic'; setResultScope(scope); setAllRunsSelected(scope !== 'run'); }}><option value="run">Selected scan · all results</option><option value="strategies">All runs · unique configurations</option><option value="all">All runs · complete history</option><option value="holistic">All runs · best per stock</option></select></label><label>Logic<select value={resultFilterJoin} onChange={(event) => setResultFilterJoin(event.target.value as 'and' | 'or')}><option value="and">Match all</option><option value="or">Match any</option></select></label><label>Stocks<select value={includeNonEquities ? 'all' : 'ordinary'} onChange={(e) => setIncludeNonEquities(e.target.value === 'all')}><option value="ordinary">Ordinary shares</option><option value="all">All instruments</option></select></label><label>Show<select value={results.page_size} onChange={(e) => setResults((current) => ({ ...current, page_size: Number(e.target.value) }))}><option>25</option><option>50</option><option>100</option></select></label></div></div>
              <datalist id="result-symbol-suggestions">{resultSymbolSuggestions.map((item) => <option key={item.symbol} value={item.symbol}>{item.company_name}{item.sector ? ` · ${item.sector}` : ''}</option>)}</datalist>
              <div className="result-quick-filters"><span>Add filter</span><button type="button" onClick={() => addResultFilter('symbol')}>Stock</button><button type="button" onClick={() => addResultFilter('current_signal_status', '', 'eq')}>Signal</button><button type="button" onClick={() => addResultFilter('sector')}>Sector</button><button type="button" onClick={() => addResultFilter('preset_name', '', 'eq')}>Strategy preset</button><button type="button" onClick={() => addResultFilter('total_trades')}>Trades</button><button type="button" onClick={() => addResultFilter('min_holding_days', '5', 'eq')}>Min hold</button><button type="button" onClick={() => addResultFilter('max_holding_days', '90', 'eq')}>Max hold</button><button type="button" onClick={() => addResultFilter('latest_volume')}>Volume</button></div>
              <div className="result-filter-presets"><span>Popular rules</span><button type="button" onClick={() => addResultFilter('total_trades', '20')}>20+ trades</button><button type="button" onClick={() => addResultFilter('oos_trades', '10')}>10+ OOS trades</button><button type="button" onClick={() => addResultFilter('robust_score', '60')}>Robust 60+</button><button type="button" onClick={() => addResultFilter('win_rate_pct', '55')}>Win rate 55%+</button><button type="button" onClick={() => addResultFilter('profit_factor', '1.5')}>Profit factor 1.5+</button><button type="button" onClick={() => addResultFilter('max_drawdown_pct', '25', 'lte')}>Drawdown ≤25%</button></div>
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
              <footer>{!resultsBusy && <span>{`${appliedResultFilters.length} active condition${appliedResultFilters.length === 1 ? '' : 's'} · ${resultFilterJoin.toUpperCase()} · stable at this checkpoint`}</span>}<div><button type="button" className="secondary" disabled={resultsBusy} onClick={() => void loadResults(1)}>Refresh new scan results</button><button type="button" className="secondary" disabled={resultsBusy} onClick={resetResultFilters}>Reset filters</button></div></footer>
            </section>
            <div className="recommendation-sort-guide"><span><b>Multi-column ranking:</b> click a heading to make it primary and toggle ↓/↑. Hold Shift while clicking to add or change a secondary rule.</span><button type="button" onClick={() => setResultSorts([{ field: 'win_rate_pct', direction: 'desc' }])}>Reset to win rate</button></div>
            <div className="research-table-summary"><div><b>{results.total.toLocaleString()} {resultScope === 'holistic' ? 'unique stocks across all runs' : resultScope === 'strategies' ? 'unique simulation configurations across all runs' : resultScope === 'all' ? 'historical results across all runs' : 'results from this run'}</b><span>{resultScope === 'holistic' ? 'Best validated result per stock · duplicate runs removed' : resultScope === 'strategies' ? 'Exact duplicates only: symbol + complete entry/exit strategy + holding/risk/cost/sizing settings + engine versions' : resultScope === 'all' ? 'Complete cached stock × strategy history across every run' : 'Every scanned stock × strategy combination in the selected workspace'} · {resultSorts.map((item, index) => `${index + 1}. ${(columns.find(([key]) => key === item.field)?.[1] || item.field)} ${item.direction === 'desc' ? '↓' : '↑'}`).join(' · ')}</span></div><div className="csv-export-control"><label><span>CSV dataset</span><select value={exportScope} onChange={(event) => setExportScope(event.target.value as 'run' | 'all')}><option value="run">This run · current filters</option><option value="all">All my cached backtests</option></select></label><button type="button" disabled={exporting} onClick={() => void downloadCsv(exportScope)}>{exporting ? 'Preparing download…' : '↓ Download CSV'}</button>{exportStatus && <small>{exportStatus}</small>}</div></div>
            <div className={`research-table-wrap ${resultsBusy ? 'is-loading' : ''}`} aria-busy={resultsBusy}><table><thead><tr>{columns.map(([key, label]) => { const sortIndex = resultSorts.findIndex((item) => item.field === key); return <th key={key} aria-sort={sortIndex === 0 ? (resultSorts[0].direction === 'desc' ? 'descending' : 'ascending') : undefined}><button type="button" className={`recommendation-sort-button ${sortIndex >= 0 ? 'active' : ''}`} disabled={resultsBusy} title="Click for primary sort; Shift-click to add a sorting rule" onClick={(event) => toggleResultSort(key, event.shiftKey)}>{label}<span>{resultSortMarker(key)}</span></button></th>; })}</tr></thead><tbody>{results.items.map((row) => <tr key={row.result_id} className={row.recommendation_status === 'recommended' ? 'recommended' : ''}>{columns.map(([key]) => <td key={key}>{key === 'symbol' ? <div className="stock-chart-links"><button type="button" className="symbol-link" title={`View ${row.symbol} backtest details`} onClick={() => void openOpportunity(row as Opportunity)}>{row.symbol}</button><NepseAlphaSymbolLink symbol={row.symbol}>Chart ↗</NepseAlphaSymbolLink></div> : key === 'preset_name' ? <button type="button" className="result-detail-link" title={`View ${row.preset_name} details`} onClick={() => void openOpportunity(row as Opportunity)}>{row.preset_name}</button> : key === 'current_signal_status' ? <span className={`signal-pill ${row.current_signal_status}`}>{signalLabel(row.current_signal_status)}</span> : key === 'robust_score' ? <span className={`score score-${Math.floor(Number(row[key] || 0) / 20)}`}>{fmt(row[key], key)}</span> : fmt(row[key], key)}</td>)}</tr>)}</tbody></table>{resultsBusy && <div className="result-table-loading"><span className="filter-spinner" />Ranking exact matches…</div>}{!resultsBusy && results.items.length === 0 && <div className="research-empty">No result matches these exact filters. Filters were not silently weakened.</div>}</div>
            <div className="research-pagination"><button disabled={resultsBusy || results.page <= 1} onClick={() => void loadResults(results.page - 1)}>Previous</button><span>{resultsBusy ? 'Loading exact page…' : `Page ${results.page} of ${results.pages || 1}`}</span><button disabled={resultsBusy || results.page >= results.pages} onClick={() => void loadResults(results.page + 1)}>Next</button></div>
          </section>}

          {tab === 'portfolio' && <section className="research-panel"><div className="research-panel-title"><div><h3>Shared-capital strategy leaderboard</h3><p>One cash balance · max 10 positions · 10% per stock · 30% per sector · 5% reserve.</p></div></div><div className="portfolio-grid">{portfolios.map((item) => <article key={item.preset_id}><span>{item.preset_name}</span><strong className={item.summary.net_return_pct >= 0 ? 'positive' : 'negative'}>{fmt(item.summary.net_return_pct, 'return')}%</strong><dl><div><dt>Final equity</dt><dd>NPR {fmt(item.summary.final_equity, 'money')}</dd></div><div><dt>Drawdown</dt><dd>{fmt(item.summary.max_drawdown_pct, 'percent')}%</dd></div><div><dt>Accepted</dt><dd>{item.summary.accepted_signals}</dd></div><div><dt>Rejected</dt><dd>{item.summary.rejected_signals}</dd></div></dl></article>)}</div>{portfolios.length === 0 && <div className="research-empty">Portfolio results are finalized after the stock scan completes.</div>}</section>}

          {tab === 'ai' && <section className="research-panel"><div className="research-panel-title"><div><h3>Ask AI for the top 10</h3><p>Search every cached strategy result using a validated query plan. Generated SQL is never executed.</p></div><label>Search scope<select value={aiScope} onChange={(e) => setAiScope(e.target.value as 'all' | 'run')}><option value="all">All my backtest data</option><option value="run">Current run only</option></select></label></div><div className="ai-backtest-presets" aria-label="AI backtest prompt presets">{aiBacktestPresets.map((prompt, index) => <button type="button" key={prompt} onClick={() => setAiQuestion(prompt)}><b>Preset {index + 1}</b><span>{prompt}</span></button>)}</div><div className="ai-query"><textarea rows={4} value={aiQuestion} onChange={(e) => setAiQuestion(e.target.value)} placeholder="Describe the stocks, strategies, risk limits, and ranking you want…" /><button disabled={aiBusy} onClick={() => void askAi()}>{aiBusy ? 'Validating…' : 'Generate query + top 10'}</button></div>{aiAnswer && <><pre>{aiAnswer.generated_query}</pre><p>{aiAnswer.explanation}</p><p><b>{aiAnswer.recommendation_summary}</b></p>{aiAnswer.total_matches === 0 && <div className="research-alert">No exact matches. {aiAnswer.suggested_relaxations.join(' ')}</div>}<div className="research-table-wrap"><table><thead><tr>{columns.slice(0, 10).map(([key, label]) => <th key={key}>{label}</th>)}<th>Why it matched</th></tr></thead><tbody>{aiAnswer.items.map((row: ResultRow) => <tr key={row.result_id}>{columns.slice(0, 10).map(([key]) => <td key={key}>{fmt(row[key], key)}</td>)}<td>{(row.match_reasons || []).join(' · ')}</td></tr>)}</tbody></table></div></>}</section>}

          {tab === 'quality' && <section className="research-panel quality-grid"><article><b>Universe snapshot</b><strong>{activeRun.symbols_total}</strong><p>Instrument membership is frozen when the run starts.</p></article><article><b>Completed symbols</b><strong>{activeRun.symbols_completed}</strong><p>Each completion is checkpointed for restart recovery.</p></article><article><b>Ordinary-share enforcement</b><strong>{activeRun.configuration.ordinary_shares_only ? 'On' : 'Explicitly off'}</strong><p>Non-equities stay excluded at the API unless explicitly requested.</p></article><article><b>Validation split</b><strong>70 / 30</strong><p>The newest 30% of sessions are locked for out-of-sample metrics.</p></article></section>}
        </>}
      </main>
    </section>
    {detailBusy && <div className="detail-loading">Loading complete signal and trade evidence…</div>}
    {selectedOpportunity && <div className={`strong-buy-overlay ${fullPageDetail ? 'full-page' : ''}`} role={fullPageDetail ? undefined : 'dialog'} aria-modal={fullPageDetail ? undefined : 'true'} aria-label="Backtest recommendation details"><div className="strong-buy-drawer">
      <header><div><span className={`signal-pill ${selectedOpportunity.best.current_signal_status}`}>{fmt(selectedOpportunity.best.current_signal_status, 'status')}</span><h2>{selectedOpportunity.best.symbol} · {selectedOpportunity.best.preset_name}</h2><p>Signal {selectedOpportunity.best.current_signal_date} · calculated from the latest completed daily session</p><NepseAlphaSymbolLink symbol={selectedOpportunity.best.symbol} className="drawer-nepse-chart">Open {selectedOpportunity.best.symbol} chart on NEPSE Alpha ↗</NepseAlphaSymbolLink></div><div className="drawer-header-actions">{fullPageDetail ? <a href="/dashboard/backtest">← Back to Backtest Lab</a> : <a href={`/dashboard/backtest?run=${activeRun?.run_id || ''}&stock=${selectedOpportunity.best.symbol}&result=${selectedOpportunity.best.result_id}&detail=full`} target="_blank" rel="noreferrer">Open full page ↗</a>}{!fullPageDetail && <button type="button" aria-label="Close details" onClick={() => setSelectedOpportunity(null)}>×</button>}</div></header>
      <section className="detail-score-row"><article><span>Reliability score</span><strong>{fmt(selectedOpportunity.best.reliability_score, 'score')}</strong></article><article><span>Current technical score</span><strong>{fmt(selectedOpportunity.best.current_technical_score, 'score')}</strong></article><article><span>Current LTP</span><strong>NPR {fmt(selectedOpportunity.best.ltp, 'ltp')}</strong></article><article><span>Latest volume</span><strong>{fmt(selectedOpportunity.best.latest_volume, 'latest_volume')}</strong></article></section>
      <section className="detail-section strategy-price-plan"><h3>Strategy planning prices</h3><p>These zones use the saved strategy’s stop, target, and ATR volatility. They are planning levels; the backtest still models entry at the next available open.</p><div><article><span>Buy zone</span><strong>{selectedOpportunity.best.buy_zone_low ? `NPR ${fmt(selectedOpportunity.best.buy_zone_low, 'money')}–${fmt(selectedOpportunity.best.buy_zone_high, 'money')}` : 'No current entry signal'}</strong></article><article><span>Protective stop</span><strong>{selectedOpportunity.best.protective_stop ? `NPR ${fmt(selectedOpportunity.best.protective_stop, 'money')}` : '—'}</strong></article><article><span>Strategy sell zone</span><strong>{selectedOpportunity.best.sell_zone_low ? `NPR ${fmt(selectedOpportunity.best.sell_zone_low, 'money')}–${fmt(selectedOpportunity.best.sell_zone_high, 'money')}` : '—'}</strong></article><article><span>20-day average volume</span><strong>{fmt(selectedOpportunity.best.average_volume_20, 'average_volume_20')}</strong></article></div></section>
      <section className="detail-section"><h3>Latest strategy signal evidence</h3><p className="evidence-reason">{selectedOpportunity.best.current_evidence?.reason}</p><code>{selectedOpportunity.best.current_evidence?.strategy_condition}</code>{selectedOpportunity.best.current_evidence?.conditions_total > 0 && <p><b>{selectedOpportunity.best.current_evidence.conditions_passed}/{selectedOpportunity.best.current_evidence.conditions_total}</b> entry conditions currently pass ({fmt(selectedOpportunity.best.current_evidence.condition_progress_pct, 'percent')}%). “Near trigger” is readiness evidence, not a forecast.</p>}<div className="latest-values">{Object.entries(selectedOpportunity.best.current_evidence?.latest_values || {}).map(([key, value]) => <div key={key}><span>{key.replaceAll('_', ' ')}</span><b>{fmt(value, key)}</b></div>)}</div><h4>Condition checks</h4><div className="condition-checks">{(selectedOpportunity.best.current_evidence?.conditions || []).map((condition: any, index: number) => <div className={condition.matched ? 'passed' : 'failed'} key={`${condition.expression}-${index}`}><b>{condition.matched ? 'Passed' : 'Failed'}</b><span>{condition.expression}</span>{condition.message && <small>{condition.message}</small>}</div>)}</div></section>
      <section className="detail-section"><h3>How reliability was calculated</h3><div className="score-breakdown">{Object.entries(selectedOpportunity.best.current_evidence?.reliability?.components || {}).map(([key, value]) => <div key={key}><span>{key.replaceAll('_', ' ')}</span><b>+{fmt(value, key)}</b></div>)}</div>{(selectedOpportunity.best.current_evidence?.reliability?.penalties || []).map((penalty: any) => <p className="score-penalty" key={penalty.code}>−{penalty.points} · {penalty.code.replaceAll('_', ' ')}</p>)}</section>
      <section className="detail-section"><h3>Complete historical backtest summary</h3><div className="historical-summary">{Object.entries(selectedOpportunity.best.assumptions?.summary || {}).map(([key, value]) => <div key={key}><span>{key.replaceAll('_', ' ')}</span><b>{fmt(value, key)}</b></div>)}</div><div className="risk-config"><span>Stop loss {selectedOpportunity.best.assumptions?.stop_loss_pct}%</span><span>Take profit {selectedOpportunity.best.assumptions?.take_profit_pct}%</span><span>Min hold {selectedOpportunity.best.assumptions?.min_holding_days || 0} days</span><span>Max hold {selectedOpportunity.best.assumptions?.max_holding_days} days</span>{String(selectedOpportunity.best.assumptions?.charge_model || '').startsWith('nepse_equity') ? <><span>NEPSE tiered brokerage</span><span>SEBON 0.015% each side</span><span>DP NPR 25 per sale</span><span>CGT by holding period</span></> : <span>Legacy flat-fee result · rerun for official Nepal charges</span>}<span>Strategy {selectedOpportunity.best.assumptions?.preset_version}</span><span>{selectedOpportunity.best.assumptions?.period?.start} → {selectedOpportunity.best.assumptions?.period?.end}</span></div></section>
      <section className="detail-section execution-promotion"><h3>Use the same query for trading</h3><p>The stored query—not a rewritten approximation—creates a paper draft first. Live scheduling remains a separate action with current account, balance, holdings, and risk checks.</p><div><label>TMS client ID<input value={paperClientId} onChange={(e) => setPaperClientId(e.target.value)} placeholder="Client ID" /></label><button disabled={promotionBusy || !paperClientId.trim()} onClick={() => void promoteToPaper()}>{promotionBusy ? 'Creating paper draft…' : 'Promote exact query to paper'}</button><a href="/dashboard/schedule-order">Open Schedule Order</a></div>{promotionMessage && <strong>{promotionMessage}</strong>}</section>
      <section className="detail-section"><h3>Every simulated trade on the daily chart</h3><p>Green triangles are next-session simulated entries. Red diamonds are exits; each exit label shows the net NPR profit or loss after saved charges.</p><TradeCandlestickChart resultId={selectedOpportunity.best.result_id} symbol={selectedOpportunity.best.symbol} /></section>
      <section className="detail-section"><h3>Equity, profit and drawdown</h3><StrongBuyCharts trades={detailTrades.items} /></section>
      <section className="detail-section"><div className="trade-heading"><div><h3>Complete wins and losses</h3><p>{detailTrades.total} historical trades · net results include brokerage, SEBON, DP, CGT, and slippage</p></div><select value={tradeFilter} onChange={(e) => void filterDetailTrades(e.target.value)}><option value="all">All trades</option><option value="wins">Wins only</option><option value="losses">Losses only</option><option value="stop_loss">Stop-loss exits</option><option value="take_profit">Take-profit exits</option></select></div><div className="research-table-wrap detail-trades"><table><thead><tr>{['Result','Strategy','Signal','Entry date','Entry price','Exit date','Exit price','Qty','Held','Exit reason','Gross return','Net return','Brokerage','SEBON','DP','CGT','Total charges','P/L','Running equity','Drawdown'].map((item) => <th key={item}>{item}</th>)}</tr></thead><tbody>{detailTrades.items.map((trade) => <tr key={trade.trade_id}><td><span className={`trade-${trade.result}`}>{trade.result}</span></td><td>{selectedOpportunity.best.preset_name}</td><td>{trade.signal_date || '—'}</td><td>{trade.entry_date}</td><td>{fmt(trade.entry_price, 'money')}</td><td>{trade.exit_date}</td><td>{fmt(trade.exit_price, 'money')}</td><td>{trade.quantity}</td><td>{trade.holding_days}d</td><td>{fmt(trade.exit_reason, 'reason')}</td><td>{trade.gross_return_pct}%</td><td>{trade.net_return_pct}%</td><td>NPR {fmt(trade.broker_commission, 'money')}</td><td>NPR {fmt(trade.sebon_fee, 'money')}</td><td>NPR {fmt(trade.dp_charge, 'money')}</td><td>NPR {fmt(trade.capital_gains_tax, 'money')}<small>{fmt(trade.capital_gains_tax_rate_pct, 'percent')}%</small></td><td>NPR {fmt(trade.total_charges, 'money')}</td><td className={Number(trade.pnl || 0) >= 0 ? 'positive' : 'negative'}>NPR {fmt(trade.pnl, 'money')}</td><td>NPR {fmt(trade.running_equity, 'money')}</td><td>{trade.drawdown_after_trade_pct}%</td></tr>)}</tbody></table></div><div className="research-pagination"><button type="button" disabled={detailTrades.page <= 1} onClick={() => void loadDetailTradePage(detailTrades.page - 1)}>Previous 100 trades</button><span>Showing {detailTrades.total ? (detailTrades.page - 1) * detailTrades.page_size + 1 : 0}–{Math.min(detailTrades.page * detailTrades.page_size, detailTrades.total)} of {detailTrades.total} · page {detailTrades.page} of {detailTrades.pages || 1}</span><button type="button" disabled={detailTrades.page >= detailTrades.pages} onClick={() => void loadDetailTradePage(detailTrades.page + 1)}>Next 100 trades</button></div></section>
      <p className="strong-buy-disclaimer">Backtested historical performance does not guarantee future results. No broker order is placed or scheduled from this view.</p>
    </div></div>}
  </div>;
};

export default BacktestV2;
