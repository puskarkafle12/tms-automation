import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { fetchJson, getApiUrl } from '../utils/api';
import { readUiPortalSettings, subscribeUiPortalSettings } from '../lib/uiPortalSettings';
import {
  formatCurrentRequired,
  formatPriceBoundary,
  formatPreviewWarnings,
  formatQuantityCell,
  type PreviewRow,
} from '../lib/strategies/previewFormatters';
import { buildPreviewKey, buildSchedulePreflightKey, getCustomQueryPreviewReadyLabel, isSchedulePreviewReady, describeSchedulePreviewBlockReason } from '../lib/strategies/rulePlanHelpers';
import './CustomQueryEditor.css';

interface ValidationIssue {
  code: string;
  message: string;
  symbol?: string;
}

interface ValidationResponse {
  valid: boolean;
  status?: string;
  message?: string;
  missing_items?: string[];
  errors: ValidationIssue[];
  warnings: ValidationIssue[];
  suggestions: ValidationIssue[];
  compiled_plan?: Record<string, unknown>;
  targets?: Array<Record<string, unknown>>;
  preview?: PreviewRow[];
  schedule_preview_snapshots_by_symbol?: Record<string, Record<string, unknown>>;
  formatted_query?: string;
  schedule_preflight?: SchedulePreflightResponse;
}

interface SchedulePreflightResponse {
  ready?: boolean;
  status?: string;
  message?: string;
  errors?: ValidationIssue[];
  warnings?: ValidationIssue[];
}

interface AiGenerateResponse extends ValidationResponse {
  generated_query?: string;
  ai_summary?: string;
  ai_retry_count?: number;
  ai_warnings?: ValidationIssue[];
}

interface Props {
  side: 'buy' | 'sell';
  strategyType: string;
  formSymbol?: string;
  clientId?: string;
  holdingsBySymbol?: Record<string, number>;
  knownBuySymbols?: string[];
  initialQuery?: string;
  aiPortalTargetId?: string;
  onPlanChange: (payload: {
    queryText: string;
    compiledPlan?: Record<string, unknown>;
    validation: ValidationResponse | null;
    schedulePreflight?: SchedulePreflightResponse | null;
    schedulePreflightKey?: string;
  }) => void;
  onValidatingChange?: (validating: boolean) => void;
}

const PREVIEW_TIMEOUT_MS = 120000;
const TOAST_DURATION_MS = 4000;
const PREVIEW_STATUS_STEPS = [
  'Validating query syntax...',
  'Fetching live TMS quotes at a safe rate...',
  'Checking Nepse Alpha data at a safe rate...',
  'Estimating trigger prices for each symbol...',
  'Preparing preview results...',
  'Still working on live preview...',
];

const AI_STATUS_STEPS = [
  'Generating strategy query with AI...',
  'Validating syntax and field registry...',
  'Running live preview and schedule preflight...',
  'Refining query after validation feedback...',
  'Still working — AI is correcting the query...',
];

const formatPreviewLtp = (value: unknown): string => {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  return '—';
};

const previewStatusClass = (status?: string, matched?: boolean): string => {
  if (matched) {
    return 'ready';
  }
  const normalized = String(status || '').toUpperCase();
  if (normalized === 'NOT_ELIGIBLE' || normalized === 'NOT_MATCHED') {
    return 'blocked';
  }
  if (normalized.startsWith('WAITING')) {
    return 'waiting';
  }
  return 'neutral';
};

const isHoldingsValidationMessage = (message?: string): boolean => {
  const text = String(message || '').toLowerCase();
  return text.includes('dp holdings') || text.includes('not available in dp holdings');
};

const CustomQueryEditor: React.FC<Props> = ({
  side,
  strategyType,
  formSymbol,
  clientId,
  holdingsBySymbol,
  knownBuySymbols,
  initialQuery,
  aiPortalTargetId,
  onPlanChange,
  onValidatingChange,
}) => {
  const onPlanChangeRef = useRef(onPlanChange);
  onPlanChangeRef.current = onPlanChange;
  const onValidatingChangeRef = useRef(onValidatingChange);
  onValidatingChangeRef.current = onValidatingChange;

  const [queryText, setQueryText] = useState(initialQuery ?? '');
  const [validation, setValidation] = useState<ValidationResponse | null>(null);
  const validationRef = useRef<ValidationResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [autoValidating, setAutoValidating] = useState(false);
  const [error, setError] = useState('');
  const [toastMessage, setToastMessage] = useState('');
  const [previewModalOpen, setPreviewModalOpen] = useState(false);
  const [expandedPreviewRows, setExpandedPreviewRows] = useState<Set<string>>(new Set());
  const [previewStatus, setPreviewStatus] = useState('');
  const [aiPrompt, setAiPrompt] = useState('');
  const [aiSummary, setAiSummary] = useState('');
  const [aiWarnings, setAiWarnings] = useState<ValidationIssue[]>([]);
  const [aiBusy, setAiBusy] = useState(false);
  const [aiPortalTarget, setAiPortalTarget] = useState<HTMLElement | null>(null);
  const validateRequestId = useRef(0);
  const previewAbortRef = useRef<AbortController | null>(null);
  const aiAbortRef = useRef<AbortController | null>(null);
  const lastPreviewKeyRef = useRef('');
  const [schedulePreflightKey, setSchedulePreflightKey] = useState('');
  const skipNextAutoPreviewRef = useRef(false);
  const immediatePreviewRef = useRef(Boolean((initialQuery ?? '').trim()));
  const prevClientIdRef = useRef(clientId);
  const [validateDebounceMs, setValidateDebounceMs] = useState(
    () => readUiPortalSettings().customQueryValidateDebounceMs,
  );

  useEffect(() => subscribeUiPortalSettings((settings) => {
    setValidateDebounceMs(settings.customQueryValidateDebounceMs);
  }), []);

  const previewContext = useCallback(() => ({
    side,
    strategyType,
    formSymbol,
    clientId,
    holdingsBySymbol,
    knownBuySymbols,
  }), [clientId, formSymbol, holdingsBySymbol, knownBuySymbols, side, strategyType]);

  useEffect(() => {
    if (!prevClientIdRef.current && clientId && queryText.trim() && !validationRef.current) {
      immediatePreviewRef.current = true;
    }
    prevClientIdRef.current = clientId;
  }, [clientId, queryText]);

  useLayoutEffect(() => {
    if (!aiPortalTargetId) {
      setAiPortalTarget(null);
      return undefined;
    }
    const syncTarget = () => {
      const target = document.getElementById(aiPortalTargetId);
      setAiPortalTarget(target);
    };
    syncTarget();
    const timer = window.setInterval(syncTarget, 100);
    const stopTimer = window.setTimeout(() => window.clearInterval(timer), 1000);
    return () => {
      window.clearInterval(timer);
      window.clearTimeout(stopTimer);
    };
  }, [aiPortalTargetId]);

  useEffect(() => {
    validationRef.current = validation;
    onPlanChangeRef.current({
      queryText,
      compiledPlan: validation?.compiled_plan,
      validation,
      schedulePreflight: validation?.schedule_preflight ?? null,
      schedulePreflightKey,
    });
  }, [queryText, schedulePreflightKey, validation]);

  useEffect(() => {
    if (!toastMessage) {
      return undefined;
    }
    const timer = window.setTimeout(() => setToastMessage(''), TOAST_DURATION_MS);
    return () => window.clearTimeout(timer);
  }, [toastMessage]);

  useEffect(() => {
    if (!previewModalOpen) {
      setExpandedPreviewRows(new Set());
      return undefined;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setPreviewModalOpen(false);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [previewModalOpen]);

  const togglePreviewRow = (rowKey: string) => {
    setExpandedPreviewRows((current) => {
      const next = new Set(current);
      if (next.has(rowKey)) {
        next.delete(rowKey);
      } else {
        next.add(rowKey);
      }
      return next;
    });
  };

  const runPreview = useCallback(async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed) {
      previewAbortRef.current?.abort();
      previewAbortRef.current = null;
      setValidation(null);
      setError('');
      setAutoValidating(false);
      setBusy(false);
      setPreviewStatus('');
      onValidatingChangeRef.current?.(false);
      return;
    }

    const previewKey = buildPreviewKey({ queryText: trimmed, ...previewContext() });
    const nextSchedulePreflightKey = buildSchedulePreflightKey({
      queryText: trimmed,
      side,
      strategyType,
      clientId,
      formSymbol,
    });
    if (lastPreviewKeyRef.current === previewKey && validationRef.current) {
      // A textarea edit sets validating=true before debounce; if the preview key
      // is unchanged we must clear that flag or the schedule button stays disabled.
      onValidatingChangeRef.current?.(false);
      setBusy(false);
      setAutoValidating(false);
      setPreviewStatus('');
      return;
    }

    previewAbortRef.current?.abort();
    const abortController = new AbortController();
    previewAbortRef.current = abortController;

    const requestId = validateRequestId.current + 1;
    validateRequestId.current = requestId;
    setBusy(true);
    setAutoValidating(true);
    setPreviewStatus(PREVIEW_STATUS_STEPS[0]);
    onValidatingChangeRef.current?.(true);
    setError('');

    try {
      const result = await fetchJson<ValidationResponse>('/api/strategy-plans/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query_text: trimmed,
          strategy_type: strategyType,
          side,
          form_symbol: formSymbol,
          client_id: clientId,
          skip_live_checks: false,
          holdings_by_symbol: holdingsBySymbol && Object.keys(holdingsBySymbol).length > 0
            ? holdingsBySymbol
            : undefined,
          known_symbols: knownBuySymbols && knownBuySymbols.length > 0 ? knownBuySymbols : undefined,
          include_schedule_preflight: true,
        }),
        signal: abortController.signal,
      }, PREVIEW_TIMEOUT_MS);
      if ((!result.ok && result.cancelled) || requestId !== validateRequestId.current) {
        return;
      }
      if (!result.ok) {
        setValidation(null);
        setError(result.error || 'Could not validate strategy query.');
        return;
      }
      const data = result.data;
      lastPreviewKeyRef.current = previewKey;
      setSchedulePreflightKey(nextSchedulePreflightKey);
      setValidation(data);
      if (!data.valid && data.errors?.length) {
        setError(data.errors[0].message);
      } else {
        setError('');
      }
    } catch (err) {
      if (requestId !== validateRequestId.current) {
        return;
      }
      if (err instanceof Error && err.name === 'AbortError') {
        return;
      }
      setError(err instanceof Error ? err.message : 'Preview request failed');
    } finally {
      if (requestId === validateRequestId.current) {
        if (previewAbortRef.current === abortController) {
          previewAbortRef.current = null;
        }
        setBusy(false);
        setAutoValidating(false);
        setPreviewStatus('');
        onValidatingChangeRef.current?.(false);
      }
    }
  }, [previewContext]);

  useEffect(() => {
    if (!busy && !aiBusy) {
      return undefined;
    }
    const steps = aiBusy ? AI_STATUS_STEPS : PREVIEW_STATUS_STEPS;
    let index = 0;
    const timer = window.setInterval(() => {
      index = Math.min(index + 1, steps.length - 1);
      setPreviewStatus(steps[index]);
    }, 1400);
    return () => window.clearInterval(timer);
  }, [aiBusy, busy]);

  useEffect(() => {
    if (skipNextAutoPreviewRef.current) {
      skipNextAutoPreviewRef.current = false;
      return undefined;
    }
    let delay = validateDebounceMs;
    if (immediatePreviewRef.current) {
      delay = 0;
      immediatePreviewRef.current = false;
    }
    const timer = window.setTimeout(() => {
      void runPreview(queryText);
    }, delay);
    return () => {
      window.clearTimeout(timer);
      previewAbortRef.current?.abort();
      previewAbortRef.current = null;
    };
  }, [queryText, runPreview, validateDebounceMs]);

  const copyLlmPrompt = async (event: React.MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.stopPropagation();
    setToastMessage('');
    const params = new URLSearchParams({ side });
    if (formSymbol) {
      params.set('form_symbol', formSymbol);
    }
    const result = await fetchJson<{ prompt: string }>(`/api/strategy-builder/llm-prompt?${params.toString()}`);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    try {
      await navigator.clipboard.writeText(result.data.prompt);
      setToastMessage('LLM prompt copied to clipboard.');
    } catch {
      setError('Could not copy prompt to clipboard.');
    }
  };

  const applyValidationResult = useCallback((text: string, data: ValidationResponse) => {
    const previewKey = buildPreviewKey({ queryText: text, ...previewContext() });
    const nextSchedulePreflightKey = buildSchedulePreflightKey({
      queryText: text.trim(),
      side,
      strategyType,
      clientId,
      formSymbol,
    });
    lastPreviewKeyRef.current = previewKey;
    setSchedulePreflightKey(nextSchedulePreflightKey);
    setValidation(data);
    setBusy(false);
    setAutoValidating(false);
    setPreviewStatus('');
    onValidatingChangeRef.current?.(false);
    if (!data.valid && data.errors?.length) {
      setError(data.errors[0].message);
    } else {
      setError('');
    }
  }, [clientId, formSymbol, previewContext, side, strategyType]);

  const askAi = async (event: React.MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.stopPropagation();
    const message = aiPrompt.trim();
    if (!message) {
      setError('Describe the strategy you want the AI to write.');
      return;
    }
    previewAbortRef.current?.abort();
    previewAbortRef.current = null;
    aiAbortRef.current?.abort();
    const abortController = new AbortController();
    aiAbortRef.current = abortController;
    setAiBusy(true);
    setAutoValidating(true);
    setPreviewStatus(AI_STATUS_STEPS[0]);
    onValidatingChangeRef.current?.(true);
    setError('');
    setAiSummary('');
    setAiWarnings([]);
    setToastMessage('');
    try {
      const response = await fetch(`${getApiUrl()}/api/strategy-plans/generate-query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message,
          side,
          strategy_type: strategyType,
          form_symbol: formSymbol,
          client_id: clientId,
          current_query: queryText.trim() || undefined,
          holdings_by_symbol: holdingsBySymbol && Object.keys(holdingsBySymbol).length > 0
            ? holdingsBySymbol
            : undefined,
          known_symbols: knownBuySymbols && knownBuySymbols.length > 0 ? knownBuySymbols : undefined,
        }),
        signal: abortController.signal,
      });
      const body = await response.json().catch(() => ({} as AiGenerateResponse & { detail?: unknown }));
      if (!response.ok) {
        const detail = body?.detail;
        const generatedQuery = detail && typeof detail === 'object' && 'generated_query' in detail
          ? String((detail as { generated_query?: string }).generated_query || '')
          : String(body.generated_query || '');
        if (generatedQuery) {
          setQueryText(generatedQuery);
          skipNextAutoPreviewRef.current = true;
        }
        const failureMessage = detail && typeof detail === 'object' && 'message' in detail
          ? String((detail as { message?: string }).message || 'AI request failed')
          : String(body.message || `HTTP ${response.status}`);
        throw new Error(failureMessage);
      }

      const data = body as AiGenerateResponse;
      const generated = data.generated_query || '';
      if (!generated) {
        throw new Error('AI did not return a strategy query.');
      }

      setQueryText(generated);
      skipNextAutoPreviewRef.current = true;
      applyValidationResult(generated, {
        valid: Boolean(data.valid),
        status: data.status,
        message: data.message,
        errors: data.errors || [],
        warnings: data.warnings || [],
        suggestions: data.suggestions || [],
        compiled_plan: data.compiled_plan,
        preview: data.preview,
        schedule_preflight: data.schedule_preflight,
      });

      const summaryLines = [
        data.ai_summary
          || `Strategy query generated${typeof data.ai_retry_count === 'number' && data.ai_retry_count > 0 ? ` after ${data.ai_retry_count} retry attempt(s)` : ''}.`,
        data.schedule_preflight?.ready ? 'Schedule preflight: ready.' : '',
        data.preview?.length ? `Preview ready for ${data.preview.length} symbol(s).` : '',
      ].filter(Boolean);
      setAiSummary(summaryLines.join('\n'));
      setAiWarnings(data.warnings || data.ai_warnings || []);
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') {
        return;
      }
      setError(err instanceof Error ? err.message : 'AI request failed');
    } finally {
      if (aiAbortRef.current === abortController) {
        aiAbortRef.current = null;
        setAiBusy(false);
        setAutoValidating(false);
        setPreviewStatus('');
        onValidatingChangeRef.current?.(false);
      }
    }
  };

  const previewRows = validation?.preview ?? [];
  const hasPreviewRows = previewRows.length > 0;
  const visibleError = error;
  const visibleErrors = validation?.errors || [];
  const visibleWarnings = validation?.warnings || [];
  const aiVisibleError = error && !isHoldingsValidationMessage(error) ? error : '';
  const isSilentOk = Boolean(
    validation
    && validation.valid
    && validation.errors.length === 0
    && validation.warnings.length === 0
    && validation.status !== 'unsupported_data',
  );
  const schedulePreviewReady = Boolean(
    validation?.valid
    && validation.compiled_plan
    && isSchedulePreviewReady(validation, validation.compiled_plan),
  );
  const [previewReadyQueryKey, setPreviewReadyQueryKey] = useState('');
  const trimmedQueryText = queryText.trim();

  useEffect(() => {
    if (schedulePreviewReady && trimmedQueryText) {
      setPreviewReadyQueryKey(trimmedQueryText);
    }
  }, [schedulePreviewReady, trimmedQueryText]);

  useEffect(() => {
    if (previewReadyQueryKey && trimmedQueryText !== previewReadyQueryKey) {
      setPreviewReadyQueryKey('');
    }
  }, [previewReadyQueryKey, trimmedQueryText]);

  const showPreviewReadyLabel = Boolean(
    previewReadyQueryKey
    && previewReadyQueryKey === trimmedQueryText
    && validation?.compiled_plan,
  );
  const aiPanel = (
    <div className="custom-query-ai-panel">
      <label htmlFor="strategyAiPrompt">Ask AI to generate strategy query</label>
      <textarea
        id="strategyAiPrompt"
        className="custom-query-ai-prompt"
        rows={4}
        value={aiPrompt}
        placeholder="Example: Buy CZBIL and NABIL when RSI 14 is above 30, quantity 100 each"
        onChange={(event) => setAiPrompt(event.target.value)}
      />
      <div className="custom-query-ai-actions">
        <button type="button" disabled={aiBusy} onClick={(event) => void askAi(event)}>
          {aiBusy ? 'Generating…' : 'Ask AI'}
        </button>
        <button type="button" className="custom-query-copy-btn" onClick={(event) => void copyLlmPrompt(event)}>
          Copy Prompt
        </button>
      </div>
      {aiSummary ? <div className="custom-query-ai-summary">{aiSummary.split('\n').map((line) => <div key={line}>{line}</div>)}</div> : null}
      {aiWarnings.map((warning) => (
        <div key={`ai-${warning.code}-${warning.message}`} className="custom-query-warning custom-query-ai-warning">
          AI note: {warning.message}
        </div>
      ))}
      {aiVisibleError ? <div className="custom-query-error">{aiVisibleError}</div> : null}
    </div>
  );

  return (
    <div className="custom-query-editor">
      {toastMessage ? (
        <div className="custom-query-toast" role="status" aria-live="polite">
          {toastMessage}
        </div>
      ) : null}

      {aiPortalTarget ? createPortal(aiPanel, aiPortalTarget) : aiPanel}

      <label htmlFor="strategyQueryText">Strategy Query</label>
      <textarea
        id="strategyQueryText"
        className="custom-query-textarea"
        rows={16}
        value={queryText}
        onPaste={() => {
          immediatePreviewRef.current = true;
        }}
        onChange={(event) => {
          aiAbortRef.current?.abort();
          aiAbortRef.current = null;
          const nativeEvent = event.nativeEvent as InputEvent;
          const inputType = nativeEvent?.inputType || '';
          if (inputType === 'insertFromPaste' || inputType === 'insertFromDrop') {
            immediatePreviewRef.current = true;
          }
          setQueryText(event.target.value);
        }}
      />
      <div className="custom-query-actions">
        {hasPreviewRows ? (
          <button
            type="button"
            className="custom-query-preview-btn"
            disabled={busy}
            onClick={() => setPreviewModalOpen(true)}
          >
            Preview details ({previewRows.length})
          </button>
        ) : null}
        {showPreviewReadyLabel && validation ? (
          <span className="custom-query-preview-ok">
            {getCustomQueryPreviewReadyLabel(validation, validation.compiled_plan)}
          </span>
        ) : autoValidating || busy ? (
          <span className="custom-query-validating">{previewStatus || 'Loading preview...'}</span>
        ) : schedulePreviewReady && validation ? (
          <span className="custom-query-preview-ok">
            {getCustomQueryPreviewReadyLabel(validation, validation.compiled_plan)}
          </span>
        ) : validation?.valid ? (
          <span className="custom-query-validating">
            {describeSchedulePreviewBlockReason(validation, validation.compiled_plan)
              || 'Preview not ready to schedule.'}
          </span>
        ) : null}
      </div>
      {visibleError ? <div className="custom-query-error">{visibleError}</div> : null}
      {validation ? (
        <div className="custom-query-results">
          {validation.status === 'unsupported_data' ? (
            <div className="custom-query-error">
              <strong>We do not currently have the requested data.</strong>
              {validation.message ? <div>{validation.message}</div> : null}
              {validation.missing_items?.length ? (
                <div>Missing: {validation.missing_items.join(', ')}</div>
              ) : null}
              {validation.suggestions.length ? (
                <div>
                  Try using one of these available alternatives:
                  <ul>
                    {validation.suggestions.map((item) => (
                      <li key={`${item.code}-${item.symbol || item.message}`}>{item.message}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
          ) : null}
          {!isSilentOk && !validation.valid && validation.errors.length === 0 ? (
            <div className="custom-query-error">Query is invalid.</div>
          ) : null}
          {visibleErrors.length > 0 ? (
            visibleErrors.map((issue) => (
              <div key={`${issue.code}-${issue.message}`} className="custom-query-error">
                {issue.message}
              </div>
            ))
          ) : null}
          {visibleWarnings.map((warning) => (
            <div key={`${warning.code}-${warning.symbol || warning.message}`} className="custom-query-warning">
              {warning.message}
            </div>
          ))}
        </div>
      ) : null}

      {previewModalOpen && hasPreviewRows ? (
        <div
          className="custom-query-preview-backdrop"
          role="presentation"
          onClick={() => setPreviewModalOpen(false)}
        >
          <div
            className="custom-query-preview-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="custom-query-preview-title"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="custom-query-preview-header">
              <div>
                <h3 id="custom-query-preview-title">Strategy Preview</h3>
                <p>{previewRows.length} rule target{previewRows.length === 1 ? '' : 's'} evaluated against current market data.</p>
              </div>
              <button
                type="button"
                className="custom-query-preview-close"
                onClick={() => setPreviewModalOpen(false)}
                aria-label="Close preview details"
              >
                ×
              </button>
            </div>
            <div className="custom-query-preview-table-wrap">
              <table className="custom-query-preview-table custom-query-preview-table-semantic">
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Status</th>
                    <th>LTP</th>
                    <th>Trigger</th>
                    <th>Qty</th>
                    <th>Progress</th>
                  </tr>
                </thead>
                <tbody>
                  {previewRows.map((row) => {
                    const warnings = formatPreviewWarnings(row);
                    const rowKey = `${row.symbol}-${row.rule}`;
                    const expanded = expandedPreviewRows.has(rowKey);
                    const triggerText = row.trigger?.strategy_text
                      || (row.trigger_ltp != null ? `Trigger ${row.trigger_ltp}` : '—');
                    const progressText = formatCurrentRequired(row);
                    const hasMore = Boolean(
                      triggerText !== '—'
                      || row.confirmation?.display
                      || row.execution_policy?.display
                      || row.reason
                      || row.blocker
                      || row.message
                      || warnings.length
                      || row.strategy,
                    );
                    return (
                    <tr key={rowKey} className={row.matched ? 'preview-row-ready' : 'preview-row-blocked'}>
                      <td className="custom-query-preview-symbol">{String(row.symbol ?? '—')}</td>
                      <td>
                        <span className={`custom-query-status-pill ${previewStatusClass(row.status, row.matched)}`}>
                          {row.status_label || row.status || '—'}
                        </span>
                      </td>
                      <td className="custom-query-preview-ltp">{formatPreviewLtp(row.preview_ltp)}</td>
                      <td>{formatPriceBoundary(row)}</td>
                      <td className="custom-query-preview-pre">
                        {formatQuantityCell(row).split('\n')[0]}
                      </td>
                      <td className="custom-query-preview-stack">
                        <div>{progressText === '—' ? (row.reason || '—') : progressText.split('\n')[0]}</div>
                        {hasMore ? (
                          <button
                            type="button"
                            className="custom-query-preview-see-more"
                            onClick={() => togglePreviewRow(rowKey)}
                          >
                            {expanded ? 'See less' : 'See more'}
                          </button>
                        ) : null}
                        {expanded ? (
                          <div className="custom-query-preview-more">
                            {triggerText !== '—' ? (
                              <div><span className="custom-query-preview-label">Condition</span> {triggerText}</div>
                            ) : null}
                            {row.confirmation?.display ? (
                              <div><span className="custom-query-preview-label">Confirmation</span> {row.confirmation.display}</div>
                            ) : null}
                            {row.execution_policy?.display ? (
                              <div className="custom-query-preview-muted">{row.execution_policy.display}</div>
                            ) : null}
                            {row.reason || row.blocker || row.message ? (
                              <div className="custom-query-preview-muted">{row.reason || row.blocker || row.message}</div>
                            ) : null}
                            {row.strategy ? (
                              <div className="custom-query-preview-strategy">{row.strategy}</div>
                            ) : null}
                            {warnings.map((warning) => (
                              <div key={warning} className="custom-query-preview-warning">{warning}</div>
                            ))}
                          </div>
                        ) : null}
                      </td>
                    </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
};

export default CustomQueryEditor;
