import React, { FormEvent, useEffect, useMemo, useRef, useState } from 'react';
import * as echarts from 'echarts/core';
import { BarChart, LineChart } from 'echarts/charts';
import { DataZoomComponent, GridComponent, LegendComponent, TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import { fetchJson } from '../../utils/api';
import NepseAlphaSymbolLink from '../../components/NepseAlphaSymbolLink';
import './BacktestV2.css';
import './BacktestV2Strategy.css';
import './StrongBuy.css';
import './StockScopePicker.css';

echarts.use([BarChart, LineChart, DataZoomComponent, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);

type Preset = { id: string; name: string; category: string; family: string; description: string };
type Run = {
  run_id: string; name: string; status: string; progress_pct: number; symbols_completed: number;
  symbols_total: number; combinations_completed: number; current_symbol?: string; created_at?: string;
  configuration: { start_date: string; end_date: string; preset_ids: string[]; ordinary_shares_only: boolean; strategy_mode?: 'presets' | 'custom'; custom_query_text?: string };
  error_summary?: string;
};
type ResultRow = Record<string, any> & { result_id: number; symbol: string; preset_name: string };
type ResultPage = { items: ResultRow[]; page: number; page_size: number; total: number; pages: number };
type Portfolio = { preset_id: string; preset_name: string; summary: Record<string, number>; allocation_config: Record<string, number> };
type Opportunity = ResultRow & { rank: number; recommendation_score: number; current_signal_status: string; signal_date: string; reliability_score: number; current_technical_score: number; wins: number; losses: number; loss_rate_pct: number; net_profit: number; ltp: number; latest_volume: number; legacy_cost_model: boolean; current_evidence: Record<string, any>; assumptions: Record<string, any> };
type OpportunityPage = { items: Opportunity[]; page: number; page_size: number; total: number; pages: number; disclaimer: string };
type TradePage = { items: Array<Record<string, any>>; page: number; page_size: number; total: number; pages: number };

const today = new Date().toISOString().slice(0, 10);
const defaultStart = '2018-01-01';
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

const BacktestV2: React.FC = () => {
  const params = useMemo(() => new URLSearchParams(window.location.search), []);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [runs, setRuns] = useState<Run[]>([]);
  const [activeRun, setActiveRun] = useState<Run | null>(null);
  const [name, setName] = useState('Full NEPSE robustness scan');
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
  const [tab, setTab] = useState<'opportunities' | 'combinations' | 'portfolio' | 'ai' | 'quality'>('opportunities');
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
  const [opportunityFilters, setOpportunityFilters] = useState({ minimum_trades: 5, minimum_win_rate: 0, minimum_confidence: 0, minimum_sharpe: -999, minimum_profit_factor: 0, maximum_drawdown: 100, minimum_return: 0, minimum_volume: '', category: '', current_signal: 'all', sort_by: 'recommendation_score' });
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
    if (!activeRun) return;
    const response = await fetchJson<OpportunityPage>(`/api/backtests/v2/runs/${activeRun.run_id}/strong-buys/query`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...opportunityFilters, minimum_volume: opportunityFilters.minimum_volume ? Number(opportunityFilters.minimum_volume) : null, category: opportunityFilters.category || null, include_non_equities: includeNonEquities, page, page_size: opportunities.page_size }),
    });
    if (response.ok) setOpportunities(response.data); else setError(response.error || 'Could not load current opportunities.');
  };

  useEffect(() => { if (tab === 'opportunities') void loadOpportunities(1); }, [activeRun?.run_id, activeRun?.combinations_completed, tab, opportunityFilters, includeNonEquities, opportunities.page_size]);

  const openOpportunity = async (row: Opportunity) => {
    setDetailBusy(true); setTradeFilter('all');
    const [detailResponse, tradesResponse] = await Promise.all([
      fetchJson<any>(`/api/backtests/v2/runs/${activeRun?.run_id}/strong-buys/${row.symbol}?result_id=${row.result_id}`),
      fetchJson<TradePage>(`/api/backtests/v2/results/${row.result_id}/trades?page=1&page_size=100&result_filter=all`),
    ]);
    setDetailBusy(false);
    if (detailResponse.ok && tradesResponse.ok) { setSelectedOpportunity(detailResponse.data); setDetailTrades(tradesResponse.data); }
    else setError((!detailResponse.ok && detailResponse.error) || (!tradesResponse.ok && tradesResponse.error) || 'Could not load recommendation details.');
  };

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
      body: JSON.stringify({ name, start_date: startDate, end_date: endDate, strategy_mode: strategyMode, custom_query_text: strategyMode === 'custom' ? customQuery : null, preset_ids: strategyMode === 'presets' ? Array.from(selected) : [], symbols: runScope === 'single' && selectedStock ? [selectedStock.symbol] : null, ordinary_shares_only: ordinaryOnly, min_holding_days: minHoldingDays, max_holding_days: maxHoldingDays ? Number(maxHoldingDays) : null, data_source: 'merolagani', max_workers: runScope === 'single' ? 1 : 8, run_type: runScope === 'single' ? 'single_stock' : 'market_scan' }),
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

  return <div className="research-page">
    <header className="research-hero">
      <div><span className="research-kicker">NEPSE Research Lab · Daily data</span><h1>Backtesting workspace</h1><p>Reproducible out-of-sample rankings, shared-capital simulation, and persistent background scans.</p></div>
      <div className="research-hero-actions"><a href="/dashboard/backtest?legacy=1">Custom strategy language</a><span>Research only · no broker orders</span></div>
    </header>

    {error && <div className="research-alert" role="alert">{error}<button onClick={() => setError('')}>Dismiss</button></div>}

    <section className="research-layout">
      <aside className="research-sidebar">
        <div className="research-side-heading"><h2>Saved runs</h2><button onClick={() => void loadRuns()}>Refresh</button></div>
        <div className="research-runs">{runs.length === 0 ? <p>No v2 research runs yet.</p> : runs.map((run) => <button key={run.run_id} className={activeRun?.run_id === run.run_id ? 'active' : ''} onClick={() => setActiveRun(run)}><span><b>{run.name}</b><small>{run.symbols_completed}/{run.symbols_total} stocks · {run.combinations_completed.toLocaleString()} results</small></span><em className={`run-${run.status}`}>{run.status}</em></button>)}</div>
      </aside>

      <main className="research-main">
        <details className="research-new-run" open={!activeRun}>
          <summary><span><b>New research run</b><small>Name it, select the universe and strategies, then leave it running safely in the background.</small></span><strong>Configure</strong></summary>
          <form onSubmit={startRun}>
            <div className="research-form-grid"><label>Run name<input value={name} onChange={(e) => setName(e.target.value)} required /></label><label>Start<input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} required /></label><label>End<input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} required /></label><label>Universe<select value={ordinaryOnly ? 'ordinary' : 'all'} onChange={(e) => setOrdinaryOnly(e.target.value === 'ordinary')}><option value="ordinary">Ordinary shares only</option><option value="all">All instrument classes</option></select></label><label>Stocks to test<select value={runScope} onChange={(e) => { setRunScope(e.target.value as 'all' | 'single'); setSelectedStock(null); setStockSearch(''); }}><option value="all">All stocks in universe</option><option value="single">One particular stock</option></select></label><label>Strategy source<select value={strategyMode} onChange={(e) => setStrategyMode(e.target.value as 'presets' | 'custom')}><option value="presets">Professional presets</option><option value="custom">One custom query</option></select></label><label>Minimum hold (days)<input type="number" min="0" max="365" value={minHoldingDays} onChange={(e) => setMinHoldingDays(Math.max(0, Number(e.target.value) || 0))} /><small>Stop-loss protection remains active.</small></label><label>Maximum hold (days)<input type="number" min="1" max="365" value={maxHoldingDays} onChange={(e) => setMaxHoldingDays(e.target.value)} placeholder="Use preset/query default" /><small>Blank preserves each strategy default.</small></label></div>
            {runScope === 'single' && <div className="stock-picker"><label>Find stock by symbol or company name<input value={stockSearch} onChange={(e) => { setStockSearch(e.target.value.toUpperCase()); setSelectedStock(null); }} placeholder="Type NABIL or Nabil Bank…" autoComplete="off" required /></label>{selectedStock && <div className="selected-stock"><b>{selectedStock.symbol}</b><span>{selectedStock.company_name}</span><em>{selectedStock.sector || 'Sector unavailable'}</em></div>}{stockSuggestions.length > 0 && <div className="stock-suggestions" role="listbox">{stockSuggestions.map((item) => <button type="button" role="option" aria-selected={selectedStock?.symbol === item.symbol} key={item.symbol} onClick={() => { setSelectedStock(item); setStockSearch(item.symbol); setStockSuggestions([]); setName(`${item.symbol} strategy research`); }}><b>{item.symbol}</b><span>{item.company_name}</span><em>{item.sector || ''}</em></button>)}</div>}<small>All selected presets will run only on the chosen stock. This does not affect saved all-market runs.</small></div>}
            {strategyMode === 'presets' ? <><div className="research-preset-head"><span><b>Preset catalog</b><small>{selected.size}/{presets.length} selected · grouped by family</small></span><div><button type="button" onClick={() => setSelected(new Set(presets.map((item) => item.id)))}>All {presets.length}</button><button type="button" onClick={() => setSelected(new Set())}>Clear</button></div></div><div className="research-preset-groups">{grouped.map(([category, items]) => <details key={category}><summary>{category}<span>{items.filter((item) => selected.has(item.id)).length}/{items.length}</span></summary><div>{items.map((preset) => <label key={preset.id} title={preset.description}><input type="checkbox" checked={selected.has(preset.id)} onChange={() => setSelected((current) => { const next = new Set(current); next.has(preset.id) ? next.delete(preset.id) : next.add(preset.id); return next; })} /><span>{preset.name}</span></label>)}</div></details>)}</div></> : <div className="research-custom-query"><div><span><b>Custom Strategy Language</b><small>The symbol in this query is a template. For an all-stock run, the server safely retargets only the symbol and keeps every condition, risk setting, charge, and order-sizing rule unchanged.</small></span><button type="button" onClick={() => void copyGptPrompt()}>Copy prompt for GPT</button>{copyStatus && <em>{copyStatus}</em>}</div><textarea value={customQuery} onChange={(e) => setCustomQuery(e.target.value)} rows={20} spellCheck={false} /></div>}
            <div className="research-submit"><p>History is cached per stock. The exact versioned query is stored with every result and can be promoted to paper, then separately confirmed for live scheduling.</p><button disabled={creating || (strategyMode === 'presets' ? selected.size === 0 : customQuery.trim().length < 20)}>{creating ? 'Queuing…' : strategyMode === 'custom' ? `Queue query on ${runScope === 'all' ? 'all stocks' : selectedStock?.symbol || 'one stock'}` : `Queue ${selected.size} strategies`}</button></div>
          </form>
        </details>

        {activeRun && <>
          <section className="research-run-head"><div><span className={`run-${activeRun.status}`}>{activeRun.status}</span><h2>{activeRun.name}</h2><p>{activeRun.configuration.start_date} → {activeRun.configuration.end_date} · ordinary shares {activeRun.configuration.ordinary_shares_only ? 'default' : 'not restricted'}</p></div><div className="research-controls">{activeRun.status === 'running' && <button onClick={() => void control('pause')}>Pause</button>}{activeRun.status === 'paused' && <button onClick={() => void control('resume')}>Resume</button>}{activeRun.status === 'failed' && <button onClick={() => void control('retry')}>Retry failed</button>}{['queued', 'running', 'paused'].includes(activeRun.status) && <button className="danger" onClick={() => void control('cancel')}>Cancel</button>}</div></section>
          <section className="research-progress"><div><b>{activeRun.progress_pct}%</b><span>{activeRun.symbols_completed}/{activeRun.symbols_total} stocks</span><span>{activeRun.combinations_completed.toLocaleString()} persisted results</span><span>{activeRun.current_symbol || 'Waiting for next checkpoint'}</span></div><progress value={activeRun.progress_pct} max="100" /><small>Partial rankings below update after every completed stock. You may leave this page and return later.</small></section>
          <nav className="research-tabs">{([['opportunities', 'Recommendations'], ['combinations', 'Combinations'], ['portfolio', 'Portfolio'], ['ai', 'Ask AI'], ['quality', 'Data quality']] as const).map(([key, label]) => <button key={key} className={tab === key ? 'active' : ''} onClick={() => setTab(key)}>{label}</button>)}</nav>

          {tab === 'opportunities' && <section className="research-panel strong-buy-panel">
            <div className="research-panel-title"><div><span className="current-session-badge">Saved and partial run results</span><h3>Backtest stock recommendations</h3><p>One best strategy per stock, ranked from historical win rate, net return, sample size, and reliability. Use the signal filter to isolate strategies triggered on the latest session or close to their entry conditions.</p></div></div>
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
              <label>Sort by<select value={opportunityFilters.sort_by} onChange={(e) => setOpportunityFilters((v) => ({ ...v, sort_by: e.target.value }))}><option value="recommendation_score">Best win + profit score</option><option value="win_rate_pct">Win rate</option><option value="net_return_pct">Net return</option><option value="reliability_score">Reliability score</option><option value="total_trades">Total trades</option><option value="profit_factor">Profit factor</option><option value="sharpe_ratio">Sharpe ratio</option><option value="max_drawdown_pct">Drawdown</option><option value="current_signal_date">Signal date</option></select></label>
            </div>
            <div className="research-table-summary"><b>{opportunities.total} ranked stocks</b><span>One best saved strategy per stock · ordinary shares by default</span></div>
            <div className="research-table-wrap strong-buy-table"><table><thead><tr>{['Rank','Stock','Signal state','Strategy','Best score','LTP','Data session','Win rate','Wins','Losses','Trades','Avg hold','Loss rate','Confidence','Net return %','Net profit','Profit factor','Max drawdown','Sharpe','Reliability','Conditions ready','Latest volume',''].map((label) => <th key={label}>{label}</th>)}</tr></thead><tbody>{opportunities.items.map((row) => <tr key={row.result_id}><td>{row.rank}</td><td><div className="stock-chart-links"><button className="symbol-link" onClick={() => void openOpportunity(row)}>{row.symbol}</button><NepseAlphaSymbolLink symbol={row.symbol}>NEPSE Alpha chart ↗</NepseAlphaSymbolLink></div></td><td><span className={`signal-pill ${row.current_signal_status}`}>{signalLabel(row.current_signal_status)}</span>{row.legacy_cost_model && <small>Legacy costs · rerun advised</small>}</td><td>{row.preset_name}</td><td><b>{fmt(row.recommendation_score, 'score')}</b></td><td>{fmt(row.ltp, 'ltp')}</td><td>{row.signal_date}</td><td><b>{fmt(row.win_rate_pct, 'percent')}%</b><small>Historical result</small></td><td>{row.wins}</td><td>{row.losses}</td><td>{row.total_trades}</td><td>{fmt(row.average_holding_days, 'days')} days</td><td>{fmt(row.loss_rate_pct, 'percent')}%</td><td>{fmt(row.confidence_score, 'score')}</td><td>{fmt(row.net_return_pct, 'percent')}%</td><td>NPR {fmt(row.net_profit, 'money')}</td><td>{fmt(row.profit_factor, 'ratio')}</td><td>{fmt(row.max_drawdown_pct, 'percent')}%</td><td>{fmt(row.sharpe_ratio, 'ratio')}</td><td><span className="reliability-ring">{fmt(row.reliability_score, 'score')}</span></td><td>{row.current_evidence?.conditions_total ? `${row.current_evidence.conditions_passed}/${row.current_evidence.conditions_total} · ${fmt(row.current_evidence.condition_progress_pct, 'percent')}%` : 'Available after rerun'}</td><td>{fmt(row.latest_volume, 'latest_volume')}</td><td><button className="view-evidence" onClick={() => void openOpportunity(row)}>View details</button></td></tr>)}</tbody></table>{opportunities.items.length === 0 && <div className="research-empty">No stocks match these exact filters. Select “Best available” or relax a numeric filter to view the saved run leaders.</div>}</div>
            <div className="research-pagination"><button disabled={opportunities.page <= 1} onClick={() => void loadOpportunities(opportunities.page - 1)}>Previous</button><span>Page {opportunities.page} of {opportunities.pages || 1}</span><button disabled={opportunities.page >= opportunities.pages} onClick={() => void loadOpportunities(opportunities.page + 1)}>Next</button></div>
            <p className="strong-buy-disclaimer">Backtested historical performance does not guarantee future results. This is research, not financial advice, and never places a broker order.</p>
          </section>}

          {tab === 'combinations' && <section className="research-panel">
            <div className="research-filter-grid"><label>Symbol<input value={symbolFilter} onChange={(e) => setSymbolFilter(e.target.value)} placeholder="NABIL" /></label><label>Sector<input value={sectorFilter} onChange={(e) => setSectorFilter(e.target.value)} placeholder="Commercial Bank" /></label><label>Min OOS trades<input type="number" min="0" value={minimumTrades} onChange={(e) => setMinimumTrades(Number(e.target.value) || 0)} /></label><label>Min robust score<input type="number" min="0" max="100" value={minimumScore} onChange={(e) => setMinimumScore(Number(e.target.value) || 0)} /></label><label>Min latest volume<input type="number" min="0" value={minimumVolume} onChange={(e) => setMinimumVolume(e.target.value)} /></label><label>Max listing age (days)<input type="number" min="1" value={maxAge} onChange={(e) => setMaxAge(e.target.value)} /></label><label>Instrument class<select value={includeNonEquities ? 'all' : 'ordinary'} onChange={(e) => setIncludeNonEquities(e.target.value === 'all')}><option value="ordinary">Ordinary shares only</option><option value="all">Explicitly include all</option></select></label><label>Rows<select value={results.page_size} onChange={(e) => setResults((current) => ({ ...current, page_size: Number(e.target.value) }))}><option>25</option><option>50</option><option>100</option></select></label></div>
            <div className="research-table-summary"><b>{results.total.toLocaleString()} matching simulations</b><span>Ranked by {sort.key.replaceAll('_', ' ')} {sort.direction}</span></div>
            <div className="research-table-wrap"><table><thead><tr>{columns.map(([key, label]) => <th key={key} onClick={() => toggleSort(key)}>{label}{sort.key === key ? (sort.direction === 'desc' ? ' ↓' : ' ↑') : ''}</th>)}</tr></thead><tbody>{results.items.map((row) => <tr key={row.result_id} className={row.recommendation_status === 'recommended' ? 'recommended' : ''}>{columns.map(([key]) => <td key={key}>{key === 'symbol' ? <div className="stock-chart-links"><a target="_blank" rel="noreferrer" href={`/dashboard/backtest?run=${activeRun.run_id}&stock=${row.symbol}`}>{row.symbol}</a><NepseAlphaSymbolLink symbol={row.symbol}>Chart ↗</NepseAlphaSymbolLink></div> : key === 'robust_score' ? <span className={`score score-${Math.floor(Number(row[key] || 0) / 20)}`}>{fmt(row[key], key)}</span> : fmt(row[key], key)}</td>)}</tr>)}</tbody></table>{results.items.length === 0 && <div className="research-empty">No result matches these exact filters. Filters were not silently weakened.</div>}</div>
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
      <section className="detail-section"><h3>Latest strategy signal evidence</h3><p className="evidence-reason">{selectedOpportunity.best.current_evidence?.reason}</p><code>{selectedOpportunity.best.current_evidence?.strategy_condition}</code>{selectedOpportunity.best.current_evidence?.conditions_total > 0 && <p><b>{selectedOpportunity.best.current_evidence.conditions_passed}/{selectedOpportunity.best.current_evidence.conditions_total}</b> entry conditions currently pass ({fmt(selectedOpportunity.best.current_evidence.condition_progress_pct, 'percent')}%). “Near trigger” is readiness evidence, not a forecast.</p>}<div className="latest-values">{Object.entries(selectedOpportunity.best.current_evidence?.latest_values || {}).map(([key, value]) => <div key={key}><span>{key.replaceAll('_', ' ')}</span><b>{fmt(value, key)}</b></div>)}</div><h4>Condition checks</h4><div className="condition-checks">{(selectedOpportunity.best.current_evidence?.conditions || []).map((condition: any, index: number) => <div className={condition.matched ? 'passed' : 'failed'} key={`${condition.expression}-${index}`}><b>{condition.matched ? 'Passed' : 'Failed'}</b><span>{condition.expression}</span>{condition.message && <small>{condition.message}</small>}</div>)}</div></section>
      <section className="detail-section"><h3>How reliability was calculated</h3><div className="score-breakdown">{Object.entries(selectedOpportunity.best.current_evidence?.reliability?.components || {}).map(([key, value]) => <div key={key}><span>{key.replaceAll('_', ' ')}</span><b>+{fmt(value, key)}</b></div>)}</div>{(selectedOpportunity.best.current_evidence?.reliability?.penalties || []).map((penalty: any) => <p className="score-penalty" key={penalty.code}>−{penalty.points} · {penalty.code.replaceAll('_', ' ')}</p>)}</section>
      <section className="detail-section"><h3>Complete historical backtest summary</h3><div className="historical-summary">{Object.entries(selectedOpportunity.best.assumptions?.summary || {}).map(([key, value]) => <div key={key}><span>{key.replaceAll('_', ' ')}</span><b>{fmt(value, key)}</b></div>)}</div><div className="risk-config"><span>Stop loss {selectedOpportunity.best.assumptions?.stop_loss_pct}%</span><span>Take profit {selectedOpportunity.best.assumptions?.take_profit_pct}%</span><span>Min hold {selectedOpportunity.best.assumptions?.min_holding_days || 0} days</span><span>Max hold {selectedOpportunity.best.assumptions?.max_holding_days} days</span>{String(selectedOpportunity.best.assumptions?.charge_model || '').startsWith('nepse_equity') ? <><span>NEPSE tiered brokerage</span><span>SEBON 0.015% each side</span><span>DP NPR 25 per sale</span><span>CGT by holding period</span></> : <span>Legacy flat-fee result · rerun for official Nepal charges</span>}<span>Strategy {selectedOpportunity.best.assumptions?.preset_version}</span><span>{selectedOpportunity.best.assumptions?.period?.start} → {selectedOpportunity.best.assumptions?.period?.end}</span></div></section>
      <section className="detail-section execution-promotion"><h3>Use the same query for trading</h3><p>The stored query—not a rewritten approximation—creates a paper draft first. Live scheduling remains a separate action with current account, balance, holdings, and risk checks.</p><div><label>TMS client ID<input value={paperClientId} onChange={(e) => setPaperClientId(e.target.value)} placeholder="Client ID" /></label><button disabled={promotionBusy || !paperClientId.trim()} onClick={() => void promoteToPaper()}>{promotionBusy ? 'Creating paper draft…' : 'Promote exact query to paper'}</button><a href="/dashboard/schedule-order">Open Schedule Order</a></div>{promotionMessage && <strong>{promotionMessage}</strong>}</section>
      <section className="detail-section"><h3>Equity, profit and drawdown</h3><StrongBuyCharts trades={detailTrades.items} /></section>
      <section className="detail-section"><div className="trade-heading"><div><h3>Complete wins and losses</h3><p>{detailTrades.total} historical trades · net results include brokerage, SEBON, DP, CGT, and slippage</p></div><select value={tradeFilter} onChange={(e) => void filterDetailTrades(e.target.value)}><option value="all">All trades</option><option value="wins">Wins only</option><option value="losses">Losses only</option><option value="stop_loss">Stop-loss exits</option><option value="take_profit">Take-profit exits</option></select></div><div className="research-table-wrap detail-trades"><table><thead><tr>{['Result','Strategy','Signal','Entry date','Entry price','Exit date','Exit price','Qty','Held','Exit reason','Gross return','Net return','Brokerage','SEBON','DP','CGT','Total charges','P/L','Running equity','Drawdown'].map((item) => <th key={item}>{item}</th>)}</tr></thead><tbody>{detailTrades.items.map((trade) => <tr key={trade.trade_id}><td><span className={`trade-${trade.result}`}>{trade.result}</span></td><td>{selectedOpportunity.best.preset_name}</td><td>{trade.signal_date || '—'}</td><td>{trade.entry_date}</td><td>{fmt(trade.entry_price, 'money')}</td><td>{trade.exit_date}</td><td>{fmt(trade.exit_price, 'money')}</td><td>{trade.quantity}</td><td>{trade.holding_days}d</td><td>{fmt(trade.exit_reason, 'reason')}</td><td>{trade.gross_return_pct}%</td><td>{trade.net_return_pct}%</td><td>NPR {fmt(trade.broker_commission, 'money')}</td><td>NPR {fmt(trade.sebon_fee, 'money')}</td><td>NPR {fmt(trade.dp_charge, 'money')}</td><td>NPR {fmt(trade.capital_gains_tax, 'money')}<small>{fmt(trade.capital_gains_tax_rate_pct, 'percent')}%</small></td><td>NPR {fmt(trade.total_charges, 'money')}</td><td>NPR {fmt(trade.pnl, 'money')}</td><td>NPR {fmt(trade.running_equity, 'money')}</td><td>{trade.drawdown_after_trade_pct}%</td></tr>)}</tbody></table></div></section>
      {selectedOpportunity.alternatives?.length > 0 && <section className="detail-section"><h3>Other saved strategies for this stock</h3><div className="alternative-strategies">{selectedOpportunity.alternatives.map((item: any) => <span key={item.result_id}>{item.preset_name} · {signalLabel(item.current_signal_status)} · reliability {item.reliability_score}</span>)}</div></section>}
      <p className="strong-buy-disclaimer">Backtested historical performance does not guarantee future results. No broker order is placed or scheduled from this view.</p>
    </div></div>}
  </div>;
};

export default BacktestV2;
