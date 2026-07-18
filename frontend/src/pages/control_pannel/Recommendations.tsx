import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchJson } from '../../utils/api';
import NepseAlphaSymbolLink from '../../components/NepseAlphaSymbolLink';
import './Recommendations.css';

type Row = Record<string, any>;
type Page = { items: Row[]; total: number; page: number; pages: number; persisted: boolean; trading_session?: string };
const money = (value: any) => value == null ? '—' : `NPR ${Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
const number = (value: any) => value == null ? '—' : Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 });

const Recommendations: React.FC = () => {
  const navigate = useNavigate();
  const [data, setData] = useState<Page>({ items: [], total: 0, page: 1, pages: 0, persisted: true });
  const [signal, setSignal] = useState('actionable'); const [search, setSearch] = useState('');
  const [minimumWin, setMinimumWin] = useState(0); const [minimumTrades, setMinimumTrades] = useState(5); const [minimumScore, setMinimumScore] = useState(0);
  const [sort, setSort] = useState({ field: 'recommendation_score', direction: 'desc' }); const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  const load = useCallback(async (page = 1) => { setBusy(true); setError(''); const response = await fetchJson<Page>('/api/market-recommendations/query', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ signal, search, minimum_win_rate: minimumWin, minimum_trades: minimumTrades, minimum_score: minimumScore, sort_by: sort.field, sort_direction: sort.direction, page, page_size: 50 }) }); setBusy(false); if (response.ok) setData(response.data); else setError(response.error || 'Could not load recommendations.'); }, [signal, search, minimumWin, minimumTrades, minimumScore, sort]);
  useEffect(() => { void load(1); }, [load]);
  const sortBy = (field: string) => setSort((current) => ({ field, direction: current.field === field && current.direction === 'desc' ? 'asc' : 'desc' }));
  const schedule = (row: Row) => { const query = row.assumptions?.strategy_query || ''; const symbol = row.symbol; let scheduleDraft: Record<string, unknown> = {}; let strategyDraft: Record<string, unknown> = {}; try { scheduleDraft = JSON.parse(localStorage.getItem('tms-schedule-order-draft-v1') || '{}'); } catch { scheduleDraft = {}; } try { strategyDraft = JSON.parse(localStorage.getItem('tms-strategy-form-draft-v1:schedule-order') || '{}'); } catch { strategyDraft = {}; } localStorage.setItem('tms-schedule-order-draft-v1', JSON.stringify({ ...scheduleDraft, scriptName: symbol, selectedScriptSymbol: symbol, orderType: 'buy', selectedStrategy: 'Custom Query Buy' })); localStorage.setItem('tms-strategy-form-draft-v1:schedule-order', JSON.stringify({ ...strategyDraft, strategy: 'Custom Query Buy', ruleQueryText: query })); navigate('/dashboard/schedule-order'); };
  const columns: Array<{ key: string; label: string; sortKey?: string }> = [
    { key: 'symbol', label: 'Stock', sortKey: 'symbol' }, { key: 'current_signal_status', label: 'Signal', sortKey: 'signal_status' },
    { key: 'preset_name', label: 'Strategy' }, { key: 'recommendation_score', label: 'Combined score', sortKey: 'recommendation_score' },
    { key: 'win_rate_pct', label: 'Win rate', sortKey: 'win_rate_pct' }, { key: 'total_trades', label: 'Trades', sortKey: 'total_trades' },
    { key: 'net_return_pct', label: 'Net return', sortKey: 'net_return_pct' }, { key: 'buy_zone_low', label: 'Buy from' },
    { key: 'buy_zone_high', label: 'Buy to' }, { key: 'protective_stop', label: 'Protective stop' },
    { key: 'sell_zone_low', label: 'Sell from' }, { key: 'sell_zone_high', label: 'Sell to' },
    { key: 'average_holding_days', label: 'Avg hold' }, { key: 'average_volume_20', label: '20D avg volume', sortKey: 'average_volume_20' },
    { key: 'signal_date', label: 'Trading session' },
  ];
  const renderCell = (row: Row, key: string) => {
    if (key === 'symbol') return <div className="recommendation-symbol"><button type="button" onClick={() => navigate(`/dashboard/backtest?run=${row.run_id}&stock=${row.symbol}&result=${row.result_id}`)}>{row.symbol}</button><NepseAlphaSymbolLink symbol={row.symbol}>NEPSE Alpha ↗</NepseAlphaSymbolLink></div>;
    if (key === 'current_signal_status') return <span className={`recommendation-signal ${row[key]}`}>{String(row[key] || '—').replaceAll('_', ' ')}</span>;
    if (key === 'preset_name' || key === 'signal_date') return String(row[key] || '—');
    if (key.includes('zone') || key === 'protective_stop') return money(row[key]);
    if (key.includes('rate') || key.includes('return') || key === 'recommendation_score') return `${number(row[key])}%`;
    if (key === 'average_holding_days') return `${number(row[key])} days`;
    return number(row[key]);
  };
  return <div className="recommendation-page"><header className="recommendation-hero"><div><span>Fresh decision workspace</span><h1>Market Recommendations</h1><p>Persisted signals combining current Market Analysis indicators with verified backtest performance.</p></div><div><b>{data.total}</b><small>ordinary shares · session {data.trading_session || 'pending'}</small></div></header><section className="recommendation-controls"><label>Signal<select value={signal} onChange={(e) => setSignal(e.target.value)}><option value="actionable">Strong Buy + Buy today</option><option value="strong_buy">Strong Buy only</option><option value="buy">Buy only</option><option value="near_trigger">Near trigger</option><option value="all">All recommendation states</option></select></label><label>Stock or strategy<input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="NABIL or momentum" /></label><label>Minimum win %<input type="number" min="0" max="100" value={minimumWin} onChange={(e) => setMinimumWin(Number(e.target.value) || 0)} /></label><label>Minimum trades<input type="number" min="0" value={minimumTrades} onChange={(e) => setMinimumTrades(Number(e.target.value) || 0)} /></label><label>Minimum score<input type="number" min="0" max="100" value={minimumScore} onChange={(e) => setMinimumScore(Number(e.target.value) || 0)} /></label><button type="button" disabled={busy} onClick={() => void load(1)}>{busy ? 'Refreshing…' : 'Apply exact rules'}</button></section>{error && <div className="recommendation-error">{error}</div>}<section className="recommendation-table-wrap"><table><thead><tr><th>#</th>{columns.map((column) => <th key={column.key} className={column.sortKey ? 'sortable' : ''} onClick={() => column.sortKey && sortBy(column.sortKey)}>{column.label}{column.sortKey && sort.field === column.sortKey ? (sort.direction === 'desc' ? ' ↓' : ' ↑') : ''}</th>)}<th>Action</th></tr></thead><tbody>{data.items.map((row, index) => <tr key={row.result_id}><td>{(data.page - 1) * 50 + index + 1}</td>{columns.map((column) => <td key={column.key}>{renderCell(row, column.key)}</td>)}<td><button className="recommendation-schedule" type="button" onClick={() => schedule(row)}>Schedule buy</button></td></tr>)}</tbody></table>{!busy && !data.items.length && <p className="recommendation-empty">No fresh signal matches these exact rules. Filters were not weakened.</p>}</section>{data.pages > 1 && <nav className="recommendation-pagination"><button disabled={data.page <= 1 || busy} onClick={() => void load(data.page - 1)}>Previous</button><span>Page {data.page} of {data.pages}</span><button disabled={data.page >= data.pages || busy} onClick={() => void load(data.page + 1)}>Next</button></nav>}<footer className="recommendation-footer"><span>Backtest performance is research, not a guarantee.</span><span>Scheduling preloads the exact versioned strategy; it never places an order automatically.</span></footer></div>;
};
export default Recommendations;
