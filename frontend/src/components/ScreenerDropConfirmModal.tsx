import React, { useCallback, useEffect, useMemo, useState } from 'react';
import ErrorMessage from './ErrorMessage';
import {
  commitScreenerDropBatch,
  previewScreenerDropBatch,
  ScreenerDropPreviewResponse,
  ScreenerDropScheduleInput,
} from '../api/screenerDrop.api';
import './ScreenerDropConfirmModal.css';

interface Props {
  open: boolean;
  input: ScreenerDropScheduleInput | null;
  onClose: () => void;
  onCommitted: (result: { scheduled: string[]; failed: string[] }) => void;
}

const formatMoney = (value?: number) =>
  value == null || Number.isNaN(Number(value)) ? '—' : Number(value).toFixed(1);

const formatPercent = (value?: number) =>
  value == null || Number.isNaN(Number(value)) ? '—' : `${Number(value).toFixed(1)}%`;

const ScreenerDropConfirmModal: React.FC<Props> = ({ open, input, onClose, onCommitted }) => {
  const [loading, setLoading] = useState(false);
  const [committing, setCommitting] = useState(false);
  const [error, setError] = useState('');
  const [preview, setPreview] = useState<ScreenerDropPreviewResponse | null>(null);

  const canConfirm = useMemo(
    () => Boolean(preview?.ready && (preview.rows?.length || 0) > 0 && !loading && !committing),
    [committing, loading, preview],
  );

  const loadPreview = useCallback(async () => {
    if (!input) {
      return;
    }
    setLoading(true);
    setError('');
    setPreview(null);
    const response = await previewScreenerDropBatch(input);
    setLoading(false);
    if (!response.ok) {
      setError(response.error || 'Preview failed.');
      return;
    }
    if (!response.data.ready) {
      const detail = response.data.errors?.[0]?.message || 'Cannot preview baseline schedule.';
      setError(detail);
    }
    setPreview(response.data);
  }, [input]);

  useEffect(() => {
    if (open && input) {
      void loadPreview();
    } else {
      setPreview(null);
      setError('');
      setLoading(false);
      setCommitting(false);
    }
  }, [input, loadPreview, open]);

  const handleConfirm = async () => {
    if (!input || !canConfirm) {
      return;
    }
    setCommitting(true);
    setError('');
    const response = await commitScreenerDropBatch(input);
    setCommitting(false);
    if (!response.ok) {
      setError(response.error || 'Commit failed.');
      return;
    }
    const scheduled = (response.data.scheduled || []).map((row) => row.symbol);
    const failed = (response.data.failed || []).map((row) => `${row.symbol}: ${row.message}`);
    onCommitted({ scheduled, failed });
    onClose();
  };

  if (!open || !input) {
    return null;
  }

  return (
    <div className="screener-drop-modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className="screener-drop-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="screener-drop-modal-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="screener-drop-modal-header">
          <h2 id="screener-drop-modal-title">Confirm fixed baseline schedule</h2>
          <button type="button" className="screener-drop-modal-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>

        <p>
          Scheduling {input.symbols.length} symbol{input.symbols.length === 1 ? '' : 's'} with a fixed reference LTP
          and pullback trigger. Quotes are captured again on confirm.
        </p>

        {preview?.baseline_warning ? (
          <p className="screener-drop-modal-warning">{preview.baseline_warning}</p>
        ) : null}
        {preview?.expiration_notice ? (
          <p className="screener-drop-modal-notice">{preview.expiration_notice}</p>
        ) : null}

        {loading ? <p className="screener-drop-modal-loading">Loading preview quotes…</p> : null}
        {error ? <ErrorMessage message={error} variant="error" persistent /> : null}

        {preview?.rows?.length ? (
          <div className="screener-drop-modal-table-wrap">
            <table className="screener-drop-modal-table">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Ref LTP</th>
                  <th>Drop %</th>
                  <th>Trigger</th>
                  <th>Qty</th>
                  <th>Expiry action</th>
                  <th>Slippage</th>
                </tr>
              </thead>
              <tbody>
                {preview.rows.map((row) => (
                  <tr key={row.symbol}>
                    <td>{row.symbol}</td>
                    <td>{formatMoney(row.reference_ltp)}</td>
                    <td>{formatPercent(row.drop_percent)}</td>
                    <td>{formatMoney(row.trigger_price)}</td>
                    <td>{row.qty ?? '—'}</td>
                    <td>{row.expiration_action || input.expirationAction}</td>
                    <td>{formatPercent(row.max_allowed_slippage_percent ?? input.maxSlippagePercent)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}

        <div className="screener-drop-modal-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={committing}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => void handleConfirm()}
            disabled={!canConfirm}
          >
            {committing ? 'Scheduling…' : 'Confirm schedule'}
          </button>
        </div>
      </div>
    </div>
  );
};

export default ScreenerDropConfirmModal;
