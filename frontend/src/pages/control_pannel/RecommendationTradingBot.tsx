import React, { useEffect, useMemo, useState } from "react";
import { fetchJson } from "../../utils/api";
import "./RecommendationTradingBot.css";

type BotFilter = { field: string; operator: string; value: string };
type BotConfig = {
  lookback_days: number; initial_capital: number; minimum_win_rate: number;
  minimum_prior_trades: number; minimum_confidence: number; minimum_average_volume: number;
  minimum_prior_expectancy_pct: number; minimum_prior_profit_factor: number;
  recent_trade_window: number; minimum_recent_win_rate: number; minimum_recent_expectancy_pct: number;
  min_holding_days: number; max_holding_days: number; max_positions: number;
  max_stock_pct: number; max_sector_pct: number; cash_reserve_pct: number;
  max_volume_participation_pct: number; exit_strategy: "strategy_exit" | "hard_stop" | "trailing_stop" | "take_profit" | "protective_ensemble" | "auto_best";
  hard_stop_pct: number; trailing_stop_pct: number; take_profit_pct: number; slippage_pct: number;
  symbol_cooldown_days: number; ranking_mode: "risk_adjusted_expectancy" | "confidence";
  filters: BotFilter[]; start_date?: string; end_date?: string;
};
type Replay = {
  start_date: string; end_date: string; config: BotConfig; summary: Record<string, number>;
  equity_curve: Array<{ date: string; equity: number; cash: number; positions: number; drawdown_pct: number }>;
  benchmark?: { name: string; return_pct: number | null; curve: Array<{ date: string; value: number }>; disclaimer: string };
  exit_selection?: { requested: string; selected: string; comparison: Record<string, { net_return_pct: number; max_drawdown_pct: number; completed_trades: number }>; note: string };
  eligibility_audit?: {
    minimum_prior_win_rate_pct: number; minimum_prior_trades: number;
    minimum_prior_confidence_floor_pct: number; executed_minimum_prior_win_rate_pct: number | null;
    executed_minimum_prior_trades: number | null; executed_orders: number;
    all_executed_orders_passed: boolean; small_sample_orders: number; basis: string;
  };
  paper_candidate?: {
    training_end: string; validation_start: string; paper_ready: boolean; note: string;
    suggested_config: Pick<BotConfig, "minimum_win_rate" | "minimum_prior_trades" | "minimum_confidence" | "exit_strategy">;
    training: Record<string, number>; validation: Record<string, number>;
  } | null;
  short_term_analysis?: {
    note: string;
    winners: Record<string, {
      paper_ready: boolean; decision: "paper_candidate" | "stay_in_cash"; decision_reason: string;
      profile: Record<string, any>;
      training: Record<string, number>;
      validation: Record<string, number>;
    }>;
  } | null;
  multi_trade_analysis?: {
    training_end: string; validation_start: string; tested_configurations: number;
    paper_ready: boolean; decision: "paper_candidate" | "stay_in_cash";
    decision_reason: string; note: string;
    suggested_config: Pick<BotConfig, "max_positions" | "max_stock_pct" | "max_sector_pct" | "exit_strategy">;
    training: Record<string, number>; validation: Record<string, number>;
  } | null;
  deployment_gate?: {
    decision: "paper_candidate" | "stay_in_cash"; paper_ready: boolean;
    completed_trades: number; realized_win_rate_floor_pct: number; reasons: string[];
  };
  trades: Array<Record<string, any>>; candidate_signals: number;
  rejection_counts: Record<string, number>; methodology: string;
};
const DEFAULT_CONFIG: BotConfig = {
  lookback_days: 180, initial_capital: 100000, minimum_win_rate: 75,
  minimum_prior_trades: 25, minimum_confidence: 55, minimum_average_volume: 10000,
  minimum_prior_expectancy_pct: 3, minimum_prior_profit_factor: 1.7,
  recent_trade_window: 12, minimum_recent_win_rate: 60, minimum_recent_expectancy_pct: 1,
  min_holding_days: 5, max_holding_days: 45, max_positions: 1,
  max_stock_pct: 10, max_sector_pct: 40, cash_reserve_pct: 5,
  max_volume_participation_pct: 5, exit_strategy: "strategy_exit", hard_stop_pct: 7, trailing_stop_pct: 8, take_profit_pct: 15, slippage_pct: 0.1, symbol_cooldown_days: 20, ranking_mode: "risk_adjusted_expectancy", filters: [],
};
const money = (value: any) => `NPR ${Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
const pct = (value: any) => `${Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}%`;

const RecommendationTradingBot: React.FC = () => {
  const [config, setConfig] = useState<BotConfig>(DEFAULT_CONFIG);
  const [catalog, setCatalog] = useState<Array<{ field: string; type: string; label: string }>>([]);
  const [mode, setMode] = useState<"historical" | "paper" | "live">("historical");
  const [dateMode, setDateMode] = useState<"lookback" | "custom">("lookback");
  const [name, setName] = useState("Recommendation portfolio bot");
  const [clientId, setClientId] = useState("");
  const [replay, setReplay] = useState<Replay | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(() => {
    void fetchJson<{ filters: typeof catalog; default_config: BotConfig }>("/api/recommendation-trading-bots/catalog").then((response) => {
      if (!response.ok) return;
      setCatalog(response.data.filters);
      setConfig({ ...DEFAULT_CONFIG, ...response.data.default_config });
    });
  }, []);
  const updateNumber = (key: keyof BotConfig, value: string) => {
    setConfig((current) => ({ ...current, [key]: Number(value) }));
  };
  const runReplay = async (
    analyzeAccuracy = false, analyzeShortTerm = false, analyzePortfolio = false,
  ) => {
    setBusy(true); setMessage("");
    const requestConfig = analyzeShortTerm ? {
      ...config, lookback_days: 730, start_date: undefined, end_date: undefined,
      minimum_win_rate: 50, minimum_prior_trades: 9, minimum_confidence: 0,
      minimum_prior_expectancy_pct: -100, minimum_prior_profit_factor: 0,
      minimum_recent_win_rate: 0, minimum_recent_expectancy_pct: -100, minimum_average_volume: 0,
      exit_strategy: "auto_best" as const, analyze_short_term: true,
    } : analyzePortfolio ? {
      ...config, lookback_days: 730, start_date: undefined, end_date: undefined,
      exit_strategy: "auto_best" as const, analyze_portfolio: true,
    } : { ...config, analyze_accuracy: analyzeAccuracy };
    const response = await fetchJson<Replay>("/api/recommendation-trading-bots/backtest", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config: requestConfig }),
    }, 120000);
    setBusy(false);
    if (response.ok) setReplay(response.data);
    else setMessage(response.error || "Recommendation replay failed.");
  };
  const saveBot = async () => {
    setBusy(true); setMessage("");
    const response = await fetchJson<{ message: string }>("/api/recommendation-trading-bots", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, execution_mode: mode, client_id: clientId || null, config }),
    }, 120000);
    setBusy(false);
    setMessage(response.ok ? response.data.message : response.error || "Could not save this bot.");
  };
  const loadShortTermProfile = (profile: Record<string, any>, horizon: string) => {
    const keys: Array<keyof BotConfig> = [
      "minimum_win_rate", "minimum_prior_trades", "minimum_confidence",
      "minimum_prior_expectancy_pct", "minimum_prior_profit_factor",
      "min_holding_days", "max_holding_days", "hard_stop_pct",
      "trailing_stop_pct", "take_profit_pct", "exit_strategy", "symbol_cooldown_days",
    ];
    const settings = Object.fromEntries(keys.map((key) => [key, profile[key]])) as Partial<BotConfig>;
    setConfig((current) => ({ ...current, ...settings, max_positions: 1, ranking_mode: "risk_adjusted_expectancy" }));
    setMode("paper");
    setMessage(`${horizon}-day validated profile loaded. Review it before saving the paper draft.`);
  };
  const loadMultiTradeProfile = (settings: Replay["multi_trade_analysis"]) => {
    if (!settings) return;
    setConfig((current) => ({ ...current, ...settings.suggested_config }));
    setMode("paper");
    setMessage("Validated multi-trade settings loaded. Review them before saving the paper draft.");
  };
  const curves = useMemo(() => {
    if (!replay) return { bot: "", benchmark: "" };
    const start = new Date(replay.start_date).getTime(); const end = new Date(replay.end_date).getTime();
    const bot = replay.equity_curve.map((item) => ({ date: new Date(item.date).getTime(), value: item.equity / config.initial_capital * 100 }));
    const benchmark = (replay.benchmark?.curve || []).map((item) => ({ date: new Date(item.date).getTime(), value: item.value }));
    const values = [...bot, ...benchmark].map((item) => item.value);
    if (!values.length) return { bot: "", benchmark: "" };
    const low = Math.min(...values); const high = Math.max(...values);
    const line = (points: Array<{ date: number; value: number }>) => points.map((item) => {
      const x = 10 + (item.date - start) / Math.max(1, end - start) * 780;
      const y = 185 - (item.value - low) / Math.max(1, high - low) * 165;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ");
    return { bot: line(bot), benchmark: line(benchmark) };
  }, [replay, config.initial_capital]);
  return <main className="recommendation-bot">
    <section className="recommendation-bot-intro">
      <div><span>Causal portfolio simulator</span><h2>Recommendation Auto Trading Bot</h2><p>Use the same filters for a historical replay, paper draft, or locked live setup. Historical ranking sees only evidence available before each signal.</p></div>
      <div className="bot-mode-switch">
        {(["historical", "paper", "live"] as const).map((item) => <button type="button" key={item} className={mode === item ? "active" : ""} onClick={() => setMode(item)}>{item === "historical" ? "Past-period test" : item === "paper" ? "Paper bot" : "Live TMS bot"}</button>)}
      </div>
    </section>
    <section className="recommendation-bot-config">
      <div className="bot-config-heading"><div><h3>Capital and execution rules</h3><p>Cash is shared. Open positions lock their cost; the bot waits when cash is unavailable and reuses proceeds only after a sell.</p></div><strong>{money(config.initial_capital)}<small>starting equity</small></strong></div>
      <button type="button" className="bot-profit-preset" onClick={() => setConfig((current) => ({ ...current, minimum_win_rate: 75, minimum_prior_trades: 16, minimum_confidence: 50, minimum_prior_expectancy_pct: 2, minimum_prior_profit_factor: 1.5, recent_trade_window: 12, minimum_recent_win_rate: 60, minimum_recent_expectancy_pct: 1, minimum_average_volume: 10000, ranking_mode: "risk_adjusted_expectancy", symbol_cooldown_days: 20, max_positions: 1 }))}>Use strict profit-focused filters</button>
      <div className="bot-config-grid">
        <label>Test period<select value={dateMode === "custom" ? "custom" : config.lookback_days} onChange={(event) => { if (event.target.value === "custom") setDateMode("custom"); else { setDateMode("lookback"); updateNumber("lookback_days", event.target.value); setConfig((current) => ({ ...current, start_date: undefined, end_date: undefined })); } }}><option value="20">20 days</option><option value="30">30 days</option><option value="90">3 months</option><option value="180">6 months</option><option value="365">1 year</option><option value="730">2 years</option><option value="custom">Custom date range</option></select></label>
        {dateMode === "custom" && <><label>From date<input type="date" value={config.start_date || ""} onChange={(event) => setConfig((current) => ({ ...current, start_date: event.target.value }))} /></label><label>To date<input type="date" value={config.end_date || ""} onChange={(event) => setConfig((current) => ({ ...current, end_date: event.target.value }))} /></label></>}
        <label>Total capital<input type="number" min="1000" step="5000" value={config.initial_capital} onChange={(event) => updateNumber("initial_capital", event.target.value)} /></label>
        <label>Per stock<select value={config.max_stock_pct} onChange={(event) => updateNumber("max_stock_pct", event.target.value)}>{Array.from({ length: 20 }, (_, index) => (index + 1) * 5).map((value) => <option key={value} value={value}>{value}% of current equity</option>)}</select></label>
        <label>Maximum positions<input type="number" min="1" max="50" value={config.max_positions} onChange={(event) => updateNumber("max_positions", event.target.value)} /></label>
        <label>Cash reserve %<input type="number" min="0" max="95" step="5" value={config.cash_reserve_pct} onChange={(event) => updateNumber("cash_reserve_pct", event.target.value)} /></label>
        <label>Sector cap %<input type="number" min="5" max="100" step="5" value={config.max_sector_pct} onChange={(event) => updateNumber("max_sector_pct", event.target.value)} /></label>
        <label>Minimum prior strategy win rate %<input type="number" min="0" max="100" step="1" value={config.minimum_win_rate} onChange={(event) => updateNumber("minimum_win_rate", event.target.value)} /></label>
        <label>Prior completed trades required<input type="number" min="0" step="1" value={config.minimum_prior_trades} onChange={(event) => updateNumber("minimum_prior_trades", event.target.value)} /></label>
        <label>Minimum prior 95% floor %<input type="number" min="0" max="100" step="1" value={config.minimum_confidence} onChange={(event) => updateNumber("minimum_confidence", event.target.value)} /></label>
        <label>Minimum prior expectancy %<input type="number" min="-100" max="1000" step="0.25" value={config.minimum_prior_expectancy_pct} onChange={(event) => updateNumber("minimum_prior_expectancy_pct", event.target.value)} /></label>
        <label>Minimum prior profit factor<input type="number" min="0" max="100" step="0.1" value={config.minimum_prior_profit_factor} onChange={(event) => updateNumber("minimum_prior_profit_factor", event.target.value)} /></label>
        <label>Recent evidence window<input type="number" min="3" max="100" step="1" value={config.recent_trade_window} onChange={(event) => updateNumber("recent_trade_window", event.target.value)} /></label>
        <label>Minimum recent win rate %<input type="number" min="0" max="100" step="1" value={config.minimum_recent_win_rate} onChange={(event) => updateNumber("minimum_recent_win_rate", event.target.value)} /></label>
        <label>Minimum recent expectancy %<input type="number" min="-100" max="1000" step="0.25" value={config.minimum_recent_expectancy_pct} onChange={(event) => updateNumber("minimum_recent_expectancy_pct", event.target.value)} /></label>
        <label>20D average volume<input type="number" min="0" step="1000" value={config.minimum_average_volume} onChange={(event) => updateNumber("minimum_average_volume", event.target.value)} /></label>
        <label>Minimum hold<input type="number" min="0" value={config.min_holding_days} onChange={(event) => updateNumber("min_holding_days", event.target.value)} /></label>
        <label>Maximum hold<input type="number" min={config.min_holding_days || 1} value={config.max_holding_days} onChange={(event) => updateNumber("max_holding_days", event.target.value)} /></label>
        <label>Sell strategy<select value={config.exit_strategy} onChange={(event) => setConfig((current) => ({ ...current, exit_strategy: event.target.value as BotConfig["exit_strategy"] }))}><option value="auto_best">Auto-select best historical exit</option><option value="protective_ensemble">Protective ensemble (first valid exit)</option><option value="strategy_exit">Saved strategy sell signal</option><option value="hard_stop">Hard stop loss</option><option value="trailing_stop">Trailing stop loss</option><option value="take_profit">Profit target</option></select></label>
        <label>Hard stop loss %<input type="number" min="0.1" max="50" step="0.5" value={config.hard_stop_pct} onChange={(event) => updateNumber("hard_stop_pct", event.target.value)} /></label>
        <label>Trailing stop %<input type="number" min="0.1" max="50" step="0.5" value={config.trailing_stop_pct} onChange={(event) => updateNumber("trailing_stop_pct", event.target.value)} /></label>
        <label>Profit target %<input type="number" min="0.1" max="500" step="1" value={config.take_profit_pct} onChange={(event) => updateNumber("take_profit_pct", event.target.value)} /></label>
        <label>Sell slippage %<input type="number" min="0" max="10" step="0.05" value={config.slippage_pct} onChange={(event) => updateNumber("slippage_pct", event.target.value)} /></label>
        <label>Same-stock cooldown days<input type="number" min="0" max="365" step="1" value={config.symbol_cooldown_days} onChange={(event) => updateNumber("symbol_cooldown_days", event.target.value)} /></label>
        <label>Top-pick ranking<select value={config.ranking_mode} onChange={(event) => setConfig((current) => ({ ...current, ranking_mode: event.target.value as BotConfig["ranking_mode"] }))}><option value="risk_adjusted_expectancy">Risk-adjusted expectancy</option><option value="confidence">Confidence only</option></select></label>
      </div>
      <p className="bot-exit-note">All exits follow the minimum holding period. After that hold is complete, hard stop-loss has protection priority even when the saved strategy sell signal is selected. Stops and targets use completed-session high/low prices; strategy exits use the close.</p>
      <p className="bot-exit-note">Recent evidence uses only the latest completed exits available before each signal. It prevents older bull-market wins from masking a strategy that has recently deteriorated.</p>
      <p className="bot-exit-note">For an exact comparison with the saved backtest exit, select “Saved strategy sell signal.” Protective, trailing, hard-stop and target modes intentionally test different exits, so their realized win rate can differ.</p>
    </section>
    <section className="recommendation-bot-filters">
      <div><h3>Additional recommendation filters</h3><p>Add up to 12 stock, strategy, sector, evidence, price, volume or holding filters.</p></div>
      {config.filters.map((filter, index) => <div className="bot-filter-row" key={`${index}-${filter.field}`}>
        <select value={filter.field} onChange={(event) => setConfig((current) => ({ ...current, filters: current.filters.map((item, position) => position === index ? { ...item, field: event.target.value } : item) }))}>{catalog.map((item) => <option value={item.field} key={item.field}>{item.label}</option>)}</select>
        <select value={filter.operator} onChange={(event) => setConfig((current) => ({ ...current, filters: current.filters.map((item, position) => position === index ? { ...item, operator: event.target.value } : item) }))}><option value="gte">≥</option><option value="gt">&gt;</option><option value="lte">≤</option><option value="lt">&lt;</option><option value="eq">Equals</option><option value="neq">Not equal</option><option value="contains">Contains</option></select>
        <input value={filter.value} onChange={(event) => setConfig((current) => ({ ...current, filters: current.filters.map((item, position) => position === index ? { ...item, value: event.target.value } : item) }))} />
        <button type="button" onClick={() => setConfig((current) => ({ ...current, filters: current.filters.filter((_, position) => position !== index) }))}>Remove</button>
      </div>)}
      <button type="button" disabled={!catalog.length || config.filters.length >= 12} onClick={() => setConfig((current) => ({ ...current, filters: [...current.filters, { field: catalog[0]?.field || "symbol", operator: "contains", value: "" }] }))}>+ Add filter</button>
    </section>
    <section className="recommendation-bot-actions">
      <button type="button" className="primary" disabled={busy || (dateMode === "custom" && (!config.start_date || !config.end_date))} onClick={() => void runReplay()}>{busy ? "Running causal replay…" : dateMode === "custom" ? "Test custom range" : `Test past ${config.lookback_days} days`}</button>
      <button type="button" disabled={busy || (dateMode === "custom" && (!config.start_date || !config.end_date))} onClick={() => void runReplay(true)}>Analyze accuracy-first paper setup</button>
      <button type="button" disabled={busy} onClick={() => void runReplay(false, false, true)}>Optimize multi-trade portfolio</button>
      <button type="button" disabled={busy} onClick={() => void runReplay(false, true)}>Find best rolling 30/60-day profile</button>
      <label>Bot name<input value={name} onChange={(event) => setName(event.target.value)} /></label>
      {mode !== "historical" && <label>TMS client ID<input value={clientId} onChange={(event) => setClientId(event.target.value)} placeholder="Required" /></label>}
      <button type="button" disabled={busy || !name.trim() || (mode !== "historical" && !clientId.trim())} onClick={() => void saveBot()}>{mode === "historical" ? "Save test setup" : mode === "paper" ? "Create paper bot draft" : "Create locked live draft"}</button>
      {message && <p role="status">{message}</p>}
    </section>
    {replay && <section className="recommendation-bot-results">
      <div className="bot-result-heading"><div><span>{replay.start_date} → {replay.end_date}</span><h3>Shared-capital result after Nepal charges</h3><p>{replay.methodology}</p></div><strong className={Number(replay.summary.net_return_pct) >= 0 ? "positive" : "negative"}>{Number(replay.summary.net_return_pct) >= 0 ? "+" : ""}{pct(replay.summary.net_return_pct)}<small>net portfolio return</small></strong></div>
      <div className="bot-result-cards">
        <article><span>Final equity</span><b>{money(replay.summary.final_equity)}</b></article>
        <article><span>Realized P/L</span><b>{money(replay.summary.realized_pnl)}</b></article>
        <article><span>Trades / wins</span><b>{replay.summary.completed_trades} / {replay.summary.winning_trades}</b></article>
        <article><span>Win rate</span><b>{pct(replay.summary.win_rate_pct)}</b></article>
        <article><span>Total charges</span><b>{money(replay.summary.total_charges)}</b></article>
        <article><span>Gross P/L before costs</span><b>{money(replay.summary.gross_pnl_before_charges)}</b></article>
        <article><span>Capital turnover</span><b>{pct(replay.summary.capital_turnover_pct)}</b></article>
        <article><span>Return on deployed capital</span><b>{pct(replay.summary.return_on_deployed_capital_pct)}</b></article>
        <article><span>CGT</span><b>{money(replay.summary.taxes)}</b></article>
        <article><span>Max drawdown</span><b>{pct(replay.summary.max_drawdown_pct)}</b></article>
        <article><span>Orders executed</span><b>{replay.summary.accepted_signals}</b></article>
        <article><span>Filtered candidates</span><b>{replay.candidate_signals}</b></article>
        <article><span>NEPSE proxy move</span><b className={Number(replay.benchmark?.return_pct) >= 0 ? "positive" : "negative"}>{replay.benchmark?.return_pct == null ? "—" : `${Number(replay.benchmark.return_pct) >= 0 ? "+" : ""}${pct(replay.benchmark.return_pct)}`}</b></article>
      </div>
      {replay.deployment_gate && <section className={`bot-paper-candidate ${replay.deployment_gate.paper_ready ? "ready" : "caution"}`}><div><span>Risk decision</span><h4>{replay.deployment_gate.paper_ready ? "Eligible for a controlled paper test" : "Stay in cash for this configuration"}</h4><p>{replay.deployment_gate.reasons.join(" ")}</p></div><article><span>Realized evidence</span><b>{replay.deployment_gate.completed_trades} trades · 95% floor {pct(replay.deployment_gate.realized_win_rate_floor_pct)}</b></article></section>}
      {replay.eligibility_audit && <section className={`bot-eligibility-audit ${replay.eligibility_audit.all_executed_orders_passed ? "passed" : "failed"}`}><div><span>Eligibility filter audit</span><b>{replay.eligibility_audit.all_executed_orders_passed ? "Applied correctly" : "Filter mismatch detected"}</b></div><article><span>Required prior win rate</span><b>≥ {pct(replay.eligibility_audit.minimum_prior_win_rate_pct)}</b></article><article><span>Lowest among executed orders</span><b>{replay.eligibility_audit.executed_minimum_prior_win_rate_pct == null ? "—" : pct(replay.eligibility_audit.executed_minimum_prior_win_rate_pct)}</b></article><article><span>Subsequent realized bot win rate</span><b>{pct(replay.summary.win_rate_pct)}</b></article><p>{replay.eligibility_audit.basis}{replay.eligibility_audit.small_sample_orders > 0 ? ` ${replay.eligibility_audit.small_sample_orders} executed order(s) had fewer than 9 prior trades, so a 100% rate was still weak evidence; increase prior trades and the 95% floor for a stricter test.` : ""}</p></section>}
      <div className="bot-result-explainer"><b>Why this can lose despite good strategy records</b><span>The prior win rate measures each strategy’s earlier saved exits. The portfolio result measures only orders it could fund, using the selected sell rule, quantities, slippage, brokerage, SEBON, DP and CGT. Those are different measurements.</span></div>
      <div className="bot-equity-chart"><div><span className="bot-legend bot">Bot equity</span><span className="bot-legend benchmark">{replay.benchmark?.name || "NEPSE proxy"}</span></div><svg viewBox="0 0 800 200" role="img" aria-label="Recommendation bot and NEPSE market proxy chart"><polyline points={curves.bot} className="bot-line" /><polyline points={curves.benchmark} className="benchmark-line" /></svg></div>
      {replay.benchmark?.disclaimer && <p className="bot-benchmark-disclaimer">{replay.benchmark.disclaimer}</p>}
      {replay.exit_selection && <section className="bot-exit-comparison"><div><span>Selected sell rule</span><b>{replay.exit_selection.selected.replaceAll("_", " ")}</b></div>{Object.entries(replay.exit_selection.comparison).map(([rule, value]) => <article key={rule} className={rule === replay.exit_selection?.selected ? "selected" : ""}><b>{rule.replaceAll("_", " ")}</b><span>{value.completed_trades} trades · {value.net_return_pct >= 0 ? "+" : ""}{pct(value.net_return_pct)} · DD {pct(value.max_drawdown_pct)}</span></article>)}<p>{replay.exit_selection.note}</p></section>}
      {replay.paper_candidate && <section className={`bot-paper-candidate ${replay.paper_candidate.paper_ready ? "ready" : "caution"}`}><div><span>Walk-forward paper candidate</span><h4>{replay.paper_candidate.paper_ready ? "Passed the untouched validation period" : "Not reliable enough for future paper activation"}</h4><p>{replay.paper_candidate.note}</p></div><article><span>Training through {replay.paper_candidate.training_end}</span><b>{pct(replay.paper_candidate.training.win_rate_pct)} wins · {Number(replay.paper_candidate.training.net_return_pct) >= 0 ? "+" : ""}{pct(replay.paper_candidate.training.net_return_pct)}</b></article><article><span>Validation from {replay.paper_candidate.validation_start}</span><b>{pct(replay.paper_candidate.validation.win_rate_pct)} wins · {Number(replay.paper_candidate.validation.net_return_pct) >= 0 ? "+" : ""}{pct(replay.paper_candidate.validation.net_return_pct)}</b><small>{replay.paper_candidate.validation.completed_trades} completed trades · 95% floor {pct(replay.paper_candidate.validation.win_rate_floor_pct)}</small></article><button type="button" disabled={!replay.paper_candidate.paper_ready} onClick={() => { setConfig((current) => ({ ...current, ...replay.paper_candidate!.suggested_config })); setMode("paper"); setMessage("Validated settings loaded. Add the TMS client and save the paper draft after review."); }}>Use validated settings</button></section>}
      {replay.multi_trade_analysis && <section className={`bot-paper-candidate ${replay.multi_trade_analysis.paper_ready ? "ready" : "caution"}`}><div><span>Multi-trade portfolio optimizer</span><h4>{replay.multi_trade_analysis.paper_ready ? "Beat the market proxy in untouched validation" : "Best setup found, but keep it in research"}</h4><p>{replay.multi_trade_analysis.note} Tested {replay.multi_trade_analysis.tested_configurations} funded portfolio configurations.</p></div><article><span>Selected setup</span><b>{replay.multi_trade_analysis.suggested_config.max_positions} positions · {pct(replay.multi_trade_analysis.suggested_config.max_stock_pct)} per stock</b><small>{String(replay.multi_trade_analysis.suggested_config.exit_strategy).replaceAll("_", " ")} · sector cap {pct(replay.multi_trade_analysis.suggested_config.max_sector_pct)}</small></article><article><span>Training through {replay.multi_trade_analysis.training_end}</span><b>{Number(replay.multi_trade_analysis.training.net_return_pct) >= 0 ? "+" : ""}{pct(replay.multi_trade_analysis.training.net_return_pct)} bot · {Number(replay.multi_trade_analysis.training.excess_return_pct) >= 0 ? "+" : ""}{pct(replay.multi_trade_analysis.training.excess_return_pct)} vs proxy</b><small>{replay.multi_trade_analysis.training.completed_trades} completed trades · DD {pct(replay.multi_trade_analysis.training.max_drawdown_pct)}</small></article><article><span>Untouched validation from {replay.multi_trade_analysis.validation_start}</span><b>{Number(replay.multi_trade_analysis.validation.net_return_pct) >= 0 ? "+" : ""}{pct(replay.multi_trade_analysis.validation.net_return_pct)} bot · {Number(replay.multi_trade_analysis.validation.excess_return_pct) >= 0 ? "+" : ""}{pct(replay.multi_trade_analysis.validation.excess_return_pct)} vs proxy</b><small>{replay.multi_trade_analysis.validation.completed_trades} trades · {pct(replay.multi_trade_analysis.validation.win_rate_pct)} wins · DD {pct(replay.multi_trade_analysis.validation.max_drawdown_pct)}</small></article><p>{replay.multi_trade_analysis.decision_reason}</p><button type="button" disabled={!replay.multi_trade_analysis.paper_ready} onClick={() => loadMultiTradeProfile(replay.multi_trade_analysis)}>Use validated multi-trade settings</button></section>}
      {replay.short_term_analysis && <section className="bot-short-term-analysis"><div><span>Rolling short-term optimizer</span><h4>30/60-day locked-profile validation</h4><p>{replay.short_term_analysis.note}</p></div>{Object.entries(replay.short_term_analysis.winners).map(([horizon, winner]) => <article key={horizon} className={winner.paper_ready ? "ready" : "caution"}><span>{horizon}-day winner</span><b>{winner.profile.label}</b><em>{winner.decision === "stay_in_cash" ? "Decision: stay in cash" : "Decision: eligible for paper test"}</em><small>Training: {winner.training.profitable_windows}/{winner.training.windows} profitable windows · avg {pct(winner.training.average_net_return_pct)}</small><strong className={Number(winner.validation.net_return_pct) >= 0 ? "positive" : "negative"}>Latest untouched window: {Number(winner.validation.net_return_pct) >= 0 ? "+" : ""}{pct(winner.validation.net_return_pct)}</strong><small>{winner.validation.completed_trades} trades · DD {pct(winner.validation.max_drawdown_pct)}</small><small>{winner.decision_reason}</small><button type="button" disabled={!winner.paper_ready} onClick={() => loadShortTermProfile(winner.profile, horizon)}>Use {horizon}D validated profile</button></article>)}</section>}
      <div className="recommendation-table-wrap"><table><thead><tr><th>Stock</th><th>Strategy</th><th>Signal</th><th>Buy</th><th>Sell</th><th>Exit rule</th><th>Qty</th><th>Held</th><th>Strategy win rate</th><th>95% floor</th><th>Charges</th><th>Net result</th></tr></thead><tbody>{replay.trades.slice(0, 200).map((trade, index) => <tr key={`${trade.symbol}-${trade.entry_date}-${index}`}><td><b>{trade.symbol}</b></td><td>{trade.strategy}</td><td>{trade.signal_date}</td><td>{trade.entry_date} · {money(trade.entry_price)}</td><td>{trade.exit_date} · {money(trade.exit_price)}</td><td>{String(trade.exit_reason || "—").replaceAll("_", " ")}</td><td>{trade.quantity}</td><td>{trade.holding_days}d</td><td>{pct(trade.prior_win_rate_pct)} · {trade.prior_trades}</td><td>{pct(trade.confidence_floor_pct)}</td><td>{money(trade.total_charges)}</td><td className={Number(trade.net_return_pct) >= 0 ? "positive" : "negative"}>{Number(trade.net_return_pct) >= 0 ? "+" : ""}{pct(trade.net_return_pct)}<small>{money(trade.net_pnl)}</small></td></tr>)}</tbody></table></div>
    </section>}
    <p className="recommendation-bot-disclaimer">Historical and paper modes submit no broker order. A live draft remains locked until separate confirmation and final TMS account, balance, holdings, market-hours, liquidity and duplicate-order preflight.</p>
  </main>;
};

export default RecommendationTradingBot;
