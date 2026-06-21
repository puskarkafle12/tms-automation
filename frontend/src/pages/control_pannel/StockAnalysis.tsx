import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import './StockAnalysis.css';
import ErrorMessage from '../../components/ErrorMessage';
import CommonTable from '../../components/table/Table';
import Dropdown from '../../components/Dropdown';
import { fetchJson, getApiUrl } from '../../utils/api';
import {
  buildPresetCopyText,
  SCREENER_PRESETS,
  SCREENER_QUERY_GUIDE,
  ScreenerPreset,
} from '../../lib/screener/presets';
import {
  buildChatGptScreenerPrompt,
  buildChatGptScreenerPromptForCopy,
  ScreenerQuerySpec,
} from '../../lib/screener/chatGptPrompt';
import { buildNepseAlphaChartUrl } from '../../lib/nepseAlpha';
import ScreenerDropConfirmModal from '../../components/ScreenerDropConfirmModal';
import { ScreenerDropScheduleInput } from '../../api/screenerDrop.api';
import { addNepalDays, apiTimestampToUtcMs, currentNepalDateTimeLocal, todayNepalDate } from '../../utils/nepalTime';
import { formatRelativeTime, formatShortRelativeTime } from '../../utils/relativeTime';

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
  'ltp',
  'percent_change',
  'qty',
  'alpha_annualized',
  'beta_3_month',
  'sharpe_ratio_annualized',
  'pe_ratio',
  'one_year_yield',
  'fundamental_roe_ttm',
  'technical_rsi_14',
  'technical_macd',
];

interface MarketDataResponse {
  rows?: Record<string, unknown>[];
  columns?: string[];
  column_labels?: Record<string, string>;
}

const parsePercentChange = (value: unknown): number | null => {
  if (value == null || value === '') {
    return null;
  }
  const parsed = Number(String(value).replace(/[^\d.-]/g, ''));
  return Number.isFinite(parsed) ? parsed : null;
};

const rowColorForPercentChange = (percentChange: number | null) => {
  if (percentChange == null) {
    return undefined;
  }
  if (percentChange > 0) {
    return 'lightgreen';
  }
  if (percentChange < 0) {
    return 'red';
  }
  return 'lightyellow';
};

const isEmptyCell = (value: unknown): boolean => {
  if (value == null || value === '') {
    return true;
  }
  if (typeof value === 'number') {
    return false;
  }
  const text = String(value).trim();
  return !text || text === '-' || text === '--' || text === '—';
};

const METADATA_COLUMNS = new Set(['updated_at', 'fetched_at']);

const reorderColumnsByData = (
  columns: string[],
  rows: Record<string, unknown>[],
): string[] => {
  const populated: string[] = [];
  const empty: string[] = [];
  for (const column of columns) {
    if (rows.some((row) => !isEmptyCell(row[column]))) {
      populated.push(column);
    } else {
      empty.push(column);
    }
  }
  const ordered = [...populated, ...empty];
  const metadata = ordered.filter((column) => METADATA_COLUMNS.has(column));
  const body = ordered.filter((column) => !METADATA_COLUMNS.has(column));
  return [...body, ...metadata];
};

const formatMarketTableRows = (rows: Record<string, unknown>[], now = Date.now()) =>
  rows.map((row, index) => {
    const percentChange = parsePercentChange(row.percent_change ?? row.ml_percent_change);
    const ltpValue = row.ltp ?? row.ml_ltp;
    const qtyValue = row.qty ?? row.ml_quantity;
    const ltpSort = typeof ltpValue === 'number' ? ltpValue : Number(String(ltpValue ?? '').replace(/[^\d.-]/g, '')) || '';
    const qtySort = typeof qtyValue === 'number' ? qtyValue : Number(String(qtyValue ?? '').replace(/[^\d.-]/g, '')) || '';
    const updatedAtRaw = row.updated_at;
    const updatedAtMs = apiTimestampToUtcMs(updatedAtRaw as string | null);
    const updatedAtLabel = formatShortRelativeTime(updatedAtRaw as string | null, now)
      || formatRelativeTime(updatedAtRaw as string | null, now)
      || '-';
    return {
      ...row,
      percent_change:
        percentChange == null ? (
          '-'
        ) : (
          <span className={percentChange >= 0 ? 'positive' : 'negative'}>
            {percentChange >= 0 ? '+' : ''}
            {percentChange}%
          </span>
        ),
      updated_at: updatedAtLabel,
      color: rowColorForPercentChange(percentChange),
      sortValues: {
        percent_change: percentChange ?? '',
        ltp: ltpSort,
        qty: qtySort,
        updated_at: updatedAtMs ?? '',
      },
      rowKey: `${String(row.symbol || '')}-${index}`,
    };
  });

const DEFAULT_QUERY = SCREENER_PRESETS[0].query;

type InputMode = 'builder' | 'query' | 'ai';

type ScreenerUniverse = 'nepse' | 'combined_holdings' | 'client_holdings';

interface ClientSession {
  client_id: string;
  display_name?: string | null;
  broker_no: string;
}

interface AiChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  query?: string;
  isError?: boolean;
}

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

const readJsonResponse = async (
  response: Response,
): Promise<{ data: unknown; rawText: string }> => {
  const rawText = await response.text();
  if (!rawText.trim()) {
    return { data: {}, rawText };
  }
  try {
    return { data: JSON.parse(rawText) as unknown, rawText };
  } catch {
    return { data: null, rawText };
  }
};

const formatNonJsonResponse = (rawText: string, fallback: string): string => {
  if (rawText.startsWith('Traceback')) {
    return 'Server error while calling AI. Check NVIDIA_API_KEY and server logs.';
  }
  const trimmed = rawText.trim();
  return trimmed ? trimmed.slice(0, 400) : fallback;
};

const clientLabel = (client: ClientSession) => {
  const name = client.display_name?.trim() || client.client_id;
  return client.broker_no ? `${name}[${client.broker_no}]` : name;
};

const defaultBaselineExpiryLocal = () => {
  const today = todayNepalDate() || currentNepalDateTimeLocal().slice(0, 10);
  const nextDay = addNepalDays(today, 1);
  return `${nextDay}T15:00`;
};

const universeRequiresLogin = (universe: ScreenerUniverse) =>
  universe === 'combined_holdings';

type AnalysisTab = 'screener' | 'new_stocks' | 'data';
type DataSource = 'combined' | 'merolagani' | 'nepse_alpha';

interface NewStockRow {
  symbol: string;
  is_watchlist?: boolean;
}

interface SchedulerStatus {
  running?: boolean;
  market_hours_open?: boolean;
  merolagani_mode?: string;
  nepse_alpha_mode?: string;
  next_merolagani_refresh_in_seconds?: number | null;
  next_nepse_alpha_refresh_in_seconds?: number | null;
  merolagani_refresh_interval_seconds?: number;
  nepse_alpha_refresh_interval_seconds?: number;
}

interface CacheStatus {
  cache?: {
    total?: number;
    merolagani_count?: number;
    nepse_alpha_count?: number;
    combined_count?: number;
    last_updated?: string;
  };
  latest_daily_snapshot?: {
    snapshot_date?: string;
    symbol_count?: number;
    created_at?: string;
  };
  last_daily_refresh?: string;
  last_screener_refresh?: string;
  scheduler?: SchedulerStatus;
}

const formatRefreshIn = (seconds?: number | null) => {
  if (seconds == null) {
    return 'paused';
  }
  if (seconds <= 0) {
    return 'due now';
  }
  if (seconds < 60) {
    return `${seconds}s`;
  }
  if (seconds < 3600) {
    return `${Math.round(seconds / 60)}m`;
  }
  return `${Math.round(seconds / 3600)}h`;
};

const StockAnalysis: React.FC = () => {
  const [analysisTab, setAnalysisTab] = useState<AnalysisTab>('screener');
  const [dataSource, setDataSource] = useState<DataSource>('combined');
  const [cacheStatus, setCacheStatus] = useState<CacheStatus | null>(null);
  const [newStocks, setNewStocks] = useState<NewStockRow[]>([]);
  const [newStocksDays, setNewStocksDays] = useState(15);
  const [dataRows, setDataRows] = useState<Record<string, unknown>[]>([]);
  const [dataColumns, setDataColumns] = useState<string[]>(['symbol']);
  const [dataColumnLabels, setDataColumnLabels] = useState<Record<string, string>>({});
  const [relativeNow, setRelativeNow] = useState(() => Date.now());
  const [dataLoading, setDataLoading] = useState(false);
  const [dataRefreshing, setDataRefreshing] = useState(false);
  const [fields, setFields] = useState<ScreenerField[]>([]);
  const [inputMode, setInputMode] = useState<InputMode>('builder');
  const [queryText, setQueryText] = useState(DEFAULT_QUERY);
  const [activePresetId, setActivePresetId] = useState<string | null>(null);
  const [copyMessage, setCopyMessage] = useState('');
  const [filters, setFilters] = useState<FilterRow[]>([makeFilterRow()]);
  const [universe, setUniverse] = useState<ScreenerUniverse>('nepse');
  const [clientId, setClientId] = useState('');
  const [clientSessions, setClientSessions] = useState<ClientSession[]>([]);
  const [universeLabel, setUniverseLabel] = useState('');
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
  const [baselineModalOpen, setBaselineModalOpen] = useState(false);
  const [baselineScheduleInput, setBaselineScheduleInput] = useState<ScreenerDropScheduleInput | null>(null);
  const [scheduleMessage, setScheduleMessage] = useState('');
  const resultsRef = useRef<HTMLElement | null>(null);

  const activePreset = useMemo(
    () => SCREENER_PRESETS.find((preset) => preset.id === activePresetId) || null,
    [activePresetId],
  );

  const chatGptPromptFull = useMemo(
    () => buildChatGptScreenerPrompt(fields, querySpec),
    [fields, querySpec],
  );
  const chatGptPromptCopy = useMemo(
    () => buildChatGptScreenerPromptForCopy(fields, querySpec),
    [fields, querySpec],
  );

  useEffect(() => {
    const loadFields = async () => {
      const response = await fetchJson<{
        fields: ScreenerField[];
        cache_ttl_seconds: number;
        query_spec?: ScreenerQuerySpec;
      }>('/market_analysis/fields');
      if (response.ok) {
        setFields(response.data.fields || []);
        setCacheTtl(response.data.cache_ttl_seconds || 300);
        setQuerySpec(response.data.query_spec || null);
      }
    };
    void loadFields();
  }, []);

  useEffect(() => {
    const loadStatus = async () => {
      const response = await fetchJson<CacheStatus>('/market_analysis/status');
      if (response.ok) {
        setCacheStatus(response.data);
      }
    };
    void loadStatus();
    const timer = window.setInterval(() => {
      void loadStatus();
    }, 60000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (analysisTab !== 'new_stocks') {
      return;
    }
    const loadNewStocks = async () => {
      setDataLoading(true);
      try {
        const response = await fetchJson<{ symbols?: NewStockRow[] }>(`/market_analysis/new_stocks?days=${newStocksDays}`);
        if (response.ok) {
          setNewStocks(response.data.symbols || []);
        }
      } finally {
        setDataLoading(false);
      }
    };
    void loadNewStocks();
  }, [analysisTab, newStocksDays]);

  const applyMarketDataResponse = useCallback((payload: MarketDataResponse) => {
    const rows = payload.rows || [];
    const columns = payload.columns?.length ? payload.columns : ['symbol'];
    setDataRows(rows);
    setDataColumns(reorderColumnsByData(columns, rows));
    setDataColumnLabels(payload.column_labels || {});
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => setRelativeNow(Date.now()), 30000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (analysisTab !== 'data') {
      return;
    }

    const loadDataRows = async () => {
      setDataLoading(true);
      try {
        const response = await fetchJson<MarketDataResponse>(
          `/market_analysis/data?source=${dataSource}`,
        );
        if (response.ok) {
          applyMarketDataResponse(response.data);
          if (!(response.data.rows || []).length) {
            await fetchJson('/market_analysis/refresh', { method: 'POST' });
            const retry = await fetchJson<MarketDataResponse>(
              `/market_analysis/data?source=${dataSource}`,
            );
            if (retry.ok) {
              applyMarketDataResponse(retry.data);
            }
          }
        }
      } finally {
        setDataLoading(false);
      }
    };
    void loadDataRows();
  }, [analysisTab, applyMarketDataResponse, dataSource]);

  const refreshDataTable = useCallback(async () => {
    setDataRefreshing(true);
    try {
      await fetchJson('/market_analysis/refresh', { method: 'POST' });
      const response = await fetchJson<MarketDataResponse>(
        `/market_analysis/data?source=${dataSource}`,
      );
      if (response.ok) {
        applyMarketDataResponse(response.data);
      }
    } finally {
      setDataRefreshing(false);
    }
  }, [applyMarketDataResponse, dataSource]);

  useEffect(() => {
    if (analysisTab !== 'data') {
      return undefined;
    }
    const timer = window.setInterval(() => {
      void refreshDataTable();
    }, 20 * 60 * 1000);
    return () => window.clearInterval(timer);
  }, [analysisTab, refreshDataTable]);

  useEffect(() => {
    const loadClients = async () => {
      try {
        const response = await fetch(`${getApiUrl()}/logged_in_clients/`);
        if (!response.ok) {
          return;
        }
        const data = await response.json();
        const sessions: ClientSession[] = data.sessions || (data.logged_in_client_ids || []).map((id: string) => ({
          client_id: id,
          broker_no: '',
        }));
        setClientSessions(sessions);
        if (sessions.length > 0) {
          setClientId((current) => current || sessions[0].client_id);
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

  const buildUniversePayload = useCallback(() => {
    const payload: {
      universe: ScreenerUniverse;
      client_id?: string;
      client_ids?: string[];
    } = { universe };

    if (universe === 'client_holdings') {
      payload.client_id = clientId;
    } else if (universe === 'combined_holdings') {
      payload.client_ids = clientSessions.map((session) => session.client_id);
    }

    return payload;
  }, [clientId, clientSessions, universe]);

  const validateUniverse = useCallback((): string | null => {
    if (universe === 'client_holdings') {
      if (!clientId) {
        return 'Select a user to screen their DP holdings.';
      }
      return null;
    }
    if (universeRequiresLogin(universe) && clientSessions.length === 0) {
      return 'At least one logged-in TMS account is required for this symbol universe.';
    }
    return null;
  }, [clientId, clientSessions.length, universe]);

  const selectNepseUniverse = () => {
    setUniverse('nepse');
    setError('');
  };

  const selectCombinedUniverse = () => {
    setUniverse('combined_holdings');
    setError('');
  };

  const selectClientUniverse = (selectedClientId: string) => {
    setUniverse('client_holdings');
    setClientId(selectedClientId);
    setError('');
  };

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
    const universeError = validateUniverse();
    if (universeError) {
      setError(universeError);
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
    setUniverseLabel('');
    setHasRun(false);

    let completedScreen = false;
    try {
      const controller = new AbortController();
      const timeoutId = window.setTimeout(() => controller.abort(), 300000);
      const response = await fetch(`${getApiUrl()}/market_analysis/ai_screen`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...buildUniversePayload(),
          message: userMessage,
          force_refresh: forceRefresh,
        }),
        signal: controller.signal,
      });
      window.clearTimeout(timeoutId);

      const { data, rawText } = await readJsonResponse(response);
      if (data === null) {
        throw new Error(formatNonJsonResponse(rawText, 'Invalid server response'));
      }
      if (!response.ok) {
        const detail = (data as { detail?: unknown })?.detail;
        const generated = detail && typeof detail === 'object' && 'generated_query' in detail
          ? String((detail as { generated_query?: string }).generated_query || '')
          : '';
        if (generated) {
          setGeneratedQuery(generated);
          setQueryText(generated);
        }
        throw new Error(parseApiError(data, 'AI screener request failed'));
      }

      const query = String((data as { generated_query?: string }).generated_query || '');
      const summary = String((data as { ai_summary?: string }).ai_summary || 'Query generated and screened successfully.');
      setGeneratedQuery(query);
      setQueryText(query);
      setAiSummary(summary);
      if ((data as { parsed_query?: { rank_by?: string } }).parsed_query?.rank_by) {
        setRankBy((data as { parsed_query: { rank_by: string } }).parsed_query.rank_by);
      }
      if ((data as { parsed_query?: { rank_direction?: 'asc' | 'desc' } }).parsed_query?.rank_direction) {
        setRankDirection((data as { parsed_query: { rank_direction: 'asc' | 'desc' } }).parsed_query.rank_direction);
      }
      if ((data as { parsed_query?: { limit?: number } }).parsed_query?.limit) {
        setLimit(String((data as { parsed_query: { limit: number } }).parsed_query.limit));
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
      setResults((data as { results?: ScreenerResult[] }).results || []);
      setStats((data as { stats?: ScreenerStats | null }).stats || null);
      setUniverseLabel(String((data as { universe_label?: string }).universe_label || ''));
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
    const universeError = validateUniverse();
    if (universeError) {
      setError(universeError);
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
    setUniverseLabel('');

    if (options?.fromPreset) {
      resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    let completedScreen = false;
    const payload = useQueryMode
      ? {
          ...buildUniversePayload(),
          query,
          force_refresh: forceRefresh,
        }
      : {
          ...buildUniversePayload(),
          filters: buildFilterPayload(),
          rank_by: rankBy,
          rank_direction: rankDirection,
          limit: Math.max(1, Math.min(500, Number(limit) || 25)),
          force_refresh: forceRefresh,
        };

    try {
      const controller = new AbortController();
      const timeoutId = window.setTimeout(() => controller.abort(), 180000);
      const response = await fetch(`${getApiUrl()}/market_analysis/screen`, {
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
      setUniverseLabel(String(data.universe_label || ''));
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
        return buildNepseAlphaChartUrl(sym);
      },
    }),
    [],
  );

  const dataTableRows = useMemo(
    () => formatMarketTableRows(dataRows, relativeNow),
    [dataRows, relativeNow],
  );

  const displayDataColumns = useMemo(
    () => reorderColumnsByData(dataColumns, dataRows),
    [dataColumns, dataRows],
  );

  const formatRelativeTimestamp = (value?: string | null) =>
    formatRelativeTime(value, relativeNow) || '-';

  return (
    <div className="stock-screener-page">
      <section className="stock-screener-hero card">
        <div>
          <h2 className="stock-screener-title">Market Analysis</h2>
          <p className="stock-screener-subtitle">
            Combined Merolagani + Nepse Alpha screener backed by the server database.
            Cache refreshes every {Math.round(cacheTtl / 60)} minutes during market hours.
            Daily Merolagani snapshots track newly listed symbols.
          </p>
        </div>
        <div className="stock-screener-status">
          {cacheStatus?.cache?.combined_count ? (
            <>
              <span>Cached {cacheStatus.cache.combined_count} symbols</span>
              <span>Updated {formatRelativeTimestamp(cacheStatus.cache.last_updated)}</span>
              <span>Daily {cacheStatus.latest_daily_snapshot?.snapshot_date || 'pending'}</span>
              {cacheStatus.scheduler?.running ? (
                <>
                  <span>
                    Merolagani {cacheStatus.scheduler.market_hours_open ? 'live' : 'daily'} · next{' '}
                    {formatRefreshIn(cacheStatus.scheduler.next_merolagani_refresh_in_seconds)}
                  </span>
                  <span>
                    Nepse {cacheStatus.scheduler.market_hours_open ? 'live' : 'paused'} · next{' '}
                    {formatRefreshIn(cacheStatus.scheduler.next_nepse_alpha_refresh_in_seconds)}
                  </span>
                </>
              ) : null}
            </>
          ) : stats ? (
            <>
              {universeLabel && <span>{universeLabel}</span>}
              <span>Scanned {stats.requested}</span>
              <span>Loaded {stats.loaded}</span>
              <span>Matched {stats.matched}</span>
            </>
          ) : (
            <span>Waiting for first cache refresh</span>
          )}
        </div>
      </section>

      <section className="stock-screener-controls card">
        <div className="stock-screener-mode-tabs">
          <button
            type="button"
            className={analysisTab === 'screener' ? 'active' : ''}
            onClick={() => setAnalysisTab('screener')}
          >
            Screener
          </button>
          <button
            type="button"
            className={analysisTab === 'new_stocks' ? 'active' : ''}
            onClick={() => setAnalysisTab('new_stocks')}
          >
            New Stocks (15d)
          </button>
          <button
            type="button"
            className={analysisTab === 'data' ? 'active' : ''}
            onClick={() => setAnalysisTab('data')}
          >
            Data Tables
          </button>
        </div>
      </section>

      {analysisTab === 'new_stocks' && (
        <section className="stock-screener-results card">
          <div className="stock-screener-universe-header">
            <div>
              <h3>New / IPO watchlist</h3>
              <p className="stock-screener-subtitle">
                Symbols first seen in the daily Merolagani snapshot during the selected window.
              </p>
            </div>
            <div className="stock-screener-universe-chips">
              <Dropdown
                value={String(newStocksDays)}
                onChange={(value) => setNewStocksDays(Number(value) || 15)}
                options={[
                  { label: '7 days', value: '7' },
                  { label: '15 days', value: '15' },
                  { label: '30 days', value: '30' },
                  { label: '90 days', value: '90' },
                ]}
              />
              <span className="badge badge-muted">{newStocks.length} stocks</span>
            </div>
          </div>
          {dataLoading ? (
            <p>Loading new symbols…</p>
          ) : newStocks.length === 0 ? (
            <p>No new symbols detected in the selected period.</p>
          ) : (
            <CommonTable
              data={newStocks}
              columns={['symbol', 'is_watchlist']}
              columnLinks={{
                symbol: (row) => buildNepseAlphaChartUrl(String(row.symbol || '')),
              }}
            />
          )}
        </section>
      )}

      {analysisTab === 'data' && (
        <section className="stock-screener-results card">
          <div className="stock-screener-universe-header">
            <h3>Stored market data</h3>
            <div className="stock-screener-universe-chips">
              {(['combined', 'merolagani', 'nepse_alpha'] as DataSource[]).map((source) => (
                <button
                  key={source}
                  type="button"
                  className={`stock-screener-universe-chip${dataSource === source ? ' active' : ''}`}
                  onClick={() => setDataSource(source)}
                >
                  {source === 'combined' ? 'Combined' : source === 'merolagani' ? 'Merolagani' : 'Nepse Alpha'}
                </button>
              ))}
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => void refreshDataTable()}
                disabled={dataRefreshing || dataLoading}
              >
                {dataRefreshing ? 'Refreshing…' : 'Refresh'}
              </button>
            </div>
          </div>
          {dataLoading ? (
            <p>Loading table…</p>
          ) : (
            <CommonTable
              data={dataTableRows}
              columns={displayDataColumns}
              columnLabels={dataColumnLabels}
              columnLinks={{
                symbol: (row) => buildNepseAlphaChartUrl(String(row.symbol || '')),
              }}
            />
          )}
        </section>
      )}

      {analysisTab === 'screener' && (
        <>
      <section className="stock-screener-controls card">
        <div className="stock-screener-universe">
          <div className="stock-screener-universe-header">
            <span className="stock-screener-universe-label">Symbol universe</span>
            <span className="stock-screener-universe-note">
              {universe === 'nepse'
                ? 'All cached Merolagani symbols'
                : universe === 'combined_holdings'
                  ? 'Union of DP holdings across logged-in users'
                  : 'DP holdings for selected user (qty > 0)'}
            </span>
          </div>
          <div className="stock-screener-universe-chips" role="group" aria-label="Symbol universe">
            <button
              type="button"
              className={`stock-screener-universe-chip${universe === 'nepse' ? ' active' : ''}`}
              onClick={selectNepseUniverse}
              disabled={loading}
            >
              NEPSE
            </button>
            <button
              type="button"
              className={`stock-screener-universe-chip${universe === 'combined_holdings' ? ' active' : ''}`}
              onClick={selectCombinedUniverse}
              disabled={loading || clientSessions.length === 0}
              title={clientSessions.length === 0 ? 'Log in at least one TMS account first' : undefined}
            >
              Combined holdings
            </button>
            {clientSessions.map((session) => (
              <button
                key={session.client_id}
                type="button"
                className={`stock-screener-universe-chip user${
                  universe === 'client_holdings' && clientId === session.client_id ? ' active' : ''
                }`}
                onClick={() => selectClientUniverse(session.client_id)}
                disabled={loading}
              >
                {clientLabel(session)}
              </button>
            ))}
          </div>
          {clientSessions.length === 0 && (
            <p className="stock-screener-universe-warning">
              No logged-in TMS accounts. Log in from the Accounts page to use combined or user holdings.
            </p>
          )}
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
              Describe your screen in plain English. DeepSeek builds a strict query on the server
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
                    Copy sends a compact prompt with rules and the live field list. Expand preview below
                    only if you need the full reference catalog (JSON and per-field operator docs).
                  </p>
                </div>
                <div className="stock-screener-prompt-actions">
                  <button
                    type="button"
                    className="btn-primary"
                    onClick={() => void copyText(chatGptPromptCopy, 'ChatGPT prompt')}
                  >
                    Copy prompt for ChatGPT
                  </button>
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => void copyText(chatGptPromptFull, 'Full reference prompt')}
                  >
                    Copy full reference
                  </button>
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => void copyText(SCREENER_QUERY_GUIDE, 'Syntax guide')}
                  >
                    Copy syntax only
                  </button>
                </div>
              </div>
              {copyMessage && !activePreset && <p className="stock-screener-copy-msg">{copyMessage}</p>}
              <details className="stock-screener-ai-prompt-details">
                <summary>Preview full reference prompt ({fields.length} fields documented)</summary>
                <pre className="stock-screener-prompt-body stock-screener-ai-prompt-preview">{chatGptPromptFull}</pre>
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
            {universeLabel && (
              <p className="stock-screener-universe-result">{universeLabel}</p>
            )}
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
                    ? `${universeLabel ? `${universeLabel} · ` : ''}Scanned ${stats.requested} symbols · ${stats.loaded} loaded · ${stats.matched} matched your filters`
                    : 'No stocks matched your filters. Try relaxing conditions or pick another quick screen.'}
                </p>
              </div>
            ) : (
              <>
                {clientId && (
                  <div className="stock-screener-schedule-row">
                    <button
                      type="button"
                      className="btn btn-secondary"
                      onClick={() => {
                        const symbols = results.slice(0, 10).map((row) => row.symbol);
                        setBaselineScheduleInput({
                          clientId,
                          queryText: '',
                          symbols,
                          dropPercent: 10,
                          expiryTimeLocal: defaultBaselineExpiryLocal(),
                          expirationAction: 'CANCEL',
                          strategyType: 'Custom Query Buy',
                        });
                        setBaselineModalOpen(true);
                      }}
                    >
                      Schedule Top {Math.min(results.length, 10)}
                    </button>
                    {scheduleMessage ? <p className="stock-screener-schedule-message">{scheduleMessage}</p> : null}
                  </div>
                )}
                <CommonTable data={results} columns={displayColumns} columnLinks={symbolColumnLinks} />
              </>
            )}
          </section>
        )}
      </section>
        </>
      )}

      <ScreenerDropConfirmModal
        open={baselineModalOpen}
        input={baselineScheduleInput}
        onClose={() => {
          setBaselineModalOpen(false);
          setBaselineScheduleInput(null);
        }}
        onCommitted={({ scheduled, failed }) => {
          setScheduleMessage(
            failed.length
              ? `Scheduled ${scheduled.join(', ')}. Failed: ${failed.join('; ')}`
              : `Baseline schedule created for ${scheduled.join(', ')}.`,
          );
        }}
      />
    </div>
  );
};

export default StockAnalysis;
