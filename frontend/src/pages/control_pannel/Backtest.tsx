import React, { FormEvent, useEffect, useMemo, useRef, useState } from 'react';
import * as echarts from 'echarts/core';
import { CandlestickChart, LineChart, ScatterChart } from 'echarts/charts';
import { DataZoomComponent, GridComponent, LegendComponent, ToolboxComponent, TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import { fetchJson } from '../../utils/api';
import CommonTable from '../../components/table/Table';
import './Backtest.css';

echarts.use([
  CandlestickChart, LineChart, ScatterChart, DataZoomComponent,
  GridComponent, LegendComponent, ToolboxComponent, TooltipComponent, CanvasRenderer,
]);

type Trade = {
  id: number; rule_name: string; signal_date: string; entry_date: string; entry_price: number;
  exit_date: string; exit_price: number; quantity: number; holding_days: number; exit_reason: string;
  broker_commission: number; sebon_fee: number; dp_charge: number; capital_gains_tax: number;
  capital_gains_tax_rate_pct: number; total_charges: number;
  pnl: number; return_pct: number; result: 'win' | 'loss' | 'break_even';
};

type ChartPoint = { time: number; date: string; close?: number; value?: number };

type BacktestResult = {
  symbol: string;
  data_source: string;
  period: { start: string; end: string; bars: number };
  assumptions: { entry: string; intraday_priority: string; charge_model?: string; brokerage_schedule?: string; sebon_transaction_fee_pct_each_side?: number; dp_charge_each_sell?: number; capital_gains_tax_policy?: string };
  summary: {
    initial_capital: number; final_equity: number; net_profit: number; net_return_pct: number;
    total_trades: number; wins: number; losses: number; win_rate_pct: number;
    profit_factor: number | null; max_drawdown_pct: number; average_trade_pct: number;
    cagr_pct: number | null; annual_volatility_pct: number; sharpe_ratio: number | null;
    sortino_ratio: number | null; exposure_pct: number; expectancy_pct: number;
    average_win_pct: number; average_loss_pct: number; payoff_ratio: number | null;
    average_holding_days: number; max_consecutive_wins: number; max_consecutive_losses: number;
    benchmark_return_pct: number; alpha_vs_benchmark_pct: number; total_fees: number;
    total_taxes: number; total_charges: number; total_broker_commission: number;
    total_sebon_fees: number; total_dp_charges: number;
    total_slippage_cost: number; rejected_orders: number;
  };
  trades: Trade[];
  bars: Array<ChartPoint & { open: number; high: number; low: number; close: number; volume: number }>;
  equity_curve: Array<ChartPoint & { value: number }>;
};

type Preset = { id: string; name: string; category: string; condition: string; description: string };
type BatchRanking = { symbol: string; preset_id: string; preset_name: string; category: string; bars: number; total_trades: number; win_rate_pct: number; confidence_score: number; net_return_pct: number; max_drawdown_pct: number; sharpe_ratio: number | null; profit_factor: number | null; expectancy_pct?: number | null; alpha_vs_benchmark_pct?: number | null; sample_quality: string; security_type?: string; sector?: string | null; listing_age_days?: number | null; latest_volume?: number | null; ltp?: number | null; technical_signal?: string; technical_signal_score?: number; technical_buy_score?: number; technical_sell_score?: number };
type StockSummary = { symbol: string; best_preset_id: string | null; best_preset_name: string | null; best_win_rate_pct: number; best_confidence_score: number; best_total_trades: number; average_win_rate_pct: number; presets_with_trades: number; total_trades: number; security_type?: string; sector?: string | null; listing_age_days?: number | null; latest_volume?: number | null; ltp?: number | null };
type BatchResult = { symbols_requested: number; symbols_completed: number; presets_tested: number; combinations_tested: number; rankings: BatchRanking[]; reliable_rankings: BatchRanking[]; stock_summary: StockSummary[]; preset_summary: Array<{ preset_id: string; preset_name: string; category: string; symbols_tested: number; average_win_rate_pct: number; average_return_pct: number; profitable_symbols: number; strong_samples: number }>; errors: Array<{ symbol: string; message: string }>; ranking_note: string };
type BatchJob = {
  job_id: string; status: 'queued' | 'running' | 'completed' | 'failed';
  created_at: string | null; started_at: string | null; finished_at: string | null;
  symbols_completed: number; symbols_total: number; combinations_completed: number;
  current_symbol: string | null; percent_complete: number; error: string | null;
  parameters: { start_date: string; end_date: string; data_source: string; preset_count: number; workers: number; ordinary_shares_only?: boolean; indicator_engine_version?: string; max_listing_age_days?: number | null; min_volume?: number | null };
  has_result: boolean; result: BatchResult | null; live_rankings?: BatchRanking[];
};
type StockDrilldown = { job_id: string; symbol: string; status: string; results: BatchRanking[]; technical_snapshot: { as_of_date?: string; engine_version?: string; indicators?: Record<string, unknown> } };
type IndicatorRefreshStatus = { running: boolean; completed: number; total: number; failed: number; stored_symbols: number; current_symbol?: string; engine_version: string };
type AiBacktestAnalysis = { generated_query: string; explanation: string; results: BatchRanking[]; rows_analyzed: number; matches_returned: number; note: string };
type AdvancedFilterField = keyof Pick<BatchRanking, 'sector' | 'ltp' | 'listing_age_days' | 'latest_volume' | 'bars' | 'total_trades' | 'win_rate_pct' | 'confidence_score' | 'net_return_pct' | 'max_drawdown_pct' | 'sharpe_ratio' | 'profit_factor' | 'expectancy_pct' | 'alpha_vs_benchmark_pct' | 'sample_quality' | 'preset_name' | 'category' | 'technical_signal' | 'technical_signal_score' | 'technical_buy_score' | 'technical_sell_score'>;
type AdvancedFilter = { id: number; field: AdvancedFilterField; operator: string; value: string };

const advancedFilterFields: Array<{ key: AdvancedFilterField; label: string; type: 'number' | 'text' }> = [
  { key: 'sector', label: 'Sector', type: 'text' }, { key: 'ltp', label: 'Latest price (LTP)', type: 'number' },
  { key: 'listing_age_days', label: 'Listing age (days)', type: 'number' }, { key: 'latest_volume', label: 'Latest volume', type: 'number' },
  { key: 'bars', label: 'History bars', type: 'number' }, { key: 'total_trades', label: 'Total trades', type: 'number' },
  { key: 'win_rate_pct', label: 'Win rate %', type: 'number' }, { key: 'confidence_score', label: 'Confidence score', type: 'number' },
  { key: 'net_return_pct', label: 'Net return %', type: 'number' }, { key: 'max_drawdown_pct', label: 'Max drawdown %', type: 'number' },
  { key: 'sharpe_ratio', label: 'Sharpe ratio', type: 'number' }, { key: 'profit_factor', label: 'Profit factor', type: 'number' },
  { key: 'expectancy_pct', label: 'Expectancy %', type: 'number' }, { key: 'alpha_vs_benchmark_pct', label: 'Benchmark alpha %', type: 'number' },
  { key: 'sample_quality', label: 'Sample quality', type: 'text' }, { key: 'preset_name', label: 'Preset name', type: 'text' },
  { key: 'category', label: 'Preset category', type: 'text' }, { key: 'technical_signal', label: 'Technical signal', type: 'text' },
  { key: 'technical_signal_score', label: 'Technical score', type: 'number' }, { key: 'technical_buy_score', label: 'Technical buy score', type: 'number' },
  { key: 'technical_sell_score', label: 'Technical sell score', type: 'number' },
];
const numericFilterOperators = [{ key: 'gte', label: 'At least' }, { key: 'lte', label: 'At most' }, { key: 'gt', label: 'Greater than' }, { key: 'lt', label: 'Less than' }, { key: 'eq', label: 'Equals' }, { key: 'neq', label: 'Not equal' }];
const textFilterOperators = [{ key: 'contains', label: 'Contains' }, { key: 'eq', label: 'Equals' }, { key: 'neq', label: 'Not equal' }];

const matchesAdvancedFilters = (row: BatchRanking, filters: AdvancedFilter[]) => filters.every((filter) => {
  if (!filter.value.trim()) return true;
  const field = advancedFilterFields.find((item) => item.key === filter.field);
  const left = row[filter.field];
  if (left == null || !field) return false;
  if (field.type === 'number') {
    const leftNumber = Number(left); const rightNumber = Number(filter.value);
    if (!Number.isFinite(leftNumber) || !Number.isFinite(rightNumber)) return false;
    return { eq: leftNumber === rightNumber, neq: leftNumber !== rightNumber, gt: leftNumber > rightNumber, gte: leftNumber >= rightNumber, lt: leftNumber < rightNumber, lte: leftNumber <= rightNumber }[filter.operator] ?? false;
  }
  const leftText = String(left).toLowerCase(); const rightText = filter.value.trim().toLowerCase();
  return { contains: leftText.includes(rightText), eq: leftText === rightText, neq: leftText !== rightText }[filter.operator] ?? false;
});

const isoDate = (date: Date) => date.toISOString().slice(0, 10);
const today = new Date();
const twoYearsAgo = new Date(today.getFullYear() - 2, today.getMonth(), today.getDate());
const marketHistoryStart = '2018-01-01';

const defaultQuery = `STRATEGY_VERSION 1
SIDE BUY
BACKTEST {
  INITIAL_CAPITAL 100000
  CHARGE_MODEL "nepse_equity"
  INVESTOR_TYPE "individual"
  APPLY_CGT TRUE
  DP_CHARGE 25
  SLIPPAGE_PCT 0.1
  STOP_LOSS_PCT 5
  TAKE_PROFIT_PCT 10
  MAX_HOLDING_DAYS 20
  POSITION_SIZE_PCT 100
  MAX_VOLUME_PARTICIPATION_PCT 10
  DATA_SOURCE "auto"
}
RULE "RSI Recovery" FOR SYMBOL "NABIL" {
  WHEN technical_rsi_14 BETWEEN 30 AND 45 AND change_percent > 0
  ORDER PERCENT_OF_AVAILABLE_CASH 100
  EXECUTE MAX 100 TIMES PER SYMBOL
}`;

const money = (value: number) => `NPR ${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;

const PerformanceChart: React.FC<{ result: BacktestResult }> = ({ result }) => {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;
    const chart = echarts.init(container, undefined, { renderer: 'canvas' });
    const dates = result.bars.map((bar) => bar.date);
    let equityPeak = result.summary.initial_capital;
    const drawdown = result.equity_curve.map((point) => {
      equityPeak = Math.max(equityPeak, point.value);
      return equityPeak ? Number((((point.value - equityPeak) / equityPeak) * 100).toFixed(2)) : 0;
    });
    const commonCategoryAxis = {
      type: 'category' as const, data: dates, boundaryGap: true,
      axisLine: { lineStyle: { color: '#cbd5e1' } },
      axisTick: { show: false }, axisLabel: { color: '#64748b', hideOverlap: true },
      splitLine: { show: false }, min: 'dataMin', max: 'dataMax',
    };
    chart.setOption({
      animation: false,
      backgroundColor: '#ffffff',
      color: ['#2563eb', '#f59e0b', '#dc2626'],
      legend: { top: 8, left: 64, textStyle: { color: '#475569' }, data: ['Price', 'Equity', 'Drawdown'] },
      toolbox: {
        right: 18, top: 3,
        feature: { dataZoom: { yAxisIndex: false }, restore: {}, saveAsImage: { name: `${result.symbol}-backtest` } },
      },
      axisPointer: { link: [{ xAxisIndex: 'all' }], label: { backgroundColor: '#334155' } },
      tooltip: { trigger: 'axis', axisPointer: { type: 'cross' }, backgroundColor: 'rgba(15,23,42,.94)', borderWidth: 0, textStyle: { color: '#f8fafc' } },
      grid: [
        { left: 72, right: 28, top: 50, height: '50%' },
        { left: 72, right: 28, top: '61%', height: '15%' },
        { left: 72, right: 28, top: '79%', height: '10%' },
      ],
      xAxis: [
        { ...commonCategoryAxis, gridIndex: 0, axisLabel: { show: false } },
        { ...commonCategoryAxis, gridIndex: 1, axisLabel: { show: false } },
        { ...commonCategoryAxis, gridIndex: 2 },
      ],
      yAxis: [
        { scale: true, gridIndex: 0, name: 'Price (NPR)', nameTextStyle: { color: '#64748b' }, axisLabel: { color: '#64748b' }, splitLine: { lineStyle: { color: '#e8edf4' } } },
        { scale: true, gridIndex: 1, name: 'Equity', nameTextStyle: { color: '#64748b' }, axisLabel: { color: '#64748b' }, splitLine: { lineStyle: { color: '#eef2f7' } } },
        { max: 0, gridIndex: 2, name: 'DD %', nameTextStyle: { color: '#64748b' }, axisLabel: { color: '#64748b', formatter: '{value}%' }, splitLine: { lineStyle: { color: '#eef2f7' } } },
      ],
      dataZoom: [
        { type: 'inside', xAxisIndex: [0, 1, 2], start: Math.max(0, 100 - (120 / Math.max(dates.length, 1)) * 100), end: 100 },
        { type: 'slider', xAxisIndex: [0, 1, 2], bottom: 5, height: 22, borderColor: '#dbe3ef', fillerColor: 'rgba(37,99,235,.16)', handleStyle: { color: '#2563eb' } },
      ],
      series: [
        {
          name: 'Price', type: 'candlestick', xAxisIndex: 0, yAxisIndex: 0,
          data: result.bars.map((bar) => [bar.open, bar.close, bar.low, bar.high]),
          itemStyle: { color: '#10b981', color0: '#ef4444', borderColor: '#059669', borderColor0: '#dc2626' },
        },
        {
          name: 'Buy', type: 'scatter', xAxisIndex: 0, yAxisIndex: 0, symbol: 'triangle', symbolSize: 13,
          data: result.trades.map((trade) => ({ value: [trade.entry_date, trade.entry_price], name: `BUY #${trade.id}`, itemStyle: { color: '#2563eb' } })),
          tooltip: { valueFormatter: (value: unknown) => `NPR ${Number(value).toLocaleString()}` },
        },
        {
          name: 'Exit', type: 'scatter', xAxisIndex: 0, yAxisIndex: 0, symbol: 'diamond', symbolSize: 13,
          data: result.trades.map((trade) => ({ value: [trade.exit_date, trade.exit_price], name: `${trade.result.toUpperCase()} #${trade.id}`, itemStyle: { color: trade.result === 'win' ? '#16a34a' : trade.result === 'loss' ? '#dc2626' : '#64748b' } })),
        },
        {
          name: 'Equity', type: 'line', xAxisIndex: 1, yAxisIndex: 1, showSymbol: false, smooth: false,
          data: result.equity_curve.map((point) => point.value), lineStyle: { width: 2, color: '#f59e0b' }, areaStyle: { color: 'rgba(245,158,11,.12)' },
        },
        {
          name: 'Drawdown', type: 'line', xAxisIndex: 2, yAxisIndex: 2, showSymbol: false, step: 'end',
          data: drawdown, lineStyle: { width: 1.5, color: '#dc2626' }, areaStyle: { color: 'rgba(220,38,38,.18)' },
        },
      ],
    });
    const resize = () => chart.resize();
    const observer = new ResizeObserver(resize);
    observer.observe(container);
    return () => { observer.disconnect(); chart.dispose(); };
  }, [result]);

  return <div className="backtest-chart-wrap"><div ref={containerRef} className="backtest-market-chart" aria-label={`${result.symbol} price, equity, drawdown, and trade results chart`} /></div>;
};

const Backtest: React.FC = () => {
  const drilldownParams = useMemo(() => new URLSearchParams(window.location.search), []);
  const drilldownJobId = drilldownParams.get('job') || '';
  const drilldownSymbol = (drilldownParams.get('stock') || '').toUpperCase();
  const [mode, setMode] = useState<'custom' | 'market'>('custom');
  const [symbol, setSymbol] = useState(drilldownSymbol || 'NABIL');
  const [query, setQuery] = useState(() => drilldownSymbol ? defaultQuery.replaceAll('NABIL', drilldownSymbol) : defaultQuery);
  const [startDate, setStartDate] = useState(isoDate(twoYearsAgo));
  const [endDate, setEndDate] = useState(isoDate(today));
  const [marketStartDate, setMarketStartDate] = useState(marketHistoryStart);
  const [marketEndDate, setMarketEndDate] = useState(isoDate(today));
  const [marketDataSource, setMarketDataSource] = useState<'merolagani' | 'combined'>('merolagani');
  const [ordinarySharesOnly, setOrdinarySharesOnly] = useState(true);
  const [maxScriptAgeDays, setMaxScriptAgeDays] = useState<number | null>(null);
  const [minimumVolume, setMinimumVolume] = useState<number | null>(null);
  const [advancedFilters, setAdvancedFilters] = useState<AdvancedFilter[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [selectedPresets, setSelectedPresets] = useState<Set<string>>(new Set());
  const [presetSearch, setPresetSearch] = useState('');
  const [batchResult, setBatchResult] = useState<BatchResult | null>(null);
  const [batchJob, setBatchJob] = useState<BatchJob | null>(null);
  const [savedJobs, setSavedJobs] = useState<BatchJob[]>([]);
  const [historyBusy, setHistoryBusy] = useState(false);
  const [minimumTrades, setMinimumTrades] = useState(5);
  const [resultSearch, setResultSearch] = useState('');
  const [rankingMode, setRankingMode] = useState<'win_rate' | 'confidence'>('win_rate');
  const [copyStatus, setCopyStatus] = useState('');
  const [stockDrilldown, setStockDrilldown] = useState<StockDrilldown | null>(null);
  const [analysisQuestion, setAnalysisQuestion] = useState('Which stocks and presets look strongest after considering confidence, trades, drawdown, and return?');
  const [analysisAnswer, setAnalysisAnswer] = useState<AiBacktestAnalysis | null>(null);
  const [analysisBusy, setAnalysisBusy] = useState(false);
  const [indicatorStatus, setIndicatorStatus] = useState<IndicatorRefreshStatus | null>(null);
  const pollTimer = useRef<number | null>(null);
  const nextAdvancedFilterId = useRef(1);

  useEffect(() => {
    void fetchJson<{ presets: Preset[] }>('/api/backtest/presets').then((response) => {
      if (response.ok) {
        setPresets(response.data.presets);
        setSelectedPresets(new Set(response.data.presets.map((item) => item.id)));
      }
    });
    return () => { if (pollTimer.current !== null) window.clearTimeout(pollTimer.current); };
  }, []);

  useEffect(() => {
    if (!drilldownJobId || !drilldownSymbol) return;
    void fetchJson<StockDrilldown>(`/api/backtest/batch/jobs/${encodeURIComponent(drilldownJobId)}/symbols/${encodeURIComponent(drilldownSymbol)}`).then((response) => {
      if (response.ok) setStockDrilldown(response.data);
      else setError(response.error || 'Could not load the saved stock analysis.');
    });
  }, [drilldownJobId, drilldownSymbol]);

  useEffect(() => {
    const load = () => void fetchJson<IndicatorRefreshStatus>('/api/technical-indicators/refresh').then((response) => {
      if (response.ok) setIndicatorStatus(response.data);
    });
    load();
    const timer = window.setInterval(load, 5000);
    return () => window.clearInterval(timer);
  }, []);

  const querySymbolMismatch = useMemo(() => {
    const match = query.match(/FOR\s+SYMBOL\s+"([A-Z0-9.-]+)"/i);
    return match && match[1].toUpperCase() !== symbol.trim().toUpperCase();
  }, [query, symbol]);

  const updateSymbol = (value: string) => {
    const clean = value.toUpperCase().replace(/[^A-Z0-9.-]/g, '').slice(0, 20);
    setSymbol(clean);
    setQuery((current) => current.replace(/(FOR\s+SYMBOL\s+")[A-Z0-9.-]+("\s*\{)/i, `$1${clean}$2`));
  };

  const run = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError('');
    setResult(null);
    const response = await fetchJson<BacktestResult>('/api/backtest/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol, query_text: query, start_date: startDate, end_date: endDate }),
    }, 120000);
    setBusy(false);
    if (!response.ok) {
      setError(response.error || 'Backtest failed.');
      return;
    }
    setResult(response.data);
  };

  const pollBatchJob = async (jobId: string): Promise<void> => {
    const response = await fetchJson<BatchJob>(`/api/backtest/batch/jobs/${jobId}`, undefined, 120000);
    if (!response.ok) { setBusy(false); setError(response.error || 'Could not read market scan progress.'); return; }
    setBatchJob(response.data);
    if (response.data.status === 'completed' && response.data.result) {
      setBatchResult(response.data.result); setBusy(false); void refreshSavedJobs(); return;
    }
    if (response.data.status === 'failed') {
      setError(response.data.error || 'Market scan failed.'); setBusy(false); void refreshSavedJobs(); return;
    }
    pollTimer.current = window.setTimeout(() => { void pollBatchJob(jobId); }, 1800);
  };

  const refreshSavedJobs = async () => {
    setHistoryBusy(true);
    const response = await fetchJson<{ jobs: BatchJob[] }>('/api/backtest/batch/jobs');
    setHistoryBusy(false);
    if (!response.ok) return;
    setSavedJobs(response.data.jobs);
    const active = response.data.jobs.find((job) => job.status === 'queued' || job.status === 'running');
    if (active && (!batchJob || batchJob.job_id !== active.job_id)) {
      setBatchJob(active); setBusy(true); setMode('market');
      void pollBatchJob(active.job_id);
    }
  };

  // Load persisted scans once; the active-job poll refreshes this list afterward.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { void refreshSavedJobs(); }, []);

  const runBatch = async (event: FormEvent) => {
    event.preventDefault();
    if (!selectedPresets.size) { setError('Select at least one preset.'); return; }
    setBusy(true); setError(''); setBatchResult(null); setBatchJob(null);
    const response = await fetchJson<BatchJob>('/api/backtest/batch/jobs', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ start_date: marketStartDate, end_date: marketEndDate, preset_ids: Array.from(selectedPresets), data_source: marketDataSource, max_workers: 8, ordinary_shares_only: ordinarySharesOnly, max_listing_age_days: maxScriptAgeDays, min_volume: minimumVolume }),
    }, 120000);
    if (!response.ok) { setBusy(false); setError(response.error || 'Market backtest failed.'); void refreshSavedJobs(); return; }
    setBatchJob(response.data);
    setSavedJobs((current) => [response.data, ...current.filter((job) => job.job_id !== response.data.job_id)]);
    void pollBatchJob(response.data.job_id);
  };

  const openSavedJob = async (job: BatchJob) => {
    setError(''); setHistoryBusy(true); setMode('market');
    const response = await fetchJson<BatchJob>(`/api/backtest/batch/jobs/${job.job_id}`, undefined, 120000);
    setHistoryBusy(false);
    if (!response.ok) { setError(response.error || 'Could not open the saved scan.'); return; }
    setBatchJob(response.data);
    if (response.data.result) setBatchResult(response.data.result);
    if (response.data.status === 'queued' || response.data.status === 'running') {
      setBusy(true); void pollBatchJob(response.data.job_id);
    }
  };

  const deleteSavedJob = async (job: BatchJob) => {
    if (!window.confirm(`Delete the saved backtest from ${job.parameters.start_date} to ${job.parameters.end_date}? This cannot be undone.`)) return;
    setHistoryBusy(true);
    const response = await fetchJson<unknown>(`/api/backtest/batch/jobs/${job.job_id}`, { method: 'DELETE' });
    setHistoryBusy(false);
    if (!response.ok) { setError(response.error || 'Could not delete the saved scan.'); return; }
    if (batchJob?.job_id === job.job_id) { setBatchJob(null); setBatchResult(null); }
    void refreshSavedJobs();
  };

  const copyGptPrompt = async () => {
    const response = await fetchJson<{ prompt: string }>(`/api/backtest/gpt-prompt?symbol=${encodeURIComponent(symbol)}`);
    if (!response.ok) { setCopyStatus('Could not load prompt'); return; }
    await navigator.clipboard.writeText(response.data.prompt);
    setCopyStatus('GPT prompt copied');
    window.setTimeout(() => setCopyStatus(''), 2500);
  };

  const askBacktestAi = async () => {
    const analysisJobId = batchJob?.job_id || drilldownJobId;
    if (!analysisJobId || !analysisQuestion.trim()) return;
    setAnalysisBusy(true); setAnalysisAnswer(null);
    const response = await fetchJson<AiBacktestAnalysis>(`/api/backtest/batch/jobs/${encodeURIComponent(analysisJobId)}/ask`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: analysisQuestion, symbol: stockDrilldown?.symbol || undefined, include_non_equities: !ordinarySharesOnly, max_listing_age_days: maxScriptAgeDays, min_volume: minimumVolume, manual_filters: advancedFilters.filter((filter) => filter.value.trim()).map(({ field, operator, value }) => ({ field, operator, value })) }),
    }, 120000);
    setAnalysisBusy(false);
    if (response.ok) setAnalysisAnswer(response.data);
    else setError(response.error || 'AI could not analyze this saved scan.');
  };

  const visiblePresets = presets.filter((preset) => `${preset.name} ${preset.category} ${preset.description}`.toLowerCase().includes(presetSearch.toLowerCase()));
  const togglePreset = (id: string) => setSelectedPresets((current) => { const next = new Set(current); next.has(id) ? next.delete(id) : next.add(id); return next; });
  const addAdvancedFilter = () => setAdvancedFilters((current) => [...current, { id: nextAdvancedFilterId.current++, field: 'total_trades', operator: 'gte', value: '20' }]);
  const updateAdvancedFilter = (id: number, changes: Partial<AdvancedFilter>) => setAdvancedFilters((current) => current.map((filter) => {
    if (filter.id !== id) return filter;
    const next = { ...filter, ...changes };
    if (changes.field) next.operator = advancedFilterFields.find((field) => field.key === changes.field)?.type === 'text' ? 'contains' : 'gte';
    return next;
  }));
  const universeRankings = useMemo(() => batchResult?.rankings.filter((row) => (!ordinarySharesOnly || row.security_type === 'ordinary_share') && (maxScriptAgeDays === null || (row.listing_age_days != null && row.listing_age_days <= maxScriptAgeDays)) && (minimumVolume === null || (row.latest_volume != null && row.latest_volume >= minimumVolume)) && matchesAdvancedFilters(row, advancedFilters)) || [], [advancedFilters, batchResult, maxScriptAgeDays, minimumVolume, ordinarySharesOnly]);
  const visibleStockSummary = useMemo(() => {
    if (!batchResult) return [];
    const symbols = new Set(universeRankings.map((row) => row.symbol));
    return batchResult.stock_summary.filter((row) => symbols.has(row.symbol));
  }, [batchResult, universeRankings]);
  const visiblePresetSummary = useMemo(() => {
    if (!batchResult) return [];
    return batchResult.preset_summary.map((preset) => {
      const rows = universeRankings.filter((row) => row.preset_id === preset.preset_id && row.total_trades > 0);
      return { ...preset, symbols_tested: rows.length, average_win_rate_pct: rows.length ? Number((rows.reduce((sum, row) => sum + row.win_rate_pct, 0) / rows.length).toFixed(2)) : 0, average_return_pct: rows.length ? Number((rows.reduce((sum, row) => sum + row.net_return_pct, 0) / rows.length).toFixed(2)) : 0, profitable_symbols: rows.filter((row) => row.net_return_pct > 0).length, strong_samples: rows.filter((row) => row.sample_quality === 'strong').length };
    }).sort((left, right) => right.average_win_rate_pct - left.average_win_rate_pct || right.average_return_pct - left.average_return_pct);
  }, [batchResult, universeRankings]);
  const filteredRankings = useMemo(() => {
    if (!batchResult) return [];
    const source = rankingMode === 'confidence' ? batchResult.reliable_rankings : batchResult.rankings;
    const search = resultSearch.trim().toLowerCase();
    return source.filter((row) => (!ordinarySharesOnly || row.security_type === 'ordinary_share') && (maxScriptAgeDays === null || (row.listing_age_days != null && row.listing_age_days <= maxScriptAgeDays)) && (minimumVolume === null || (row.latest_volume != null && row.latest_volume >= minimumVolume)) && matchesAdvancedFilters(row, advancedFilters) && row.total_trades >= minimumTrades && (!search || `${row.symbol} ${row.preset_name} ${row.category}`.toLowerCase().includes(search)));
  }, [advancedFilters, batchResult, maxScriptAgeDays, minimumTrades, minimumVolume, ordinarySharesOnly, rankingMode, resultSearch]);

  const downloadAllResults = () => {
    if (!batchResult) return;
    const header = ['rank', 'symbol', 'sector', 'ltp', 'listing_age_days', 'latest_volume', 'preset', 'category', 'trades', 'win_rate_pct', 'confidence', 'return_pct', 'drawdown_pct', 'sharpe', 'sample'];
    const rows = universeRankings.map((row, index) => [index + 1, row.symbol, row.sector ?? '', row.ltp ?? '', row.listing_age_days ?? '', row.latest_volume ?? '', row.preset_name, row.category, row.total_trades, row.win_rate_pct, row.confidence_score, row.net_return_pct, row.max_drawdown_pct, row.sharpe_ratio ?? '', row.sample_quality]);
    const csv = [header, ...rows].map((row) => row.map((value) => `"${String(value).replaceAll('"', '""')}"`).join(',')).join('\n');
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    const anchor = document.createElement('a');
    anchor.href = url; anchor.download = `nepse-${presets.length}-presets-${marketStartDate}-${marketEndDate}.csv`; anchor.click();
    URL.revokeObjectURL(url);
  };

  const metrics = result ? [
    ['Win rate', `${result.summary.win_rate_pct}%`, 'primary'],
    ['Net return', `${result.summary.net_return_pct}%`, result.summary.net_return_pct >= 0 ? 'positive' : 'negative'],
    ['Net profit', money(result.summary.net_profit), result.summary.net_profit >= 0 ? 'positive' : 'negative'],
    ['Trades', String(result.summary.total_trades), ''],
    ['Wins / losses', `${result.summary.wins} / ${result.summary.losses}`, ''],
    ['Max drawdown', `${result.summary.max_drawdown_pct}%`, 'negative'],
    ['Profit factor', result.summary.profit_factor === null ? '—' : String(result.summary.profit_factor), ''],
    ['Final equity', money(result.summary.final_equity), ''],
    ['Sharpe', result.summary.sharpe_ratio === null ? '—' : String(result.summary.sharpe_ratio), ''],
    ['Sortino', result.summary.sortino_ratio === null ? '—' : String(result.summary.sortino_ratio), ''],
    ['CAGR', result.summary.cagr_pct === null ? '—' : `${result.summary.cagr_pct}%`, ''],
    ['Exposure', `${result.summary.exposure_pct}%`, ''],
    ['Benchmark', `${result.summary.benchmark_return_pct}%`, ''],
    ['Alpha', `${result.summary.alpha_vs_benchmark_pct}%`, result.summary.alpha_vs_benchmark_pct >= 0 ? 'positive' : 'negative'],
    ['Expectancy', `${result.summary.expectancy_pct}%`, result.summary.expectancy_pct >= 0 ? 'positive' : 'negative'],
    ['Market charges', money(result.summary.total_charges), ''],
    ['CGT', money(result.summary.total_taxes), ''],
    ['Slippage', money(result.summary.total_slippage_cost), ''],
  ] : [];

  return (
    <div className="backtest-page">
      {stockDrilldown && <section className="backtest-card"><div className="backtest-section-heading"><div><h2>{stockDrilldown.symbol} saved strategy analysis</h2><p>Every stored preset result for this stock · scan {stockDrilldown.status} · indicators {stockDrilldown.technical_snapshot.as_of_date || 'pending'}</p></div><span className="backtest-source-badge">{stockDrilldown.technical_snapshot.engine_version || 'OHLCV'}</span></div>{stockDrilldown.technical_snapshot.indicators && <><h3>Latest technical snapshot</h3><CommonTable data={[stockDrilldown.technical_snapshot.indicators]} columns={['technical_signal', 'technical_signal_score', 'technical_buy_score', 'technical_sell_score', 'technical_rsi_14', 'technical_mfi_14', 'technical_adx_14', 'technical_macd_histogram', 'technical_atr_percent', 'technical_percent_b', 'technical_stochastic_k_14', 'technical_volume_ratio_20', 'technical_historical_volatility_20']} columnLabels={{ technical_signal: 'Signal', technical_signal_score: 'Signal Score', technical_buy_score: 'Buy Score', technical_sell_score: 'Sell Score', technical_rsi_14: 'RSI 14', technical_mfi_14: 'MFI 14', technical_adx_14: 'ADX 14', technical_macd_histogram: 'MACD Histogram', technical_atr_percent: 'ATR %', technical_percent_b: 'Bollinger %B', technical_stochastic_k_14: 'Stochastic %K', technical_volume_ratio_20: 'Volume Ratio', technical_historical_volatility_20: 'Volatility %' }} /></>}<h3>Preset backtests</h3><CommonTable data={stockDrilldown.results} columns={['preset_name', 'category', 'sample_quality', 'total_trades', 'win_rate_pct', 'confidence_score', 'net_return_pct', 'max_drawdown_pct', 'sharpe_ratio', 'technical_signal', 'technical_signal_score', 'technical_buy_score', 'technical_sell_score']} columnLabels={{ preset_name: 'Preset', sample_quality: 'Sample', total_trades: 'Trades', win_rate_pct: 'Win Rate %', confidence_score: 'Confidence', net_return_pct: 'Return %', max_drawdown_pct: 'Drawdown %', sharpe_ratio: 'Sharpe', technical_signal: 'TA Signal', technical_signal_score: 'TA Score', technical_buy_score: 'Buy Score', technical_sell_score: 'Sell Score' }} emptyMessage="This stock has not finished processing yet." /><p className="backtest-data-note">The custom strategy editor below is preselected for {stockDrilldown.symbol}; edit the strategy language and run a separate one-stock test.</p></section>}
      <div className="backtest-mode-tabs" role="tablist" aria-label="Backtest mode">
        <button type="button" className={mode === 'custom' ? 'active' : ''} onClick={() => setMode('custom')}>Custom query</button>
        <button type="button" className={mode === 'market' ? 'active' : ''} onClick={() => setMode('market')}>NEPSE preset scanner <span>{presets.length}</span></button>
      </div>
      <form className="backtest-card backtest-form" onSubmit={mode === 'custom' ? run : runBatch}>
        <div className="backtest-section-heading"><div><h2>{mode === 'custom' ? 'Custom strategy language' : `All-stock × ${presets.length}-preset scan`}</h2><p>{mode === 'custom' ? 'Write the entry and risk configuration in one auditable query.' : 'Test every available NEPSE stock and sort each stock × preset result by win rate.'}</p></div><span className="backtest-source-badge">{mode === 'custom' ? 'Apache ECharts + custom data' : '2018–today historical OHLCV'}</span></div>
        <div className="backtest-grid">
          {mode === 'custom' && <label>NEPSE symbol<input value={symbol} onChange={(event) => updateSymbol(event.target.value)} required /></label>}
          <label>Start date<input type="date" value={mode === 'custom' ? startDate : marketStartDate} onChange={(event) => mode === 'custom' ? setStartDate(event.target.value) : setMarketStartDate(event.target.value)} required /></label>
          <label>End date<input type="date" value={mode === 'custom' ? endDate : marketEndDate} onChange={(event) => mode === 'custom' ? setEndDate(event.target.value) : setMarketEndDate(event.target.value)} required /></label>
          {mode === 'market' && <label>History source<select value={marketDataSource} onChange={(event) => setMarketDataSource(event.target.value as 'merolagani' | 'combined')}><option value="merolagani">Full adjusted history</option><option value="combined">Stored combined snapshots</option></select></label>}
          {mode === 'market' && <label>Instrument universe<select value={ordinarySharesOnly ? 'ordinary' : 'all'} onChange={(event) => setOrdinarySharesOnly(event.target.value === 'ordinary')}><option value="ordinary">Ordinary shares only (recommended)</option><option value="all">All instruments</option></select></label>}
          {mode === 'market' && <label>Maximum script age<select value={maxScriptAgeDays ?? ''} onChange={(event) => setMaxScriptAgeDays(event.target.value ? Number(event.target.value) : null)}><option value="">All listing ages</option><option value="30">30 days</option><option value="90">90 days</option><option value="180">180 days</option><option value="365">1 year</option><option value="1095">3 years</option><option value="1825">5 years</option></select></label>}
          {mode === 'market' && <label>Minimum latest volume<input type="number" min="0" step="1000" placeholder="No minimum" value={minimumVolume ?? ''} onChange={(event) => setMinimumVolume(event.target.value ? Math.max(0, Number(event.target.value)) : null)} /></label>}
        </div>
        {mode === 'market' && <div className="advanced-filter-builder">
          <div className="advanced-filter-heading"><div><strong>Custom stock and result filters</strong><span>Combine any conditions below. Every condition must match.</span></div><button type="button" onClick={addAdvancedFilter}>+ Add filter</button></div>
          {advancedFilters.length === 0 ? <p>Add filters for sector, price, liquidity, history, win rate, return, drawdown, technical score, and more.</p> : <div className="advanced-filter-list">{advancedFilters.map((filter) => {
            const definition = advancedFilterFields.find((field) => field.key === filter.field) || advancedFilterFields[0];
            const operators = definition.type === 'number' ? numericFilterOperators : textFilterOperators;
            return <div className="advanced-filter-row" key={filter.id}>
              <select aria-label="Filter field" value={filter.field} onChange={(event) => updateAdvancedFilter(filter.id, { field: event.target.value as AdvancedFilterField })}>{advancedFilterFields.map((field) => <option value={field.key} key={field.key}>{field.label}</option>)}</select>
              <select aria-label="Filter operator" value={filter.operator} onChange={(event) => updateAdvancedFilter(filter.id, { operator: event.target.value })}>{operators.map((operator) => <option value={operator.key} key={operator.key}>{operator.label}</option>)}</select>
              <input aria-label="Filter value" type={definition.type === 'number' ? 'number' : 'text'} step="any" placeholder={definition.type === 'number' ? 'Value' : 'Text'} value={filter.value} onChange={(event) => updateAdvancedFilter(filter.id, { value: event.target.value })} />
              <button type="button" className="remove-filter" onClick={() => setAdvancedFilters((current) => current.filter((item) => item.id !== filter.id))}>Remove</button>
            </div>;
          })}</div>}
          {advancedFilters.length > 0 && <button type="button" className="clear-filters" onClick={() => setAdvancedFilters([])}>Clear custom filters</button>}
        </div>}
        {mode === 'custom' ? <>
          <div className="backtest-query-toolbar"><strong>Strategy query</strong><button type="button" onClick={copyGptPrompt}>Copy prompt for GPT</button>{copyStatus && <span>{copyStatus}</span>}</div>
          <label className="backtest-query-label"><textarea value={query} onChange={(event) => setQuery(event.target.value)} spellCheck={false} rows={19} /></label>
          {querySymbolMismatch && <p className="backtest-warning">The query symbol does not match the selected symbol.</p>}
        </> : <>
          <div className="preset-toolbar"><input type="search" placeholder={`Search ${presets.length} presets…`} value={presetSearch} onChange={(event) => setPresetSearch(event.target.value)} /><button type="button" onClick={() => setSelectedPresets(new Set(presets.map((item) => item.id)))}>Select all {presets.length}</button><button type="button" onClick={() => setSelectedPresets(new Set(visiblePresets.map((item) => item.id)))}>Select shown</button><button type="button" onClick={() => setSelectedPresets(new Set())}>Clear</button><span>{selectedPresets.size}/{presets.length} selected</span></div>
          <div className="preset-grid">{visiblePresets.map((preset) => <label key={preset.id} className={`preset-option${selectedPresets.has(preset.id) ? ' selected' : ''}`}><input type="checkbox" checked={selectedPresets.has(preset.id)} onChange={() => togglePreset(preset.id)} /><span><strong>{preset.name}</strong><small>{preset.category}</small><em>{preset.description}</em></span></label>)}</div>
          <p className="backtest-scan-note">Multi-core workers download and prepare each stock once, then reuse it across every selected preset. Progress and partial leaders are saved automatically, so you can leave this page and return later.</p>
          {indicatorStatus && <p className="backtest-scan-note">Technical engine {indicatorStatus.engine_version}: {indicatorStatus.stored_symbols} stock snapshots stored{indicatorStatus.running ? ` · backfilling ${indicatorStatus.completed}/${indicatorStatus.total}${indicatorStatus.current_symbol ? ` · ${indicatorStatus.current_symbol}` : ''}` : ''}{indicatorStatus.failed ? ` · ${indicatorStatus.failed} unavailable` : ''}.</p>}
        </>}
        {error && <div className="backtest-error" role="alert">{error}</div>}
        {mode === 'market' && batchJob && busy && <div className="backtest-progress" role="status"><div><strong>{batchJob.percent_complete}% complete · saved</strong><span>{batchJob.symbols_completed}/{batchJob.symbols_total || '…'} stocks · {batchJob.combinations_completed.toLocaleString()} combinations{batchJob.current_symbol ? ` · ${batchJob.current_symbol}` : ''}</span></div><progress value={batchJob.percent_complete} max="100" /><small>You can safely leave this page. This scan continues in the background and reconnects automatically.</small></div>}
        <div className="backtest-actions"><button type="submit" disabled={busy || (mode === 'custom' && Boolean(querySymbolMismatch))}>{busy ? (mode === 'custom' ? 'Loading history and testing…' : `Scanning ${batchJob?.symbols_completed || 0}/${batchJob?.symbols_total || '…'} stocks…`) : (mode === 'custom' ? 'Run custom backtest' : `Run ${selectedPresets.size} presets across all stocks`)}</button><span>No broker order is placed. Results are simulations, not financial advice.</span></div>
      </form>

      {mode === 'market' && busy && batchJob?.live_rankings && batchJob.live_rankings.length > 0 && <section className="backtest-card live-results-card"><div className="backtest-section-heading"><div><h2>Leaders so far</h2><p>Live results from {batchJob.symbols_completed} completed stocks. Click any heading to sort.</p></div><span className="live-pulse"><i /> Live</span></div><CommonTable data={batchJob.live_rankings.filter((row) => (!ordinarySharesOnly || row.security_type === 'ordinary_share') && (maxScriptAgeDays === null || (row.listing_age_days != null && row.listing_age_days <= maxScriptAgeDays)) && (minimumVolume === null || (row.latest_volume != null && row.latest_volume >= minimumVolume)) && matchesAdvancedFilters(row, advancedFilters))} columns={['symbol', 'sector', 'ltp', 'listing_age_days', 'latest_volume', 'preset_name', 'total_trades', 'win_rate_pct', 'confidence_score', 'net_return_pct', 'technical_signal', 'technical_signal_score', 'sample_quality']} columnLabels={{ ltp: 'LTP', listing_age_days: 'Age (Days)', latest_volume: 'Latest Volume', preset_name: 'Preset', total_trades: 'Trades', win_rate_pct: 'Win Rate %', confidence_score: 'Confidence', net_return_pct: 'Return %', technical_signal: 'TA Signal', technical_signal_score: 'TA Score', sample_quality: 'Sample' }} columnLinks={{ symbol: (row) => `/dashboard/backtest?job=${encodeURIComponent(batchJob.job_id)}&stock=${encodeURIComponent(String(row.symbol))}` }} /></section>}

      {mode === 'market' && <section className="backtest-card saved-scans"><div className="backtest-section-heading"><div><h2>Saved market scans</h2><p>Progress and completed results remain here until you delete them.</p></div><button type="button" className="backtest-export" onClick={() => void refreshSavedJobs()} disabled={historyBusy}>{historyBusy ? 'Refreshing…' : 'Refresh'}</button></div>{savedJobs.length === 0 ? <div className="backtest-empty">No saved market scans yet.</div> : <div className="saved-scan-grid">{savedJobs.map((job) => <article className={`saved-scan ${job.status}`} key={job.job_id}><div className="saved-scan-top"><span className={`job-status ${job.status}`}>{job.status}</span><time>{job.created_at ? new Date(job.created_at).toLocaleString() : ''}</time></div><strong>{job.parameters.preset_count} presets · {job.parameters.start_date} → {job.parameters.end_date}</strong><p>{job.symbols_completed}/{job.symbols_total || '…'} stocks · {job.combinations_completed.toLocaleString()} combinations · {job.parameters.workers} workers</p><progress value={job.percent_complete} max="100" /><div className="saved-scan-actions"><button type="button" onClick={() => void openSavedJob(job)}>{job.status === 'completed' ? 'Open results' : job.status === 'failed' ? 'View partial results' : 'Open live scan'}</button><button type="button" className="danger" disabled={job.status === 'queued' || job.status === 'running'} onClick={() => void deleteSavedJob(job)}>Delete</button></div></article>)}</div>}</section>}
      {(batchJob || drilldownJobId) && (mode === 'market' || stockDrilldown) && <section className="backtest-card"><div className="backtest-section-heading"><div><h2>Ask AI to find the top 10</h2><p>Describe what you want. AI writes a validated query, explains its selection logic, and returns the matching top 10 in a sortable table.</p></div></div><div className="ranking-toolbar"><input type="text" value={analysisQuestion} onChange={(event) => setAnalysisQuestion(event.target.value)} placeholder="Top 10 ordinary stocks with at least 20 trades, high volume, and low drawdown" /><button type="button" className="backtest-export" disabled={analysisBusy || !analysisQuestion.trim()} onClick={() => void askBacktestAi()}>{analysisBusy ? 'Writing and running query…' : 'Generate query + top 10'}</button></div>{analysisAnswer && <><div className="backtest-query-toolbar"><strong>Generated validated query</strong><span>{analysisAnswer.rows_analyzed.toLocaleString()} stored combinations analyzed</span></div><pre className="backtest-data-note">{analysisAnswer.generated_query}</pre><div className="backtest-data-note"><strong>Why this query:</strong> {analysisAnswer.explanation}<br />{analysisAnswer.note}</div><CommonTable data={analysisAnswer.results} columns={['symbol', 'listing_age_days', 'latest_volume', 'preset_name', 'category', 'sample_quality', 'total_trades', 'win_rate_pct', 'confidence_score', 'net_return_pct', 'max_drawdown_pct', 'sharpe_ratio', 'technical_signal_score']} columnLabels={{ listing_age_days: 'Age (Days)', latest_volume: 'Latest Volume', preset_name: 'Preset', sample_quality: 'Sample', total_trades: 'Trades', win_rate_pct: 'Win Rate %', confidence_score: 'Confidence', net_return_pct: 'Return %', max_drawdown_pct: 'Drawdown %', sharpe_ratio: 'Sharpe', technical_signal_score: 'TA Score' }} emptyMessage="No stored backtest rows matched the generated query." /></>}</section>}

      {mode === 'custom' && result && <>
        <section className="backtest-metrics" aria-label="Backtest summary">
          {metrics.map(([label, value, tone]) => <div className="backtest-metric" key={label}><span>{label}</span><strong className={tone}>{value}</strong></div>)}
        </section>
        <section className="backtest-card">
          <div className="backtest-section-heading"><div><h2>{result.symbol} performance</h2><p>{result.period.bars} sessions from {result.period.start} to {result.period.end}</p></div><span className="backtest-source-badge">Apache ECharts · Open source</span></div>
          <PerformanceChart result={result} />
          <div className="backtest-assumptions"><span>{result.assumptions.entry}</span><span>{result.assumptions.intraday_priority}</span><span>Tiered NEPSE brokerage</span><span>SEBON {result.assumptions.sebon_transaction_fee_pct_each_side ?? .015}% each side</span><span>DP NPR {result.assumptions.dp_charge_each_sell ?? 25} per sale</span><span>CGT by investor type and holding period</span></div>
        </section>
        <section className="backtest-card">
          <div className="backtest-section-heading"><div><h2>Win and loss details</h2><p>Every simulated entry and exit, including Nepal brokerage, SEBON, DP, CGT, and slippage.</p></div></div>
          {result.trades.length === 0 ? <div className="backtest-empty">No entry signals matched in this period. Adjust the query or date range.</div> : <div className="backtest-table-wrap"><table><thead><tr><th>Result</th><th>Rule</th><th>Entry</th><th>Exit</th><th>Qty</th><th>Held</th><th>Reason</th><th>Brokerage</th><th>SEBON</th><th>DP</th><th>CGT</th><th>Total charges</th><th>Return</th><th>P/L</th></tr></thead><tbody>{result.trades.map((trade) => <tr key={trade.id}><td><span className={`trade-result ${trade.result}`}>{trade.result.replace('_', ' ')}</span></td><td>{trade.rule_name}</td><td>{trade.entry_date}<small>{money(trade.entry_price)}</small></td><td>{trade.exit_date}<small>{money(trade.exit_price)}</small></td><td>{trade.quantity}</td><td>{trade.holding_days}d</td><td>{trade.exit_reason.replaceAll('_', ' ')}</td><td>{money(trade.broker_commission)}</td><td>{money(trade.sebon_fee)}</td><td>{money(trade.dp_charge)}</td><td>{money(trade.capital_gains_tax)}<small>{trade.capital_gains_tax_rate_pct}%</small></td><td>{money(trade.total_charges)}</td><td className={trade.return_pct >= 0 ? 'text-positive' : 'text-negative'}>{trade.return_pct}%</td><td className={trade.pnl >= 0 ? 'text-positive' : 'text-negative'}>{money(trade.pnl)}</td></tr>)}</tbody></table></div>}
        </section>
        <p className="backtest-data-note">Source: {result.data_source}. Historical performance does not guarantee future results.</p>
      </>}
      {mode === 'market' && batchResult && <>
        <section className="backtest-metrics" aria-label="Market scan summary">
          {[['Symbols', String(visibleStockSummary.length)], ['Presets', String(batchResult.presets_tested)], ['Combinations', universeRankings.length.toLocaleString()], ['Universe', ordinarySharesOnly ? 'Ordinary only' : 'All instruments']].map(([label, value]) => <div className="backtest-metric" key={label}><span>{label}</span><strong>{value}</strong></div>)}
        </section>
        <section className="backtest-card"><div className="backtest-section-heading"><div><h2>Best preset for every stock</h2><p>Click any column heading to sort; click a stock to open its full analysis in a new tab.</p></div><button type="button" className="backtest-export" onClick={downloadAllResults}>Download visible combinations CSV</button></div><CommonTable data={visibleStockSummary} columns={['symbol', 'listing_age_days', 'latest_volume', 'best_preset_name', 'best_win_rate_pct', 'best_total_trades', 'best_confidence_score', 'average_win_rate_pct', 'presets_with_trades', 'total_trades']} columnLabels={{ listing_age_days: 'Age (Days)', latest_volume: 'Latest Volume', best_preset_name: 'Best Preset', best_win_rate_pct: 'Win Rate %', best_total_trades: 'Best Trades', best_confidence_score: 'Confidence', average_win_rate_pct: 'Average Win %', presets_with_trades: 'Active Presets', total_trades: 'All Trades' }} columnLinks={batchJob ? { symbol: (row) => `/dashboard/backtest?job=${encodeURIComponent(batchJob.job_id)}&stock=${encodeURIComponent(String(row.symbol))}` } : undefined} /></section>
        <section className="backtest-card"><div className="backtest-section-heading"><div><h2>Preset leaderboard</h2><p>Which strategy shines across the selected instrument universe.</p></div></div><CommonTable data={visiblePresetSummary} columns={['preset_name', 'category', 'symbols_tested', 'average_win_rate_pct', 'average_return_pct', 'profitable_symbols', 'strong_samples']} columnLabels={{ preset_name: 'Preset', symbols_tested: 'Symbols', average_win_rate_pct: 'Average Win %', average_return_pct: 'Average Return %', profitable_symbols: 'Profitable', strong_samples: 'Strong Samples' }} /></section>
        <section className="backtest-card"><div className="backtest-section-heading"><div><h2>All stock × preset results</h2><p>{batchResult.ranking_note} Click a heading for direct table sorting.</p></div></div><div className="ranking-toolbar"><input type="search" placeholder="Filter stock or preset…" value={resultSearch} onChange={(event) => setResultSearch(event.target.value)} /><label>Minimum trades<input type="number" min="0" max="10000" value={minimumTrades} onChange={(event) => setMinimumTrades(Math.max(0, Number(event.target.value) || 0))} /></label><label>Initial order<select value={rankingMode} onChange={(event) => setRankingMode(event.target.value as 'win_rate' | 'confidence')}><option value="win_rate">Win rate descending</option><option value="confidence">Confidence-adjusted</option></select></label><strong>{filteredRankings.length.toLocaleString()} results</strong></div><CommonTable data={filteredRankings.slice(0, 2000)} columns={['symbol', 'listing_age_days', 'latest_volume', 'preset_name', 'category', 'sample_quality', 'total_trades', 'win_rate_pct', 'confidence_score', 'net_return_pct', 'max_drawdown_pct', 'sharpe_ratio', 'technical_signal', 'technical_signal_score', 'technical_buy_score', 'technical_sell_score']} columnLabels={{ listing_age_days: 'Age (Days)', latest_volume: 'Latest Volume', preset_name: 'Preset', sample_quality: 'Sample', total_trades: 'Trades', win_rate_pct: 'Win Rate %', confidence_score: 'Confidence', net_return_pct: 'Return %', max_drawdown_pct: 'Drawdown %', sharpe_ratio: 'Sharpe', technical_signal: 'TA Signal', technical_signal_score: 'TA Score', technical_buy_score: 'Buy Score', technical_sell_score: 'Sell Score' }} columnLinks={batchJob ? { symbol: (row) => `/dashboard/backtest?job=${encodeURIComponent(batchJob.job_id)}&stock=${encodeURIComponent(String(row.symbol))}` } : undefined} />{filteredRankings.length > 2000 && <p className="backtest-data-note">Showing the first 2,000 filtered rows. Download CSV for every combination.</p>}</section>
      </>}
    </div>
  );
};

export default Backtest;
