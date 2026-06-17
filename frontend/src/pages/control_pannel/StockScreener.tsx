import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import './StockScreener.css';
import ErrorMessage from '../../components/ErrorMessage';
import CommonTable from '../../components/table/Table';
import { fetchJson, getApiUrl } from '../../utils/api';
import {
  buildPresetCopyText,
  SCREENER_PRESETS,
  SCREENER_QUERY_GUIDE,
  ScreenerPreset,
} from '../../lib/screener/presets';
import { buildChatGptScreenerPrompt, ScreenerQuerySpec } from '../../lib/screener/chatGptPrompt';

type FieldType = 'number' | 'text';

interface ScreenerField {
  key: string;
  label: string;
  category: string;
  type: FieldType;
  operators: string[];
}

interface FilterRow {
  id: string;
  field: string;
  operator: string;
  value: string;
  valueTo: string;
}

interface ScreenerResult {
  rank?: number;
  symbol: string;
  cached?: boolean;
  [key: string]: string | number | boolean | undefined;
}

interface ScreenerStats {
  requested: number;
  loaded: number;
  failed: number;
  cache_hits: number;
  matched: number;
  returned: number;
  cache_ttl_seconds: number;
}

const OPERATOR_LABELS: Record<string, string> = {
  gt: '>',
  gte: '≥',
  lt: '<',
  lte: '≤',
  eq: '=',
  neq: '≠',
  between: 'between',
  contains: 'contains',
  in: 'in',
};

const DEFAULT_FILTER: Omit<FilterRow, 'id'> = {
  field: 'alpha_annualized',
  operator: 'gte',
  value: '0',
  valueTo: '',
};

const makeFilterRow = (overrides?: Partial<Omit<FilterRow, 'id'>>): FilterRow => ({
  id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
  ...DEFAULT_FILTER,
  ...overrides,
});

const RESULT_COLUMNS = [
  'rank',
  'symbol',
  'alpha_annualized',
  'beta_3_month',
  'sharpe_ratio_annualized',
  'ltp',
  'one_year_yield',
  'fundamental_pe_ttm',
  'fundamental_roe_ttm',
  'technical_rsi_14',
  'technical_macd',
];

const DEFAULT_QUERY = SCREENER_PRESETS[0].query;

type InputMode = 'builder' | 'query' | 'ai';

interface AiChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  query?: string;
  isError?: boolean;
}

const NEPSE_ALPHA_CHART_URL = 'https://nepsealpha.com/trading/chart';

const parseApiError = (data: unknown, fallback: string): string => {
  if (!data || typeof data !== 'object') {
    return fallback;
  }
  const detail = (data as { detail?: unknown }).detail;
  if (typeof detail === 'string') {
    return detail;
  }
  if (detail && typeof detail === 'object' && 'message' in detail) {
    return String((detail as { message: unknown }).message);
  }
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (typeof item === 'string') {
          return item;
        }
        if (item && typeof item === 'object' && 'msg' in item) {
          return String((item as { msg: unknown }).msg);
        }
        return JSON.stringify(item);
      })
      .join(' ');
  }
  return fallback;
};

const StockScreener: React.FC = () => {
  const [fields, setFields] = useState<ScreenerField[]>([]);
  const [inputMode, setInputMode] = useState<InputMode>('builder');
  const [queryText, setQueryText] = useState(DEFAULT_QUERY);
  const [activePresetId, setActivePresetId] = useState<string | null>(null);
  const [copyMessage, setCopyMessage] = useState('');
  const [filters, setFilters] = useState<FilterRow[]>([makeFilterRow()]);
  const [clientId, setClientId] = useState('');
  const [clientIds, setClientIds] = useState<string[]>([]);
  const [rankBy, setRankBy] = useState('alpha_annualized');
  const [rankDirection, setRankDirection] = useState<'desc' | 'asc'>('desc');
  const [limit, setLimit] = useState('25');
  const [forceRefresh, setForceRefresh] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loadingLabel, setLoadingLabel] = useState('');
  const [error, setError] = useState('');
  const [results, setResults] = useState<ScreenerResult[]>([]);
  const [stats, setStats] = useState<ScreenerStats | null>(null);
  const [cacheTtl, setCacheTtl] = useState(300);
  const [querySpec, setQuerySpec] = useState<ScreenerQuerySpec | null>(null);
  const [presetGuideOpen, setPresetGuideOpen] = useState(false);
  const [hasRun, setHasRun] = useState(false);
  const [aiInput, setAiInput] = useState('');
  const [aiMessages, setAiMessages] = useState<AiChatMessage[]>([]);
  const [aiSummary, setAiSummary] = useState('');
  const [generatedQuery, setGeneratedQuery] = useState('');
  const resultsRef = useRef<HTMLElement | null>(null);

  const activePreset = useMemo(
    () => SCREENER_PRESETS.find((preset) => preset.id === activePresetId) || null,
    [activePresetId],
  );

  const chatGptPrompt = useMemo(() => buildChatGptScreenerPrompt(fields, querySpec), [fields, querySpec]);

  useEffect(() => {
    const loadFields = async () => {
      const response = await fetchJson<{
        fields: ScreenerField[];
        cache_ttl_seconds: number;
        query_spec?: ScreenerQuerySpec;
      }>('/stock_screener/fields');
      if (response.ok) {
        setFields(response.data.fields || []);
        setCacheTtl(response.data.cache_ttl_seconds || 300);
        setQuerySpec(response.data.query_spec || null);
      }
    };
    void loadFields();
  }, []);

  useEffect(() => {
    const loadClients = async () => {
      try {
        const response = await fetch(`${getApiUrl()}/logged_in_clients/`);
        if (!response.ok) {
          return;
        }
        const data = await response.json();
        const ids: string[] = data.logged_in_client_ids || [];
        setClientIds(ids);
        if (ids.length > 0) {
          setClientId(ids[0]);
        }
      } catch {
        // ignore
      }
    };
    void loadClients();
  }, []);

  const fieldsByKey = useMemo(() => {
    const map = new Map<string, ScreenerField>();
    fields.forEach((field) => map.set(field.key, field));
    return map;
  }, [fields]);

  const groupedFields = useMemo(() => {
    const groups = new Map<string, ScreenerField[]>();
    fields.forEach((field) => {
      const list = groups.get(field.category) || [];
      list.push(field);
      groups.set(field.category, list);
    });
    return groups;
  }, [fields]);

  const updateFilter = (id: string, patch: Partial<FilterRow>) => {
    setFilters((prev) => prev.map((row) => (row.id === id ? { ...row, ...patch } : row)));
  };

  const addFilter = () => {
    setFilters((prev) => [...prev, makeFilterRow({ field: fields[0]?.key || 'alpha_annualized' })]);
  };

  const removeFilter = (id: string) => {
    setFilters((prev) => (prev.length <= 1 ? prev : prev.filter((row) => row.id !== id)));
  };

  const buildFilterPayload = useCallback(() => {
    return filters
      .map((row) => {
        const fieldMeta = fieldsByKey.get(row.field);
        if (!fieldMeta) {
          return null;
        }
        if (fieldMeta.type === 'number' && row.operator === 'between') {
          const low = Number(row.value);
          const high = Number(row.valueTo);
          if (!Number.isFinite(low) || !Number.isFinite(high)) {
            return null;
          }
          return { field: row.field, operator: row.operator, value: [low, high] };
        }
        if (fieldMeta.type === 'number') {
          const numeric = Number(row.value);
          if (!Number.isFinite(numeric)) {
            return null;
          }
          return { field: row.field, operator: row.operator, value: numeric };
        }
        if (row.operator === 'in') {
          const options = row.value.split(',').map((item) => item.trim()).filter(Boolean);
          if (options.length === 0) {
            return null;
          }
          return { field: row.field, operator: row.operator, value: options };
        }
        if (!row.value.trim()) {
          return null;
        }
        return { field: row.field, operator: row.operator, value: row.value.trim() };
      })
      .filter(Boolean);
  }, [fieldsByKey, filters]);

  const copyText = async (text: string, label: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopyMessage(`${label} copied`);
      window.setTimeout(() => setCopyMessage(''), 2000);
    } catch {
      setCopyMessage('Copy failed — select text manually');
    }
  };

  const runAiScreener = async (messageOverride?: string) => {
    if (!clientId) {
      setError('Select a logged-in TMS client to scan the full symbol universe.');
      return;
    }

    const userMessage = (messageOverride ?? aiInput).trim();
    if (!userMessage) {
      setError('Describe what you want to screen for.');
      return;
    }

    const userMsg: AiChatMessage = {
      id: `${Date.now()}-user`,
      role: 'user',
      content: userMessage,
    };
    setAiMessages((prev) => [...prev, userMsg]);
    setAiInput('');
    setLoading(true);
    setLoadingLabel('AI is building query and screening stocks…');
    setError('');
    setResults([]);
    setStats(null);
    setAiSummary('');
    setGeneratedQuery('');
    setHasRun(false);

    let completedScreen = false;
    try {
      const controller = new AbortController();
      const timeoutId = window.setTimeout(() => controller.abort(), 300000);
      const response = await fetch(`${getApiUrl()}/stock_screener/ai_screen`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          client_id: clientId,
          message: userMessage,
          force_refresh: forceRefresh,
        }),
        signal: controller.signal,
      });
      window.clearTimeout(timeoutId);

      const data = await response.json();
      if (!response.ok) {
        const detail = data?.detail;
        const generated = detail && typeof detail === 'object' && 'generated_query' in detail
          ? String((detail as { generated_query?: string }).generated_query || '')
          : '';
        if (generated) {
          setGeneratedQuery(generated);
          setQueryText(generated);
        }
        throw new Error(parseApiError(data, 'AI screener request failed'));
      }

      const query = String(data.generated_query || '');
      const summary = String(data.ai_summary || 'Query generated and screened successfully.');
      setGeneratedQuery(query);
      setQueryText(query);
      setAiSummary(summary);
      if (data.parsed_query?.rank_by) {
        setRankBy(data.parsed_query.rank_by);
      }
      if (data.parsed_query?.rank_direction) {
        setRankDirection(data.parsed_query.rank_direction);
      }
      if (data.parsed_query?.limit) {
        setLimit(String(data.parsed_query.limit));
      }

      setAiMessages((prev) => [
        ...prev,
        {
          id: `${Date.now()}-assistant`,
          role: 'assistant',
          content: summary,
          query,
        },
      ]);
      setResults(data.results || []);
      setStats(data.stats || null);
      completedScreen = true;
      setHasRun(true);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'AI screener request failed';
      setError(message);
      setAiMessages((prev) => [
        ...prev,
        {
          id: `${Date.now()}-assistant-error`,
          role: 'assistant',
          content: message,
          isError: true,
        },
      ]);
      completedScreen = true;
      setHasRun(true);
    } finally {
      setLoading(false);
      setLoadingLabel('');
      if (completedScreen) {
        resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    }
  };

  const runScreener = async (options?: {
    queryOverride?: string;
    useBuilder?: boolean;
    fromPreset?: boolean;
    loadingMessage?: string;
  }) => {
    if (!clientId) {
      setError('Select a logged-in TMS client to scan the full symbol universe.');
      return;
    }

    const presetQuery = options?.queryOverride;
    const useQueryMode = Boolean(presetQuery) || (!options?.useBuilder && inputMode === 'query');
    const query = presetQuery ?? queryText;

    if (useQueryMode && !query.trim()) {
      setError('Enter a SQL-like screener query.');
      return;
    }

    setLoading(true);
    setLoadingLabel(options?.loadingMessage || (options?.fromPreset ? 'Screening stocks…' : 'Running screener…'));
    setError('');
    setResults([]);
    setStats(null);

    if (options?.fromPreset) {
      resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    let completedScreen = false;
    const payload = useQueryMode
      ? {
          client_id: clientId,
          query,
          force_refresh: forceRefresh,
        }
      : {
          client_id: clientId,
          filters: buildFilterPayload(),
          rank_by: rankBy,
          rank_direction: rankDirection,
          limit: Math.max(1, Math.min(500, Number(limit) || 25)),
          force_refresh: forceRefresh,
        };

    try {
      const controller = new AbortController();
      const timeoutId = window.setTimeout(() => controller.abort(), 180000);
      const response = await fetch(`${getApiUrl()}/stock_screener/screen`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });
      window.clearTimeout(timeoutId);

      const data = await response.json();
      if (!response.ok) {
        throw new Error(parseApiError(data, 'Stock screener request failed'));
      }

      if (data.parsed_query?.rank_by) {
        setRankBy(data.parsed_query.rank_by);
      }
      if (data.parsed_query?.rank_direction) {
        setRankDirection(data.parsed_query.rank_direction);
      }
      if (data.parsed_query?.limit) {
        setLimit(String(data.parsed_query.limit));
      }

      setResults(data.results || []);
      setStats(data.stats || null);
      completedScreen = true;
      setHasRun(true);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Stock screener request failed';
      setError(message);
      setHasRun(true);
      completedScreen = true;
    } finally {
      setLoading(false);
      setLoadingLabel('');
      if (completedScreen) {
        resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    }
  };

  const applyPreset = (preset: ScreenerPreset) => {
    setActivePresetId(preset.id);
    setPresetGuideOpen(false);
    setQueryText(preset.query);
    void runScreener({
      queryOverride: preset.query,
      fromPreset: true,
      loadingMessage: `Screening: ${preset.title}…`,
    });
  };

  const handleQueryChange = (value: string) => {
    setQueryText(value);
    setActivePresetId(null);
    setPresetGuideOpen(false);
  };

  const displayColumns = useMemo(() => {
    const extras = rankBy && !RESULT_COLUMNS.includes(rankBy) ? [rankBy] : [];
    const merged = [...RESULT_COLUMNS, ...extras];
    return merged.filter((column, index) => merged.indexOf(column) === index);
  }, [rankBy]);

  const symbolColumnLinks = useMemo(
    () => ({
      symbol: (row: Record<string, unknown>) => {
        const sym = String(row.symbol || '').trim().toUpperCase();
        return sym ? `${NEPSE_ALPHA_CHART_URL}?symbol=${encodeURIComponent(sym)}` : undefined;
      },
    }),
    [],
  );

  return (
    <div className="stock-screener-page">
      <section className="stock-screener-hero card">
        <div>
          <h2 className="stock-screener-title">Stock Screener</h2>
          <p className="stock-screener-subtitle">
            Pick a quick screen for top 25 stocks, or write your own SQL-like query.
            Nepse Alpha data is cached for {Math.round(cacheTtl / 60)} minutes per symbol.
          </p>
        </div>
        <div className="stock-screener-status">
          {stats ? (
            <>
              <span>Scanned {stats.requested}</span>
              <span>Loaded {stats.loaded}</span>
              <span>Matched {stats.matched}</span>
              <span>Cache hits {stats.cache_hits}</span>
            </>
          ) : (
            <span>Ready</span>
          )}
        </div>
      </section>

      <section className="stock-screener-controls card">
        <div className="stock-screener-row">
          <label htmlFor="screener-client">TMS Client (symbol universe)</label>
          <select
            id="screener-client"
            className="input"
            value={clientId}
            onChange={(e) => setClientId(e.target.value)}
          >
            <option value="">Select client</option>
            {clientIds.map((id) => (
              <option key={id} value={id}>{id}</option>
            ))}
          </select>
        </div>

        <div className="stock-screener-presets">
          <div className="stock-screener-presets-header">
            <h3>Quick Screens (Top 25)</h3>
            <span className="stock-screener-presets-note">Click a shortcut to run instantly</span>
          </div>
          <div className="stock-screener-preset-grid">
            {SCREENER_PRESETS.map((preset) => (
              <button
                key={preset.id}
                type="button"
                className={`stock-screener-preset-card${activePresetId === preset.id ? ' active' : ''}`}
                disabled={loading}
                onClick={() => applyPreset(preset)}
              >
                <span className="stock-screener-preset-title">{preset.title}</span>
                <span className="stock-screener-preset-subtitle">{preset.subtitle}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="stock-screener-mode-tabs">
          <button
            type="button"
            className={inputMode === 'builder' ? 'active' : ''}
            onClick={() => setInputMode('builder')}
          >
            Filter Builder
          </button>
          <button
            type="button"
            className={inputMode === 'query' ? 'active' : ''}
            onClick={() => setInputMode('query')}
          >
            SQL-like Query
          </button>
          <button
            type="button"
            className={inputMode === 'ai' ? 'active' : ''}
            onClick={() => setInputMode('ai')}
          >
            Talk to AI
          </button>
        </div>

        {inputMode === 'ai' ? (
          <div className="stock-screener-ai-chat-panel">
            <p className="stock-screener-ai-chat-desc">
              Describe your screen in plain English. Nemotron builds a strict query on the server
              (validated against live field keys), runs it, and shows results below.
            </p>
            {aiMessages.length > 0 && (
              <div className="stock-screener-ai-chat-log" aria-live="polite">
                {aiMessages.map((message) => (
                  <div
                    key={message.id}
                    className={`stock-screener-ai-chat-message ${message.role}${message.isError ? ' error' : ''}`}
                  >
                    <span className="stock-screener-ai-chat-role">
                      {message.role === 'user' ? 'You' : 'AI'}
                    </span>
                    <p className="stock-screener-ai-chat-text">{message.content}</p>
                    {message.query && (
                      <pre className="stock-screener-ai-chat-query">{message.query}</pre>
                    )}
                  </div>
                ))}
              </div>
            )}
            <label htmlFor="screener-ai-input">What do you want to screen?</label>
            <textarea
              id="screener-ai-input"
              className="stock-screener-query-input"
              rows={4}
              value={aiInput}
              onChange={(e) => setAiInput(e.target.value)}
              placeholder="e.g. Show top 25 stocks with RSI between 30 and 45, PE under 30, and bullish MACD, ranked by alpha"
              onKeyDown={(e) => {
                if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                  e.preventDefault();
                  void runAiScreener();
                }
              }}
            />
            <p className="stock-screener-query-help">
              Press <kbd>Ctrl</kbd>+<kbd>Enter</kbd> or use the button below. Only columns from the live Nepse Alpha API are allowed.
            </p>
            <label className="stock-screener-checkbox">
              <input type="checkbox" checked={forceRefresh} onChange={(e) => setForceRefresh(e.target.checked)} />
              Bypass cache
            </label>
          </div>
        ) : inputMode === 'query' ? (
          <>
            <div className="stock-screener-ai-prompt-panel">
              <div className="stock-screener-prompt-header">
                <div>
                  <h4>ChatGPT / AI assistant prompt</h4>
                  <p className="stock-screener-ai-prompt-desc">
                    Copy this into ChatGPT (or any AI). It embeds the live field catalog from
                    <code> /stock_screener/fields</code> — every column key, label, type, operator, and alias.
                    The AI must return <code>STATUS: ERROR</code> if you ask for a column that is not in the API.
                  </p>
                </div>
                <div className="stock-screener-prompt-actions">
                  <button
                    type="button"
                    className="btn-primary"
                    onClick={() => void copyText(chatGptPrompt, 'ChatGPT prompt')}
                  >
                    Copy prompt for ChatGPT
                  </button>
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => void copyText(SCREENER_QUERY_GUIDE, 'Syntax guide')}
                  >
                    Copy short syntax only
                  </button>
                </div>
              </div>
              {copyMessage && !activePreset && <p className="stock-screener-copy-msg">{copyMessage}</p>}
              <details className="stock-screener-ai-prompt-details">
                <summary>Preview full AI prompt ({fields.length} fields documented)</summary>
                <pre className="stock-screener-prompt-body stock-screener-ai-prompt-preview">{chatGptPrompt}</pre>
              </details>
            </div>

            {activePreset && presetGuideOpen && (
              <div className="stock-screener-prompt-panel">
                <div className="stock-screener-prompt-header">
                  <h4>{activePreset.title} — query guide</h4>
                  <div className="stock-screener-prompt-actions">
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={() => void copyText(buildPresetCopyText(activePreset), 'Full guide')}
                    >
                      Copy guide + query
                    </button>
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={() => void copyText(activePreset.query, 'Query')}
                    >
                      Copy query only
                    </button>
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={() => void copyText(SCREENER_QUERY_GUIDE, 'Syntax guide')}
                    >
                      Copy syntax help
                    </button>
                  </div>
                </div>
                {copyMessage && <p className="stock-screener-copy-msg">{copyMessage}</p>}
                <pre className="stock-screener-prompt-body">{activePreset.prompt}</pre>
                <div className="stock-screener-prompt-query">
                  <span className="stock-screener-prompt-query-label">Query used</span>
                  <pre>{activePreset.query}</pre>
                </div>
              </div>
            )}
          <div className="stock-screener-query-panel">
            <label htmlFor="screener-query">Manual query (edit shortcut or write your own)</label>
            {activePreset && !presetGuideOpen && (
              <button
                type="button"
                className="btn-secondary stock-screener-view-query-btn"
                onClick={() => setPresetGuideOpen(true)}
              >
                View query guide for {activePreset.title}
              </button>
            )}
            <textarea
              id="screener-query"
              className="stock-screener-query-input"
              rows={8}
              spellCheck={false}
              value={queryText}
              onChange={(e) => handleQueryChange(e.target.value)}
              placeholder="WHERE field >= value AND ..."
            />
            <p className="stock-screener-query-help">
              Use field keys like <code>technical_rsi_14</code>, <code>fundamental_pe_ttm</code>, <code>alpha_annualized</code>.
              Supports <code>WHERE</code>, <code>AND</code>, <code>BETWEEN</code>, <code>IN (...)</code>, <code>ORDER BY</code>, <code>LIMIT</code>.
            </p>
            <label className="stock-screener-checkbox">
              <input type="checkbox" checked={forceRefresh} onChange={(e) => setForceRefresh(e.target.checked)} />
              Bypass cache
            </label>
          </div>
          </>
        ) : (
          <>
            <div className="stock-screener-filters-header">
              <h3>Dynamic Filters</h3>
              <button type="button" className="btn-secondary" onClick={addFilter}>+ Add Filter</button>
            </div>

            <div className="stock-screener-filters">
              {filters.map((row) => {
                const fieldMeta = fieldsByKey.get(row.field);
                const operators = fieldMeta?.operators || ['gte'];
                const isBetween = fieldMeta?.type === 'number' && row.operator === 'between';
                return (
                  <div key={row.id} className="stock-screener-filter-row">
                    <select
                      className="input"
                      value={row.field}
                      onChange={(e) => updateFilter(row.id, { field: e.target.value })}
                    >
                      {Array.from(groupedFields.entries()).map(([category, items]) => (
                        <optgroup key={category} label={category}>
                          {items.map((field) => (
                            <option key={field.key} value={field.key}>{field.label}</option>
                          ))}
                        </optgroup>
                      ))}
                    </select>
                    <select
                      className="input stock-screener-operator"
                      value={row.operator}
                      onChange={(e) => updateFilter(row.id, { operator: e.target.value })}
                    >
                      {operators.map((operator) => (
                        <option key={operator} value={operator}>{OPERATOR_LABELS[operator] || operator}</option>
                      ))}
                    </select>
                    <input
                      className="input"
                      type={fieldMeta?.type === 'number' ? 'number' : 'text'}
                      value={row.value}
                      placeholder={row.operator === 'in' ? 'Bullish, Bearish' : 'Value'}
                      onChange={(e) => updateFilter(row.id, { value: e.target.value })}
                    />
                    {isBetween && (
                      <input
                        className="input"
                        type="number"
                        value={row.valueTo}
                        placeholder="Max"
                        onChange={(e) => updateFilter(row.id, { valueTo: e.target.value })}
                      />
                    )}
                    <button type="button" className="btn-icon" onClick={() => removeFilter(row.id)} aria-label="Remove filter">×</button>
                  </div>
                );
              })}
            </div>

            <div className="stock-screener-row stock-screener-rank-row">
              <div>
                <label htmlFor="rank-by">Rank by</label>
                <select id="rank-by" className="input" value={rankBy} onChange={(e) => setRankBy(e.target.value)}>
                  {fields.map((field) => (
                    <option key={field.key} value={field.key}>{field.label}</option>
                  ))}
                </select>
              </div>
              <div>
                <label htmlFor="rank-direction">Direction</label>
                <select
                  id="rank-direction"
                  className="input"
                  value={rankDirection}
                  onChange={(e) => setRankDirection(e.target.value as 'desc' | 'asc')}
                >
                  <option value="desc">Highest first</option>
                  <option value="asc">Lowest first</option>
                </select>
              </div>
              <div>
                <label htmlFor="result-limit">Top results</label>
                <input
                  id="result-limit"
                  className="input"
                  type="number"
                  min="1"
                  max="500"
                  value={limit}
                  onChange={(e) => setLimit(e.target.value)}
                />
              </div>
              <label className="stock-screener-checkbox">
                <input type="checkbox" checked={forceRefresh} onChange={(e) => setForceRefresh(e.target.checked)} />
                Bypass cache
              </label>
            </div>
          </>
        )}

        <div className="stock-screener-actions">
          <button
            type="button"
            className="btn-primary"
            disabled={loading}
            onClick={() => {
              if (inputMode === 'ai') {
                void runAiScreener();
                return;
              }
              void runScreener();
            }}
          >
            {loading
              ? 'Screening…'
              : inputMode === 'ai'
                ? 'Ask AI & Screen'
                : inputMode === 'query'
                  ? 'Run Query'
                  : 'Run Screener'}
          </button>
        </div>

        {error && !hasRun && <ErrorMessage message={error} variant="error" persistent />}

        {(loading || hasRun) && (
          <section ref={resultsRef} className="stock-screener-results stock-screener-results-below-run">
            <h3>
              Top Ranked Results
              {activePreset ? ` — ${activePreset.title}` : ''}
            </h3>
            {inputMode === 'ai' && generatedQuery && (
              <div className="stock-screener-generated-query">
                <span className="stock-screener-prompt-query-label">AI-generated query (strictly validated)</span>
                {aiSummary && <p className="stock-screener-ai-summary">{aiSummary}</p>}
                <pre>{generatedQuery}</pre>
              </div>
            )}
            {loading ? (
              <div className="stock-screener-loading" role="status" aria-live="polite">
                <div className="stock-screener-progress-track">
                  <div className="stock-screener-progress-bar" />
                </div>
                <p>{loadingLabel || 'Screening stocks with Nepse Alpha…'}</p>
              </div>
            ) : error && hasRun ? (
              <div className="stock-screener-result-message">
                <ErrorMessage message={error} variant="error" persistent />
              </div>
            ) : results.length === 0 ? (
              <div className="stock-screener-result-message" role="status">
                <p className="stock-screener-no-records">No records found</p>
                <p className="stock-screener-empty-meta">
                  {stats
                    ? `Scanned ${stats.requested} symbols · ${stats.loaded} loaded · ${stats.matched} matched your filters`
                    : 'No stocks matched your filters. Try relaxing conditions or pick another quick screen.'}
                </p>
              </div>
            ) : (
              <CommonTable data={results} columns={displayColumns} columnLinks={symbolColumnLinks} />
            )}
          </section>
        )}
      </section>
    </div>
  );
};

export default StockScreener;
