import React, { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { fetchJson } from "../../utils/api";
import NepseAlphaSymbolLink from "../../components/NepseAlphaSymbolLink";
import "./Recommendations.css";

type Row = Record<string, any>;
type Page = {
  items: Row[];
  total: number;
  page: number;
  pages: number;
  persisted: boolean;
  trading_session?: string;
};
type AiAnswer = {
  generated_query: string;
  explanation: string;
  recommendation_summary: string;
  total_matches: number;
  items: Row[];
  suggested_relaxations: string[];
};
const recommendationPrompts = [
  "Show the top 10 fresh buy signals with at least 10 trades, win rate above 55%, and controlled drawdown.",
  "Find liquid strong-buy stocks with positive out-of-sample return and robust score above 60.",
  "Show low-risk recommendations ranked by robust score with drawdown below 25%.",
];
const RECOMMENDATION_COLUMN_WIDTHS_KEY = "tms-recommendation-column-widths-v1";
const RECOMMENDATION_VISIBLE_COLUMNS_KEY = "tms-recommendation-visible-columns-v1";
const DEFAULT_VISIBLE_COLUMNS: Record<"buy" | "sell", string[]> = {
  buy: ["symbol", "current_signal_status", "recommendation_score", "current_ltp", "buy_range", "sell_range", "current_ltp_estimated_profit_pct", "current_ltp_estimated_loss_pct", "preset_name", "win_rate_pct", "total_trades", "average_holding_days"],
  sell: ["symbol", "current_signal_status", "recommendation_score", "ltp", "holding_quantity", "preset_name", "win_rate_pct", "total_trades", "net_return_pct", "average_holding_days"],
};
const DEFAULT_COLUMN_WIDTHS: Record<string, number> = {
  symbol: 120,
  current_signal_status: 125,
  preset_name: 190,
  recommendation_score: 120,
  win_rate_pct: 105,
  total_trades: 85,
  net_return_pct: 110,
  current_ltp: 115,
  current_ltp_position: 135,
  buy_range: 150,
  protective_stop: 120,
  sell_range: 150,
  estimated_profit_pct: 105,
  estimated_loss_pct: 100,
  current_ltp_estimated_profit_pct: 105,
  current_ltp_estimated_loss_pct: 95,
  average_holding_days: 100,
  average_volume_20: 125,
  signal_date: 120,
  holding_quantity: 120,
  ltp: 110,
  action: 130,
};
const money = (value: any) =>
  value == null
    ? "—"
    : `NPR ${Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
const number = (value: any) =>
  value == null
    ? "—"
    : Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 });

const Recommendations: React.FC = () => {
  const navigate = useNavigate();
  const preferenceUserId = localStorage.getItem("userId") || "local";
  const [data, setData] = useState<Page>({
    items: [],
    total: 0,
    page: 1,
    pages: 0,
    persisted: true,
  });
  const [recommendationSide, setRecommendationSide] = useState<"buy" | "sell">(
    "buy",
  );
  const [signal, setSignal] = useState("actionable");
  const [search, setSearch] = useState("");
  const [minimumWin, setMinimumWin] = useState("");
  const [minimumTrades, setMinimumTrades] = useState("5");
  const [minimumScore, setMinimumScore] = useState("");
  const [appliedRules, setAppliedRules] = useState({
    signal: "actionable",
    search: "",
    minimumWin: 0,
    minimumTrades: 5,
    minimumScore: 0,
  });
  const [sort, setSort] = useState({
    field: "recommendation_score",
    direction: "desc",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [scheduleBusyResultId, setScheduleBusyResultId] = useState<number | null>(null);
  const [scheduleMessage, setScheduleMessage] = useState("");
  const [aiQuestion, setAiQuestion] = useState(recommendationPrompts[0]);
  const [aiBusy, setAiBusy] = useState(false);
  const [aiAnswer, setAiAnswer] = useState<AiAnswer | null>(null);
  const [refreshBusy, setRefreshBusy] = useState(false);
  const [refreshMessage, setRefreshMessage] = useState("");
  const [tableHelpOpen, setTableHelpOpen] = useState(false);
  const [selectedStockDetail, setSelectedStockDetail] = useState<Row | null>(null);
  const [visibleColumns, setVisibleColumns] = useState<Record<"buy" | "sell", string[]>>(() => {
    const read = (side: "buy" | "sell") => {
      try {
        const saved = JSON.parse(localStorage.getItem(`${RECOMMENDATION_VISIBLE_COLUMNS_KEY}:${preferenceUserId}:${side}`) || "[]");
        return Array.isArray(saved) && saved.length ? saved.map(String) : DEFAULT_VISIBLE_COLUMNS[side];
      } catch {
        return DEFAULT_VISIBLE_COLUMNS[side];
      }
    };
    return { buy: read("buy"), sell: read("sell") };
  });
  useEffect(() => {
    localStorage.setItem(`${RECOMMENDATION_VISIBLE_COLUMNS_KEY}:${preferenceUserId}:${recommendationSide}`, JSON.stringify(visibleColumns[recommendationSide]));
  }, [preferenceUserId, recommendationSide, visibleColumns]);
  useEffect(() => {
    if (!tableHelpOpen && !selectedStockDetail) return undefined;
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") { setTableHelpOpen(false); setSelectedStockDetail(null); } };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [tableHelpOpen, selectedStockDetail]);
  const [columnWidths, setColumnWidths] = useState<Record<string, number>>(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(`${RECOMMENDATION_COLUMN_WIDTHS_KEY}:${preferenceUserId}`) || "{}") as Record<string, unknown>;
      return Object.fromEntries(
        Object.entries(saved).filter(([, value]) => Number.isFinite(Number(value))),
      ) as Record<string, number>;
    } catch {
      return {};
    }
  });
  useEffect(() => {
    localStorage.setItem(`${RECOMMENDATION_COLUMN_WIDTHS_KEY}:${preferenceUserId}`, JSON.stringify(columnWidths));
  }, [columnWidths, preferenceUserId]);
  const columnWidth = (key: string) => columnWidths[key] || DEFAULT_COLUMN_WIDTHS[key] || 110;
  const startColumnResize = (event: React.PointerEvent<HTMLSpanElement>, key: string) => {
    event.preventDefault();
    event.stopPropagation();
    const startX = event.clientX;
    const startWidth = columnWidth(key);
    document.body.classList.add("recommendation-column-resizing");
    const move = (moveEvent: PointerEvent) => {
      const nextWidth = Math.max(72, Math.min(520, startWidth + moveEvent.clientX - startX));
      setColumnWidths((current) => ({ ...current, [key]: nextWidth }));
    };
    const stop = () => {
      document.body.classList.remove("recommendation-column-resizing");
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop, { once: true });
  };
  const load = useCallback(
    async (page = 1) => {
      setBusy(true);
      setError("");
      const endpoint =
        recommendationSide === "sell"
          ? "/api/market-recommendations/sells/query"
          : "/api/market-recommendations/query";
      const response = await fetchJson<Page>(
        endpoint,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            signal: appliedRules.signal,
            search: appliedRules.search,
            minimum_win_rate: appliedRules.minimumWin,
            minimum_trades: appliedRules.minimumTrades,
            minimum_score: appliedRules.minimumScore,
            sort_by: sort.field,
            sort_direction: sort.direction,
            page,
            page_size: 50,
          }),
        },
        recommendationSide === "sell" ? 120000 : 30000,
      );
      setBusy(false);
      if (response.ok) setData(response.data);
      else setError(response.error || "Could not load recommendations.");
    },
    [appliedRules, recommendationSide, sort],
  );
  useEffect(() => {
    void load(1);
  }, [load]);
  const refreshRecommendations = async () => {
    setRefreshBusy(true);
    setRefreshMessage("Refreshing from cached strategies and the latest market data…");
    const response = await fetchJson<{ materialized: number }>("/api/market-recommendations/refresh", { method: "POST" }, 120000);
    if (response.ok) {
      await load(1);
      setRefreshMessage(`Refreshed ${response.data.materialized.toLocaleString()} stock recommendations.`);
    } else {
      setRefreshMessage(response.error || "Recommendation refresh failed.");
    }
    setRefreshBusy(false);
  };
  const applyRules = () => {
    const win = minimumWin.trim() === "" ? 0 : Number(minimumWin);
    const trades = minimumTrades.trim() === "" ? 0 : Number(minimumTrades);
    const score = minimumScore.trim() === "" ? 0 : Number(minimumScore);
    if (!Number.isFinite(win) || win < 0 || win > 100) {
      setError("Minimum win rate must be blank or between 0 and 100.");
      return;
    }
    if (!Number.isInteger(trades) || trades < 0) {
      setError("Minimum trades must be blank or a whole number of 0 or more.");
      return;
    }
    if (!Number.isFinite(score) || score < 0 || score > 100) {
      setError("Minimum score must be blank or between 0 and 100.");
      return;
    }
    setError("");
    setAppliedRules({
      signal,
      search: search.trim(),
      minimumWin: win,
      minimumTrades: trades,
      minimumScore: score,
    });
  };
  const sortBy = (field: string) =>
    setSort((current) => ({
      field,
      direction:
        current.field === field && current.direction === "desc"
          ? "asc"
          : current.field === field
            ? "desc"
            : ["symbol", "preset_name", "current_ltp_estimated_loss_pct", "average_holding_days"].includes(field)
              ? "asc"
              : "desc",
    }));
  const askAi = async (prompt = aiQuestion) => {
    const message = prompt.trim();
    if (!message) return;
    setAiQuestion(message);
    setAiBusy(true);
    setAiAnswer(null);
    setError("");
    const response = await fetchJson<AiAnswer>(
      "/api/backtests/v2/runs/all/ai-query",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, include_non_equities: false }),
      },
      120000,
    );
    setAiBusy(false);
    if (response.ok) setAiAnswer(response.data);
    else setError(response.error || "AI recommendation search failed.");
  };
  const openSchedule = async (row: Row) => {
    const side = recommendationSide;
    const resultId = Number(row.result_id);
    if (!resultId) {
      setScheduleMessage("This recommendation is missing its source backtest result.");
      return;
    }
    setScheduleBusyResultId(resultId);
    setScheduleMessage(`Resolving and validating the exact ${side.toUpperCase()} strategy…`);
    const response = await fetchJson<{
      valid: boolean;
      query_text: string;
      compiled_plan: Record<string, unknown>;
      paired_sell_query_text?: string | null;
      paired_sell_compiled_plan?: Record<string, unknown> | null;
      live_charge_policy?: Record<string, unknown>;
      source_backtest_result_id: number;
      source_backtest_run_id: string;
    }>(`/api/backtests/v2/results/${resultId}/strategy-query?side=${side}`);
    if (!response.ok) {
      setScheduleBusyResultId(null);
      setScheduleMessage(response.error || "The saved strategy could not be validated for scheduling.");
      return;
    }
    if (!response.data.valid || !String(response.data.query_text || "").trim()) {
      setScheduleBusyResultId(null);
      setScheduleMessage("The saved strategy could not be validated for scheduling.");
      return;
    }
    const symbol = String(row.symbol || "").trim().toUpperCase();
    const strategy = `Custom Query ${side === "buy" ? "Buy" : "Sell"}`;
    let scheduleDraft: Record<string, unknown> = {};
    let strategyDraft: Record<string, unknown> = {};
    try { scheduleDraft = JSON.parse(localStorage.getItem("tms-schedule-order-draft-v1") || "{}"); } catch { scheduleDraft = {}; }
    try { strategyDraft = JSON.parse(localStorage.getItem("tms-strategy-form-draft-v1:schedule-order") || "{}"); } catch { strategyDraft = {}; }
    const quantity = side === "sell" ? String(row.holding_quantity || "") : String(scheduleDraft.qty || "10");
    localStorage.setItem("tms-schedule-order-draft-v1", JSON.stringify({
      ...scheduleDraft,
      scriptName: symbol,
      selectedScriptSymbol: symbol,
      price: String(row.buy_zone_low || row.ltp || ""),
      qty: quantity,
      orderType: side,
      selectedStrategy: strategy,
      sourceBacktestResultId: response.data.source_backtest_result_id,
      sourceBacktestRunId: response.data.source_backtest_run_id,
    }));
    localStorage.setItem("tms-strategy-form-draft-v1:schedule-order", JSON.stringify({
      ...strategyDraft,
      strategy,
      ruleQueryText: response.data.query_text,
      qty: quantity,
      price: "",
      stopLossPrice: row.protective_stop == null ? "" : String(row.protective_stop),
      profitTargetPrice: row.sell_zone_low == null ? "" : String(row.sell_zone_low),
    }));
    localStorage.setItem("tms-strategy-source-v1:schedule-order", JSON.stringify({
      query_text: response.data.query_text,
      compiled_plan: response.data.compiled_plan,
      paired_sell_query_text: response.data.paired_sell_query_text,
      paired_sell_compiled_plan: response.data.paired_sell_compiled_plan,
      live_charge_policy: response.data.live_charge_policy,
      source_backtest_result_id: response.data.source_backtest_result_id,
      source_backtest_run_id: response.data.source_backtest_run_id,
      symbol,
      side,
    }));
    setScheduleBusyResultId(null);
    setScheduleMessage("Strategy validated. Opening Schedule Order for final confirmation…");
    navigate(`/dashboard/schedule-order?side=${side}&symbol=${encodeURIComponent(symbol)}&source=backtest-recommendation`);
  };
  const columns: Array<{ key: string; label: string; sortKey?: string }> = [
    { key: "symbol", label: "Stock", sortKey: "symbol" },
    { key: "current_signal_status", label: "Signal", sortKey: "signal_status" },
    {
      key: "recommendation_score",
      label: "Best pick score",
      sortKey: "recommendation_score",
    },
    { key: "current_ltp", label: "Current LTP", sortKey: "current_ltp" },
    { key: "buy_range", label: "Buy range", sortKey: "buy_range" },
    { key: "sell_range", label: "Sell range", sortKey: "sell_range" },
    { key: "current_ltp_estimated_profit_pct", label: "LTP upside", sortKey: "current_ltp_estimated_profit_pct" },
    { key: "current_ltp_estimated_loss_pct", label: "LTP risk", sortKey: "current_ltp_estimated_loss_pct" },
    { key: "preset_name", label: "Strategy", sortKey: "preset_name" },
    { key: "win_rate_pct", label: "Win rate", sortKey: "win_rate_pct" },
    { key: "total_trades", label: "Trades", sortKey: "total_trades" },
    { key: "net_return_pct", label: "Net return", sortKey: "net_return_pct" },
    { key: "current_ltp_position", label: "LTP vs buy range" },
    { key: "protective_stop", label: "Protective stop", sortKey: "protective_stop" },
    { key: "estimated_profit_pct", label: "Est. profit", sortKey: "estimated_profit_pct" },
    { key: "estimated_loss_pct", label: "Est. loss", sortKey: "estimated_loss_pct" },
    { key: "average_holding_days", label: "Avg hold", sortKey: "average_holding_days" },
    {
      key: "average_volume_20",
      label: "20D avg volume",
      sortKey: "average_volume_20",
    },
    { key: "signal_date", label: "Trading session", sortKey: "signal_date" },
  ];
  const availableColumns =
    recommendationSide === "buy"
      ? columns
      : [
          { key: "symbol", label: "Stock", sortKey: "symbol" },
          { key: "current_signal_status", label: "Signal", sortKey: "signal_status" },
          {
            key: "recommendation_score",
            label: "Robust score",
            sortKey: "recommendation_score",
          },
          { key: "ltp", label: "Latest close", sortKey: "ltp" },
          { key: "holding_quantity", label: "Combined holding", sortKey: "holding_quantity" },
          { key: "preset_name", label: "Tested exit strategy", sortKey: "preset_name" },
          {
            key: "win_rate_pct",
            label: "Historical win rate",
            sortKey: "win_rate_pct",
          },
          { key: "total_trades", label: "Trades", sortKey: "total_trades" },
          {
            key: "net_return_pct",
            label: "Backtest return",
            sortKey: "net_return_pct",
          },
          { key: "average_holding_days", label: "Avg hold", sortKey: "average_holding_days" },
          { key: "signal_date", label: "Signal session", sortKey: "signal_date" },
        ];
  const activeColumns = availableColumns.filter((column) => (
    column.key === "symbol" || visibleColumns[recommendationSide].includes(column.key)
  ));
  const toggleColumn = (key: string) => {
    if (key === "symbol") return;
    setVisibleColumns((current) => {
      const selected = new Set(current[recommendationSide]);
      if (selected.has(key)) selected.delete(key); else selected.add(key);
      return { ...current, [recommendationSide]: Array.from(selected) };
    });
  };
  const renderCell = (row: Row, key: string) => {
    if (key === "symbol")
      return (
        <div className="recommendation-symbol">
          <button
            type="button"
            onClick={() =>
              setSelectedStockDetail(row)
            }
          >
            {row.symbol}
          </button>
          <NepseAlphaSymbolLink symbol={row.symbol}>
            NEPSE Alpha ↗
          </NepseAlphaSymbolLink>
        </div>
      );
    if (key === "current_signal_status")
      return (
        <span className={`recommendation-signal ${row[key]}`}>
          {String(row[key] || "—").replaceAll("_", " ")}
        </span>
      );
    if (key === "preset_name") return String(row[key] || "—");
    if (key === "signal_date") return String(row[key] || "—");
    if (key === "current_ltp") return money(row[key]);
    if (key === "current_ltp_position") {
      const labels: Record<string, string> = { inside_buy_range: "Inside buy range", below_buy_range: "Below buy range", above_buy_range: "Above buy range", unavailable: "Unavailable" };
      return <span className={`recommendation-ltp-position ${row[key] || "unavailable"}`}>{labels[String(row[key])] || "Unavailable"}</span>;
    }
    if (key === "buy_range" || key === "sell_range") {
      const low = key === "buy_range" ? row.buy_zone_low : row.sell_zone_low;
      const high = key === "buy_range" ? row.buy_zone_high : row.sell_zone_high;
      if (low == null || high == null) return "—";
      return <span className={key === "buy_range" ? "recommendation-range buy" : "recommendation-range sell"}>NPR {number(low)}–{number(high)}</span>;
    }
    if (key === "estimated_profit_pct")
      return row[key] == null ? "—" : <span className="recommendation-estimate profit">+{number(row[key])}%</span>;
    if (key === "estimated_loss_pct")
      return row[key] == null ? "—" : <span className="recommendation-estimate loss">-{number(row[key])}%</span>;
    if (key === "current_ltp_estimated_profit_pct")
      return row[key] == null ? "—" : <span className={Number(row[key]) >= 0 ? "recommendation-estimate profit" : "recommendation-estimate loss"}>{Number(row[key]) >= 0 ? "+" : ""}{number(row[key])}%</span>;
    if (key === "current_ltp_estimated_loss_pct")
      return row[key] == null ? "—" : <span className="recommendation-estimate loss">-{number(row[key])}%</span>;
    if (key.includes("zone") || key === "protective_stop")
      return money(row[key]);
    if (
      key.includes("rate") ||
      key.includes("return") ||
      key === "recommendation_score"
    )
      return `${number(row[key])}%`;
    if (key === "average_holding_days") return `${number(row[key])} days`;
    return number(row[key]);
  };
  return (
    <div className="recommendation-page">
      <header className="recommendation-hero">
        <div>
          <span>Fresh decision workspace</span>
          <h1>Market Recommendations</h1>
          <p>
            Persisted signals combining current Market Analysis indicators with
            verified backtest performance.
          </p>
        </div>
        <div>
          <b>{data.total}</b>
          <small>
            {recommendationSide === "buy"
              ? "ordinary shares"
              : "eligible combined holdings"} · session {data.trading_session || "pending"}
          </small>
          <button type="button" className="recommendation-manual-refresh" disabled={refreshBusy} onClick={() => void refreshRecommendations()}>{refreshBusy ? "Refreshing…" : "Refresh recommendations"}</button>
          <small>Automatic NPT refresh: 10:00 · 12:30 · 15:00 · 16:00 on configured trading days</small>
          {refreshMessage && <small role="status">{refreshMessage}</small>}
        </div>
      </header>
      <nav className="recommendation-side-tabs" aria-label="Recommendation side">
        <button type="button" className={recommendationSide === "buy" ? "active buy" : ""} onClick={() => setRecommendationSide("buy")}>
          <b>Buy recommendations</b><span>Fresh entry signals across ordinary shares</span>
        </button>
        <button type="button" className={recommendationSide === "sell" ? "active sell" : ""} onClick={() => setRecommendationSide("sell")}>
          <b>Sell recommendations</b><span>Tested exit signals from combined holdings</span>
        </button>
      </nav>
      <section className="recommendation-controls">
        {recommendationSide === "buy" && <label>
          Signal
          <select value={signal} onChange={(e) => setSignal(e.target.value)}>
            <option value="actionable">Strong Buy + Buy today</option>
            <option value="strong_buy">Strong Buy only</option>
            <option value="buy">Buy only</option>
            <option value="near_trigger">Near trigger</option>
            <option value="all">All recommendation states</option>
          </select>
        </label>}
        <label>
          Stock or strategy
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="NABIL or momentum"
          />
        </label>
        <label>
          Minimum win %
          <input
            type="number"
            min="0"
            max="100"
            value={minimumWin}
            placeholder="Any"
            onChange={(e) => setMinimumWin(e.target.value)}
          />
        </label>
        <label>
          Minimum trades
          <input
            type="number"
            min="0"
            step="1"
            value={minimumTrades}
            placeholder="Any"
            onChange={(e) => setMinimumTrades(e.target.value)}
          />
        </label>
        <label>
          Minimum score
          <input
            type="number"
            min="0"
            max="100"
            value={minimumScore}
            placeholder="Any"
            onChange={(e) => setMinimumScore(e.target.value)}
          />
        </label>
        <button type="button" disabled={busy} onClick={applyRules}>
          {busy ? "Applying filters…" : "Apply exact rules"}
        </button>
      </section>
      {busy && (
        <div className="recommendation-loading" role="status">
          <i />
          Updating the fresh recommendation ranking…
        </div>
      )}
      {error && <div className="recommendation-error">{error}</div>}
      <section className="recommendation-ai">
        <div>
          <span>Ask AI</span>
          <h2>Search all cached backtests</h2>
          <p>
            Choose a common question or write your own. Exact conditions are
            validated and older market sessions are not substituted.
          </p>
        </div>
        <div className="recommendation-ai-presets">
          {recommendationPrompts.map((prompt, index) => (
            <button
              type="button"
              disabled={aiBusy}
              key={prompt}
              onClick={() => void askAi(prompt)}
            >
              <b>{index + 1}</b>
              {prompt}
            </button>
          ))}
        </div>
        <div className="recommendation-ai-query">
          <input
            value={aiQuestion}
            onChange={(event) => setAiQuestion(event.target.value)}
            placeholder="Ask for the best stocks, strategies, trades, risk or volume…"
            onKeyDown={(event) => {
              if (event.key === "Enter") void askAi();
            }}
          />
          <button
            type="button"
            disabled={aiBusy || !aiQuestion.trim()}
            onClick={() => void askAi()}
          >
            {aiBusy ? "Analyzing all results…" : "Ask AI"}
          </button>
        </div>
        {aiBusy && (
          <div className="recommendation-ai-progress">
            <i />
            Validating your query and ranking the top 10…
          </div>
        )}
        {aiAnswer && (
          <div className="recommendation-ai-answer">
            <code>{aiAnswer.generated_query}</code>
            <p>{aiAnswer.explanation}</p>
            <strong>{aiAnswer.recommendation_summary}</strong>
            {aiAnswer.total_matches === 0 ? (
              <p>
                No exact matches. {aiAnswer.suggested_relaxations.join(" ")}
              </p>
            ) : (
              <div className="recommendation-ai-results">
                {aiAnswer.items.map((row) => (
                  <button
                    type="button"
                    key={row.result_id}
                    onClick={() =>
                      navigate(
                        `/dashboard/backtest?run=${row.run_id}&stock=${row.symbol}&result=${row.result_id}`,
                      )
                    }
                  >
                    <b>{row.symbol}</b>
                    <span>{row.preset_name}</span>
                    <small>
                      {number(row.robust_score)} robust ·{" "}
                      {number(row.win_rate_pct)}% wins ·{" "}
                      {number(row.total_trades)} trades
                    </small>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </section>
      <section className="recommendation-table-tools">
        <div>
          <strong>Trader view</strong>
          <span>Risk-adjusted best picks first · {activeColumns.length} columns visible</span>
        </div>
        <div className="recommendation-table-tool-actions">
          <button type="button" onClick={() => setTableHelpOpen(true)}>How this table works</button>
          <details className="recommendation-column-picker">
            <summary>Columns <b>{activeColumns.length}/{availableColumns.length}</b></summary>
            <div>
              <header>
                <span>Add or remove columns</span>
                <button type="button" onClick={() => setVisibleColumns((current) => ({ ...current, [recommendationSide]: DEFAULT_VISIBLE_COLUMNS[recommendationSide] }))}>Trader default</button>
                <button type="button" onClick={() => setVisibleColumns((current) => ({ ...current, [recommendationSide]: availableColumns.map((column) => column.key) }))}>Show all</button>
              </header>
              {availableColumns.map((column) => (
                <label key={column.key}>
                  <input
                    type="checkbox"
                    checked={column.key === "symbol" || visibleColumns[recommendationSide].includes(column.key)}
                    disabled={column.key === "symbol"}
                    onChange={() => toggleColumn(column.key)}
                  />
                  <span>{column.label}</span>
                </label>
              ))}
            </div>
          </details>
        </div>
      </section>
      <section className="recommendation-table-wrap">
        <table style={{ width: activeColumns.reduce((sum, column) => sum + columnWidth(column.key), columnWidth("action")) }}>
          <colgroup>
            {activeColumns.map((column) => (
              <col key={column.key} style={{ width: columnWidth(column.key) }} />
            ))}
            <col style={{ width: columnWidth("action") }} />
          </colgroup>
          <thead>
            <tr>
              {activeColumns.map((column) => (
                <th
                  key={column.key}
                  className={column.sortKey ? "sortable" : ""}
                  title={column.sortKey ? `Sort by ${column.label} · drag the right edge to resize` : `Drag the right edge to resize ${column.label}`}
                  onClick={() => column.sortKey && sortBy(column.sortKey)}
                >
                  {column.label}
                  {column.sortKey && sort.field === column.sortKey
                    ? sort.direction === "desc"
                      ? " ↓"
                      : " ↑"
                    : ""}
                  <span
                    className="recommendation-column-resizer"
                    role="separator"
                    aria-orientation="vertical"
                    aria-label={`Resize ${column.label} column`}
                    title="Drag to resize · double-click to reset"
                    onClick={(event) => event.stopPropagation()}
                    onDoubleClick={(event) => {
                      event.stopPropagation();
                      setColumnWidths((current) => {
                        const next = { ...current };
                        delete next[column.key];
                        return next;
                      });
                    }}
                    onPointerDown={(event) => startColumnResize(event, column.key)}
                  />
                </th>
              ))}
              <th>
                Action
                <span
                  className="recommendation-column-resizer"
                  role="separator"
                  aria-orientation="vertical"
                  aria-label="Resize Action column"
                  title="Drag to resize · double-click to reset"
                  onDoubleClick={() => setColumnWidths((current) => {
                    const next = { ...current };
                    delete next.action;
                    return next;
                  })}
                  onPointerDown={(event) => startColumnResize(event, "action")}
                />
              </th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((row) => (
              <tr key={row.result_id}>
                {activeColumns.map((column) => (
                  <td
                    key={column.key}
                  className={column.key === "preset_name" ? "recommendation-strategy-cell" : ""}
                    title={column.key === "preset_name" ? String(row[column.key] || "") : undefined}
                  >
                    {renderCell(row, column.key)}
                  </td>
                ))}
                <td>
                  <button
                    className="recommendation-schedule"
                    type="button"
                    disabled={scheduleBusyResultId !== null}
                    onClick={() => void openSchedule(row)}
                  >
                    {scheduleBusyResultId === Number(row.result_id) ? "Validating strategy…" : `Schedule ${recommendationSide}`}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!busy && !data.items.length && (
          <p className="recommendation-empty">
            No fresh signal matches these exact rules. Filters were not
            weakened.
          </p>
        )}
      </section>
      {scheduleMessage && <div className="recommendation-schedule-message" role="status">{scheduleMessage}</div>}
      {selectedStockDetail && (
        <div className="recommendation-detail-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setSelectedStockDetail(null); }}>
          <aside role="dialog" aria-modal="true" aria-labelledby="recommendation-stock-detail-title">
            <header>
              <div><span>Recommendation detail</span><h2 id="recommendation-stock-detail-title">{selectedStockDetail.symbol}</h2><p>{selectedStockDetail.preset_name}</p></div>
              <button type="button" aria-label="Close stock detail" onClick={() => setSelectedStockDetail(null)}>×</button>
            </header>
            <div className="recommendation-detail-body">
              <section className="recommendation-detail-signal"><b>{String(selectedStockDetail.current_signal_status || "historical").replaceAll("_", " ")}</b><span>Signal session {selectedStockDetail.signal_date || "—"}</span></section>
              <dl>
                <div><dt>Best pick score</dt><dd>{number(selectedStockDetail.recommendation_score)}%</dd></div>
                <div><dt>Current LTP</dt><dd>{money(selectedStockDetail.current_ltp ?? selectedStockDetail.ltp)}</dd></div>
                <div><dt>Buy range</dt><dd>{money(selectedStockDetail.buy_zone_low)} – {money(selectedStockDetail.buy_zone_high)}</dd></div>
                <div><dt>Sell range</dt><dd>{money(selectedStockDetail.sell_zone_low)} – {money(selectedStockDetail.sell_zone_high)}</dd></div>
                <div><dt>Protective stop</dt><dd className="loss">{money(selectedStockDetail.protective_stop)}</dd></div>
                <div><dt>LTP upside</dt><dd className="profit">+{number(selectedStockDetail.current_ltp_estimated_profit_pct)}%</dd></div>
                <div><dt>Win rate</dt><dd>{number(selectedStockDetail.win_rate_pct)}%</dd></div>
                <div><dt>Completed trades</dt><dd>{number(selectedStockDetail.total_trades)}</dd></div>
                <div><dt>Average hold</dt><dd>{number(selectedStockDetail.average_holding_days)} days</dd></div>
              </dl>
              <article><h3>Lifecycle execution</h3><p>Scheduling this BUY transfers its tested entry plus a linked SELL monitor. The SELL remains dormant until the BUY executes, the stock appears in sellable holdings, and the minimum holding sessions are complete.</p></article>
            </div>
            <footer>
              <NepseAlphaSymbolLink symbol={selectedStockDetail.symbol}>Open NEPSE Alpha ↗</NepseAlphaSymbolLink>
              <button type="button" onClick={() => navigate(`/dashboard/backtest?run=${selectedStockDetail.run_id}&stock=${selectedStockDetail.symbol}&result=${selectedStockDetail.result_id}`)}>Open full backtest</button>
              <button type="button" className="primary" onClick={() => void openSchedule(selectedStockDetail)}>Schedule {recommendationSide}</button>
            </footer>
          </aside>
        </div>
      )}
      {tableHelpOpen && (
        <div className="recommendation-help-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setTableHelpOpen(false); }}>
          <section role="dialog" aria-modal="true" aria-labelledby="recommendation-table-help-title">
            <header>
              <div><span>Decision guide</span><h2 id="recommendation-table-help-title">How the recommendation table works</h2></div>
              <button type="button" aria-label="Close table guide" onClick={() => setTableHelpOpen(false)}>×</button>
            </header>
            <div className="recommendation-help-content">
              <article><h3>Default ranking: best risk-adjusted pick</h3><p>The Buy table starts with the highest Best Pick Score. It combines robust out-of-sample quality (35%), net return (20%), Sharpe ratio (15%), drawdown protection (20%), and profit factor (10%). A high raw return cannot rank first when its drawdown and consistency are poor.</p></article>
              <article><h3>Reading strategy names such as 8/21/60</h3><p><b>8</b> means an 8% stop-loss below entry, <b>21</b> means a 21% take-profit target above entry, and <b>60</b> means a maximum holding period of 60 trading sessions. At NPR 1,000, that is approximately NPR 920 stop and NPR 1,210 target, with a forced exit after 60 sessions if no earlier valid exit occurs.</p></article>
              <article><h3>Price and risk columns</h3><p>Current LTP is the latest available market price. Buy Range is the planned entry area; Sell Range is the tested target area. LTP Upside and LTP Risk estimate reward and downside from the current LTP. Protective Stop is the risk boundary, not a guaranteed execution price during a market gap.</p></article>
              <article><h3>Evidence columns</h3><p>Win Rate is winning trades divided by all completed trades. Trades shows sample size. Net Return includes the configured Nepal brokerage, SEBON fee, DP charge, CGT and slippage assumptions. Average Hold shows the historical time spent in each completed position.</p></article>
              <article><h3>Fresh signals and scheduling</h3><p>Buy and Strong Buy rows must match the latest confirmed trading session. Schedule Buy validates and transfers the exact versioned strategy into Schedule Order. It does not place an order until you review the account, quantity, live data and confirm.</p></article>
              <article><h3>Customize your view</h3><p>Use Columns to add or remove metrics and drag a header edge to resize it. Both visible columns and widths are saved separately for your signed-in user. Double-click a header edge to reset that width.</p></article>
            </div>
            <footer><button type="button" onClick={() => setTableHelpOpen(false)}>Close</button></footer>
          </section>
        </div>
      )}
      {data.pages > 1 && (
        <nav className="recommendation-pagination">
          <button
            disabled={data.page <= 1 || busy}
            onClick={() => void load(data.page - 1)}
          >
            Previous
          </button>
          <span>
            Page {data.page} of {data.pages}
          </span>
          <button
            disabled={data.page >= data.pages || busy}
            onClick={() => void load(data.page + 1)}
          >
            Next
          </button>
        </nav>
      )}
      <footer className="recommendation-footer">
        <span>Backtest performance is research, not a guarantee.</span>
        <span>
          Scheduling preloads the exact versioned strategy; it never places an
          order automatically.
        </span>
      </footer>
    </div>
  );
};
export default Recommendations;
