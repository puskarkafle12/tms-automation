import React, { useCallback, useEffect, useMemo, useState } from 'react';
import StrategySellForm, { StrategyPayload } from './StrategySellForm';
import type { StrategyFormPrefill } from './strategyValidation';
import { formatStrategyLabel } from '../../lib/strategies';
import { isoToNepalDateTimeLocal } from '../../utils/nepalTime';
import ErrorMessage from '../../components/ErrorMessage';
import './EditScheduledOrderModal.css';

export interface ScheduledOrderDetail {
  order_id: number;
  client_id: string;
  script_name: string;
  price: number;
  qty: number;
  status: string;
  order_type: string;
  strategy_type?: string;
  side?: string;
  security_details?: Record<string, unknown>;
  stop_loss_price?: number | null;
  stop_limit_price?: number | null;
  book_profit_price?: number | null;
  profit_target_price?: number | null;
  trailing_drop_percent?: number | null;
  stable_band_percent?: number | null;
  minimum_wait_minutes?: number | null;
  consecutive_drop_checks?: number | null;
  activation_price?: number | null;
  average_buy_price?: number | null;
  partial_legs?: Array<{ id?: string; targetPrice?: number; sellPercent?: number }>;
  expiry_time?: string | null;
  expiry_action?: string | null;
  max_allowed_slippage_percent?: number | null;
  emergency_execution?: boolean;
  strategy_config?: Record<string, unknown>;
  editable?: boolean;
}

interface Props {
  orderId: number;
  apiUrl: string;
  onClose: () => void;
  onSaved: () => void;
}

const toInput = (value: number | null | undefined) =>
  value == null || Number.isNaN(Number(value)) ? '' : String(value);

const buildPrefill = (order: ScheduledOrderDetail): StrategyFormPrefill => {
  const legs = order.partial_legs || [];
  const firstLeg = legs[0];
  const secondLeg = legs[1];
  const config = order.strategy_config || {};

  return {
    strategy: formatStrategyLabel(order.strategy_type || '', order.order_type || order.side || ''),
    qty: toInput(order.qty),
    price: toInput(order.price),
    stopLossPrice: toInput(order.stop_loss_price),
    stopLimitPrice: toInput(order.stop_limit_price),
    bookProfitPrice: toInput(order.book_profit_price),
    profitTargetPrice: toInput(order.profit_target_price),
    trailingDropPercent: toInput(order.trailing_drop_percent) || '3',
    stableBandPercent: toInput(order.stable_band_percent) || '0.20',
    minimumWaitMinutes: toInput(order.minimum_wait_minutes) || '5',
    consecutiveDropChecks: toInput(order.consecutive_drop_checks) || '2',
    activationPrice: toInput(order.activation_price),
    averagePrice: toInput(order.average_buy_price),
    maxSlippage: toInput(order.max_allowed_slippage_percent) || '1',
    firstTarget: toInput(firstLeg?.targetPrice ?? order.profit_target_price),
    firstPercent: toInput(firstLeg?.sellPercent) || String(config.target1_sell_pct || '30'),
    secondTarget: toInput(secondLeg?.targetPrice),
    secondPercent: toInput(secondLeg?.sellPercent) || String(config.target2_sell_pct || '30'),
    expiryTime: isoToNepalDateTimeLocal(order.expiry_time),
    expiryAction: order.expiry_action || 'Cancel strategy',
    minBuyScore: String(config.min_buy_score || '65'),
    wrappedStrategyType: String(config.wrapped_strategy_type || 'Quality Pullback Recovery Buy'),
    requireFreshTrade: Boolean(config.require_fresh_trade),
    requireVolumeIncrease: Boolean(config.require_volume_increase),
    allowMarketDepthFilter: config.allow_market_depth_filter !== false,
    breakEvenTriggerPct: String(config.break_even_trigger_pct || '3'),
    allowSplitEmergencyExit: Boolean(config.allow_split_emergency_exit),
    emergencyExecution: Boolean(order.emergency_execution),
    emergencyConfirmed: Boolean(order.emergency_execution),
  };
};

const EditScheduledOrderModal: React.FC<Props> = ({ orderId, apiUrl, onClose, onSaved }) => {
  const [order, setOrder] = useState<ScheduledOrderDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [submitError, setSubmitError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [latestLtp, setLatestLtp] = useState<number | null>(null);
  const [holdingQty, setHoldingQty] = useState<number | null>(null);

  useEffect(() => {
    const loadOrder = async () => {
      setLoading(true);
      setError('');
      try {
        const response = await fetch(`${apiUrl}/scheduled_orders/${orderId}`, {
          headers: { Accept: 'application/json' },
        });
        const data = await response.json();
        if (!response.ok) {
          throw new Error(data.detail || 'Failed to load scheduled order');
        }
        const loaded = data.order as ScheduledOrderDetail;
        if (loaded.editable === false) {
          throw new Error(`Order status "${loaded.status}" cannot be edited`);
        }
        setOrder(loaded);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load scheduled order');
      } finally {
        setLoading(false);
      }
    };
    void loadOrder();
  }, [apiUrl, orderId]);

  useEffect(() => {
    if (!order?.client_id || !order.script_name) {
      return;
    }
    const loadContext = async () => {
      try {
        const quoteParams = new URLSearchParams({
          client_id: order.client_id,
          symbol: order.script_name,
        });
        const quoteResponse = await fetch(`${apiUrl}/stock_quote?${quoteParams.toString()}`, {
          headers: { Accept: 'application/json' },
        });
        if (quoteResponse.ok) {
          const quoteData = await quoteResponse.json();
          const ltp = Number(quoteData?.quote?.ltp ?? 0);
          if (ltp > 0) {
            setLatestLtp(ltp);
          }
        }

        if ((order.order_type || order.side || '').toLowerCase() === 'sell') {
          const holdingsResponse = await fetch(`${apiUrl}/dp_holdings?client_id=${encodeURIComponent(order.client_id)}`, {
            headers: { Accept: 'application/json' },
          });
          if (holdingsResponse.ok) {
            const holdings = await holdingsResponse.json();
            const symbol = order.script_name.trim().toUpperCase();
            const match = (holdings || []).find((holding: { scrip?: string; symbolName?: string; currentBalance?: number }) => {
              const scrip = String(holding.scrip || '').trim().toUpperCase();
              const name = String(holding.symbolName || '').trim().toUpperCase();
              return scrip === symbol || name === symbol;
            });
            if (match?.currentBalance) {
              setHoldingQty(Number(match.currentBalance));
            }
          }
        }
      } catch {
        // quote/holdings are optional for edit
      }
    };
    void loadContext();
  }, [apiUrl, order]);

  const prefill = useMemo(() => (order ? buildPrefill(order) : null), [order]);
  const side = ((order?.order_type || order?.side || 'buy') as string).toLowerCase() === 'sell' ? 'sell' : 'buy';

  const submitUpdate = useCallback(async (strategyPayload: StrategyPayload) => {
    if (!order) {
      return;
    }
    setIsSubmitting(true);
    setSubmitError('');
    try {
      const response = await fetch(`${apiUrl}/scheduled_orders/${order.order_id}`, {
        method: 'PUT',
        headers: {
          Accept: 'application/json',
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          client_id: order.client_id,
          script_name: order.script_name,
          order_type: side,
          security_details: order.security_details || {},
          ...strategyPayload,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.detail || data.message || 'Failed to update scheduled order');
      }
      onSaved();
      onClose();
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : 'Failed to update scheduled order');
    } finally {
      setIsSubmitting(false);
    }
  }, [apiUrl, onClose, onSaved, order, side]);

  return (
    <div className="edit-scheduled-order-backdrop" role="presentation" onClick={onClose}>
      <div
        className="edit-scheduled-order-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="edit-scheduled-order-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="edit-scheduled-order-header">
          <div>
            <h3 id="edit-scheduled-order-title">Edit Scheduled Order</h3>
            {order && (
              <p>
                {order.script_name} · {order.client_id} · #{order.order_id}
              </p>
            )}
          </div>
          <button type="button" className="edit-scheduled-order-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>

        {loading && <p className="edit-scheduled-order-status">Loading order…</p>}
        {error && <ErrorMessage message={error} variant="error" persistent />}
        {submitError && <ErrorMessage message={submitError} variant="error" persistent />}

        {!loading && !error && order && prefill && (
          <StrategySellForm
            key={order.order_id}
            scriptName={order.script_name}
            side={side}
            currentLtp={latestLtp}
            availableQty={side === 'sell' ? holdingQty : null}
            averageBuyPrice={order.average_buy_price ?? null}
            initialQty={prefill.qty}
            initialPrice={prefill.price}
            securityDetails={order.security_details || null}
            isSubmitting={isSubmitting}
            submitError={submitError}
            prefill={prefill}
            submitButtonLabel="Save Changes"
            onSubmit={submitUpdate}
          />
        )}
      </div>
    </div>
  );
};

export default EditScheduledOrderModal;
