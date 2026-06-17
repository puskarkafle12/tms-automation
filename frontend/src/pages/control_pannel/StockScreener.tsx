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
import { buildChatGptScreenerPrompt } from '../../lib/screener/chatGptPrompt';

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

type InputMode = 'builder' | 'query';

const NEPSE_ALPHA_CHART_URL = 'https://nepsealpha.com/trading/chart';

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
  const [presetGuideOpen, setPresetGuideOpen] = useState(false);
  const resultsRef = useRef<HTMLElement | null>(null);

  const activePreset = useMemo(
    () => SCREENER_PRESETS.find((preset) => preset.id === activePresetId) || null,
    [activePresetId],
  );

  const chatGptPrompt = useMemo(() => buildChatGptScreenerPrompt(fields), [fields]);

  useEffect(() => {
    const loadFields = async () => {
      const response = await fetchJson<{ fields: ScreenerField[]; cache_ttl_seconds: number }>('/stock_screener/fields');
      if (response.ok) {
        setFields(response.data.fields || []);
        setCacheTtl(response.data.cache_ttl_seconds || 300);
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
        throw new Error(typeof data.detail === 'string' ? data.detail : 'Stock screener request failed');
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
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Stock screener request failed';
      setError(message);
    } finally {
      setLoading(false);
      setLoadingLabel('');
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

        <section ref={resultsRef} className="stock-screener-results stock-screener-results-inline">
          <h3>
            Top Ranked Results
            {activePreset ? ` — ${activePreset.title}` : ''}
          </h3>
          {loading ? (
            <div className="stock-screener-loading" role="status" aria-live="polite">
              <div className="stock-screener-progress-track">
                <div className="stock-screener-progress-bar" />
              </div>
              <p>{loadingLabel || 'Screening stocks with Nepse Alpha…'}</p>
            </div>
          ) : results.length === 0 ? (
            <p className="stock-screener-empty">Pick a quick screen or run a custom query to see ranked stocks.</p>
          ) : (
            <CommonTable data={results} columns={displayColumns} columnLinks={symbolColumnLinks} />
          )}
        </section>

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
        </div>

        {inputMode === 'query' ? (
          <>
            <div className="stock-screener-ai-prompt-panel">
              <div className="stock-screener-prompt-header">
                <div>
                  <h4>ChatGPT / AI assistant prompt</h4>
                  <p className="stock-screener-ai-prompt-desc">
                    Copy this into ChatGPT (or any AI). It lists every filterable stock field,
                    operators, syntax rules, and examples so the AI can write a valid screener query for you.
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
            onClick={() => void runScreener()}
          >
            {loading ? 'Screening…' : inputMode === 'query' ? 'Run Query' : 'Run Screener'}
          </button>
        </div>

        {error && <ErrorMessage message={error} />}
      </section>
    </div>
  );
};

export default StockScreener;
