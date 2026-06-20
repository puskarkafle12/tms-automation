import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { fetchJson } from '../utils/api';
import { readUiPortalSettings, subscribeUiPortalSettings } from '../lib/uiPortalSettings';
import {
  formatCurrentRequired,
  formatPriceBoundary,
  formatPreviewWarnings,
  formatQuantityCell,
  type PreviewRow,
} from '../lib/strategies/previewFormatters';
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
  'Preparing preview results...',
  'Still working on live preview...',
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

const buildSchedulePreflightKey = (params: {
  queryText: string;
  side: 'buy' | 'sell';
  strategyType: string;
  clientId?: string;
  formSymbol?: string;
}) => JSON.stringify({
  query: params.queryText.trim(),
  side: params.side,
  strategyType: params.strategyType,
  clientId: params.clientId || '',
  formSymbol: params.formSymbol || '',
});

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
  const [previewStatus, setPreviewStatus] = useState('');
  const [aiPrompt, setAiPrompt] = useState('');
  const [aiSummary, setAiSummary] = useState('');
  const [aiBusy, setAiBusy] = useState(false);
  const [aiPortalTarget, setAiPortalTarget] = useState<HTMLElement | null>(null);
  const validateRequestId = useRef(0);
  const lastPreviewKeyRef = useRef('');
  const [schedulePreflightKey, setSchedulePreflightKey] = useState('');
  const skipNextAutoPreviewRef = useRef(false);
  const [validateDebounceMs, setValidateDebounceMs] = useState(
    () => readUiPortalSettings().customQueryValidateDebounceMs,
  );

  useEffect(() => subscribeUiPortalSettings((settings) => {
    setValidateDebounceMs(settings.customQueryValidateDebounceMs);
  }), []);

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

  const runPreview = useCallback(async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed) {
      setValidation(null);
      setError('');
      setAutoValidating(false);
      setBusy(false);
      setPreviewStatus('');
      onValidatingChangeRef.current?.(false);
      return;
    }

    const previewKey = JSON.stringify({
      query: trimmed,
      side,
      strategyType,
      formSymbol: formSymbol || '',
      clientId: clientId || '',
      holdingsCount: holdingsBySymbol ? Object.keys(holdingsBySymbol).length : 0,
      knownSymbolsCount: knownBuySymbols?.length || 0,
    });
    const nextSchedulePreflightKey = buildSchedulePreflightKey({
      queryText: trimmed,
      side,
      strategyType,
      clientId,
      formSymbol,
    });
    if (lastPreviewKeyRef.current === previewKey && validationRef.current) {
      return;
    }

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
      }, PREVIEW_TIMEOUT_MS);
      if (requestId !== validateRequestId.current) {
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
      setError(err instanceof Error ? err.message : 'Preview request failed');
    } finally {
      if (requestId === validateRequestId.current) {
        setBusy(false);
        setAutoValidating(false);
        setPreviewStatus('');
        onValidatingChangeRef.current?.(false);
      }
    }
  }, [clientId, formSymbol, holdingsBySymbol, knownBuySymbols, side, strategyType]);

  useEffect(() => {
    if (!busy) {
      return undefined;
    }
    let index = 0;
    const timer = window.setInterval(() => {
      index = Math.min(index + 1, PREVIEW_STATUS_STEPS.length - 1);
      setPreviewStatus(PREVIEW_STATUS_STEPS[index]);
    }, 1400);
    return () => window.clearInterval(timer);
  }, [busy]);

  useEffect(() => {
    if (skipNextAutoPreviewRef.current) {
      skipNextAutoPreviewRef.current = false;
      return undefined;
    }
    const timer = window.setTimeout(() => {
      void runPreview(queryText);
    }, validateDebounceMs);
    return () => window.clearTimeout(timer);
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

  const askAi = async (event: React.MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.stopPropagation();
    const message = aiPrompt.trim();
    if (!message) {
      setError('Describe the strategy you want the AI to write.');
      return;
    }
    setAiBusy(true);
    setAutoValidating(true);
    setPreviewStatus('Generating AI query...');
    onValidatingChangeRef.current?.(true);
    setError('');
    setAiSummary('');
    setToastMessage('');
    let startedPreview = false;
    try {
      const result = await fetchJson<AiGenerateResponse>('/api/strategy-plans/generate-query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message,
          side,
          strategy_type: strategyType,
          form_symbol: formSymbol,
          client_id: clientId,
          current_query: queryText.trim() || undefined,
        }),
      }, 300000);
      if (!result.ok) {
        throw new Error(result.error);
      }
      const data = result.data;
      const generated = data.generated_query || '';
      if (!generated) {
        throw new Error('AI did not return a strategy query.');
      }
      setQueryText(generated);
      setValidation({
        valid: true,
        errors: data.errors || [],
        warnings: data.warnings || [],
        suggestions: data.suggestions || [],
        compiled_plan: data.compiled_plan,
        preview: data.preview,
      });
      setAiSummary(
        data.ai_summary
          || `Strategy query generated${typeof data.ai_retry_count === 'number' && data.ai_retry_count > 0 ? ` after ${data.ai_retry_count} retry attempt(s)` : ''}.`,
      );
      startedPreview = true;
      skipNextAutoPreviewRef.current = true;
      void runPreview(generated);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'AI request failed');
    } finally {
      setAiBusy(false);
      if (!startedPreview) {
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
        <button type="button" disabled={busy || aiBusy} onClick={(event) => void askAi(event)}>
          {aiBusy ? 'Generating...' : 'Ask AI'}
        </button>
        <button type="button" className="custom-query-copy-btn" onClick={(event) => void copyLlmPrompt(event)}>
          Copy Prompt
        </button>
      </div>
      {aiSummary ? <div className="custom-query-warning">{aiSummary}</div> : null}
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
        onChange={(event) => setQueryText(event.target.value)}
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
        {autoValidating || busy ? (
          <span className="custom-query-validating">{previewStatus || 'Loading preview...'}</span>
        ) : validation?.valid ? (
          <span className="custom-query-preview-ok">Preview OK</span>
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
                    <th>Market</th>
                    <th>Order</th>
                    <th>Trigger</th>
                    <th>Progress</th>
                    <th>Why</th>
                  </tr>
                </thead>
                <tbody>
                  {previewRows.map((row) => {
                    const warnings = formatPreviewWarnings(row);
                    const triggerText = row.trigger?.strategy_text
                      || (row.trigger_ltp != null ? `Trigger ${row.trigger_ltp}` : '—');
                    return (
                    <tr key={`${row.symbol}-${row.rule}`} className={row.matched ? 'preview-row-ready' : 'preview-row-blocked'}>
                      <td className="custom-query-preview-symbol">{String(row.symbol ?? '—')}</td>
                      <td>
                        <span className={`custom-query-status-pill ${previewStatusClass(row.status, row.matched)}`}>
                          {row.status_label || row.status || '—'}
                        </span>
                      </td>
                      <td className="custom-query-preview-stack">
                        <div><span className="custom-query-preview-label">Live LTP</span> {formatPreviewLtp(row.preview_ltp)}</div>
                        {row.reference_ltp != null ? (
                          <div><span className="custom-query-preview-label">Ref LTP</span> {formatPreviewLtp(row.reference_ltp)}</div>
                        ) : null}
                      </td>
                      <td className="custom-query-preview-stack custom-query-preview-pre">
                        <div><span className="custom-query-preview-label">Est. Qty</span></div>
                        {formatQuantityCell(row).split('\n').map((line) => (
                          <div key={line}>{line}</div>
                        ))}
                        {row.execution_price?.description ? (
                          <div className="custom-query-preview-muted">{row.execution_price.description}</div>
                        ) : null}
                      </td>
                      <td className="custom-query-preview-stack">
                        <div><span className="custom-query-preview-label">Price Boundary</span> {formatPriceBoundary(row)}</div>
                        <div><span className="custom-query-preview-label">Condition</span> {triggerText}</div>
                        <div className="custom-query-preview-muted">{formatCurrentRequired(row).split('\n').map((line) => (
                          <div key={line}>{line}</div>
                        ))}</div>
                      </td>
                      <td className="custom-query-preview-stack">
                        {row.confirmation?.display ? (
                          <div><span className="custom-query-preview-label">Confirmation</span> {row.confirmation.display}</div>
                        ) : null}
                        {row.execution_policy?.display ? (
                          <div className="custom-query-preview-muted">{row.execution_policy.display}</div>
                        ) : null}
                      </td>
                      <td className="custom-query-preview-blocker">
                        {row.strategy ? (
                          <div className="custom-query-preview-strategy">{row.strategy}</div>
                        ) : null}
                        {row.reason || row.blocker || row.message || (row.matched ? 'Ready to execute' : '—')}
                        {warnings.map((warning) => (
                          <div key={warning} className="custom-query-preview-warning">{warning}</div>
                        ))}
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
