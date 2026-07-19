import React, { useEffect, useRef, useState } from 'react';
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type SeriesMarker,
  type Time,
} from 'lightweight-charts';
import './TradeLightweightChart.css';

export type TradeChartCandle = {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

export type TradeChartTrade = Record<string, unknown>;

type TradeLightweightChartProps = {
  symbol: string;
  candles: TradeChartCandle[];
  trades?: TradeChartTrade[];
  loading?: boolean;
  error?: string;
  emptyMessage?: string;
  className?: string;
  loadingMessage?: string;
};

const toChartTime = (value: string): string => String(value || '').slice(0, 10);

const timeKey = (value: Time): string => {
  if (typeof value === 'string') return value.slice(0, 10);
  if (typeof value === 'number') return new Date(value * 1000).toISOString().slice(0, 10);
  return `${value.year}-${String(value.month).padStart(2, '0')}-${String(value.day).padStart(2, '0')}`;
};

const snapToCandleTime = (dates: string[], value: string): string | null => {
  const target = toChartTime(value);
  if (!target || !dates.length) return null;
  if (dates.includes(target)) return target;
  let best: string | null = null;
  for (const date of dates) {
    if (date <= target) best = date;
    else break;
  }
  return best ?? dates[0];
};

const EMPTY_TRADES: TradeChartTrade[] = [];

const formatVolume = (value: number): string => {
  const volume = Number(value) || 0;
  if (volume >= 1_000_000) return `${(volume / 1_000_000).toFixed(2)}M`;
  if (volume >= 1_000) return `${(volume / 1_000).toFixed(1)}K`;
  return volume.toLocaleString();
};

const TradeLightweightChart: React.FC<TradeLightweightChartProps> = ({
  symbol,
  candles,
  trades = EMPTY_TRADES,
  loading = false,
  error = '',
  emptyMessage = 'No cached OHLCV candles are available for this symbol.',
  className = '',
  loadingMessage = 'Loading daily price history…',
}) => {
  const ref = useRef<HTMLDivElement | null>(null);
  const shellRef = useRef<HTMLDivElement | null>(null);
  const bandRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const rangeDragRef = useRef<{ startX: number; pointerId: number } | null>(null);
  const [activeCandleIndex, setActiveCandleIndex] = useState<number | null>(null);
  const zoomModifierLabel = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent) ? '⌘+drag' : 'Ctrl+drag';

  useEffect(() => {
    setActiveCandleIndex(null);
  }, [symbol, candles]);

  useEffect(() => {
    if (!ref.current || !candles.length) return undefined;
    const el = ref.current;
    const shell = shellRef.current;
    const dates = candles.map((bar) => toChartTime(bar.date)).filter(Boolean);
    const indexByDate = new Map(dates.map((date, index) => [date, index]));
    const candleData = candles.map((bar) => ({
      time: toChartTime(bar.date) as Time,
      open: Number(bar.open),
      high: Number(bar.high),
      low: Number(bar.low),
      close: Number(bar.close),
    }));
    const volumeData = candles.map((bar) => ({
      time: toChartTime(bar.date) as Time,
      value: Number(bar.volume || 0),
      color: Number(bar.close) >= Number(bar.open) ? 'rgba(33,166,111,.55)' : 'rgba(224,82,82,.55)',
    }));
    const npr = (value: number) => `${value >= 0 ? '+' : '−'}NPR ${Math.abs(value).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
    const markers: SeriesMarker<Time>[] = [];
    trades.forEach((trade) => {
      const entry = snapToCandleTime(dates, String(trade.entry_date || ''));
      const exit = snapToCandleTime(dates, String(trade.exit_date || ''));
      if (entry) markers.push({ time: entry as Time, position: 'belowBar', color: '#42d392', shape: 'arrowUp', text: 'BUY' });
      if (exit) {
        const pnl = Number(trade.pnl || 0);
        markers.push({ time: exit as Time, position: 'aboveBar', color: pnl >= 0 ? '#34d399' : '#ff5e66', shape: 'arrowDown', text: npr(pnl) });
      }
    });
    markers.sort((a, b) => timeKey(a.time).localeCompare(timeKey(b.time)));

    const chart = createChart(el, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: '#131722' },
        textColor: '#a7b0c0',
        fontSize: 11,
        attributionLogo: true,
      },
      grid: {
        vertLines: { color: '#1e2330' },
        horzLines: { color: '#1e2330' },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: '#8493a8', width: 1, style: LineStyle.Dashed, labelBackgroundColor: '#2962ff' },
        horzLine: { color: '#8493a8', width: 1, style: LineStyle.Dashed, labelBackgroundColor: '#2962ff' },
      },
      rightPriceScale: { borderColor: '#2a2e39', scaleMargins: { top: 0.08, bottom: 0.08 } },
      timeScale: {
        borderColor: '#2a2e39',
        rightOffset: 6,
        barSpacing: 7,
        minBarSpacing: 2,
        timeVisible: false,
      },
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: true },
      handleScale: { axisPressedMouseMove: { time: true, price: true }, mouseWheel: true, pinch: true },
    });
    chartRef.current = chart;

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#20b27a',
      downColor: '#e45454',
      borderUpColor: '#20b27a',
      borderDownColor: '#e45454',
      wickUpColor: '#20b27a',
      wickDownColor: '#e45454',
    });
    candleSeries.setData(candleData);
    if (markers.length) createSeriesMarkers(candleSeries, markers);

    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    }, 1);
    volumeSeries.setData(volumeData);
    chart.priceScale('volume').applyOptions({
      borderColor: '#2a2e39',
      scaleMargins: { top: 0.15, bottom: 0 },
    });
    const panes = chart.panes();
    if (panes[0]) panes[0].setStretchFactor(3.2);
    if (panes[1]) panes[1].setStretchFactor(1);

    const showRecent = () => {
      const from = Math.max(0, candleData.length - 260);
      chart.timeScale().setVisibleLogicalRange({ from: from - 0.5, to: candleData.length - 0.5 });
    };
    showRecent();

    const setScrollEnabled = (enabled: boolean) => {
      chart.applyOptions({
        handleScroll: { mouseWheel: true, pressedMouseMove: enabled, horzTouchDrag: enabled, vertTouchDrag: enabled },
      });
    };
    const setRangeBand = (left: number | null, width = 0) => {
      const band = bandRef.current;
      if (!band) return;
      if (left == null) {
        band.hidden = true;
        band.style.width = '0px';
        return;
      }
      band.hidden = false;
      band.style.left = `${left}px`;
      band.style.width = `${Math.max(0, width)}px`;
    };
    const clearRangeDrag = () => {
      rangeDragRef.current = null;
      setRangeBand(null);
      el.classList.remove('range-selecting');
      setScrollEnabled(true);
    };
    const syncModifierArm = (armed: boolean) => {
      shell?.classList.toggle('range-zoom-armed', armed);
      el.classList.toggle('range-zoom-armed', armed);
      if (!rangeDragRef.current) setScrollEnabled(!armed);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Meta' || event.key === 'Control') syncModifierArm(true);
    };
    const onKeyUp = (event: KeyboardEvent) => {
      if (event.key === 'Meta' || event.key === 'Control') {
        if (rangeDragRef.current) return;
        syncModifierArm(false);
      }
    };
    const onBlur = () => { clearRangeDrag(); syncModifierArm(false); };
    const onPointerDown = (event: PointerEvent) => {
      if (event.button !== 0 || !(event.metaKey || event.ctrlKey)) return;
      event.preventDefault();
      event.stopPropagation();
      rangeDragRef.current = { startX: event.clientX, pointerId: event.pointerId };
      setScrollEnabled(false);
      el.classList.add('range-selecting');
      const localX = event.clientX - el.getBoundingClientRect().left;
      setRangeBand(localX, 0);
      el.setPointerCapture(event.pointerId);
    };
    const onPointerMove = (event: PointerEvent) => {
      const drag = rangeDragRef.current;
      if (!drag || drag.pointerId !== event.pointerId) return;
      const rect = el.getBoundingClientRect();
      const startLocal = drag.startX - rect.left;
      const currentLocal = event.clientX - rect.left;
      setRangeBand(Math.min(startLocal, currentLocal), Math.abs(currentLocal - startLocal));
    };
    const onPointerUp = (event: PointerEvent) => {
      const drag = rangeDragRef.current;
      if (!drag || drag.pointerId !== event.pointerId) return;
      const startX = drag.startX;
      const endX = event.clientX;
      clearRangeDrag();
      syncModifierArm(event.metaKey || event.ctrlKey);
      if (Math.abs(endX - startX) < 8) return;
      const rect = el.getBoundingClientRect();
      const fromTime = chart.timeScale().coordinateToTime(startX - rect.left);
      const toTime = chart.timeScale().coordinateToTime(endX - rect.left);
      if (fromTime == null || toTime == null) return;
      const a = timeKey(fromTime);
      const b = timeKey(toTime);
      const from = a <= b ? a : b;
      const to = a <= b ? b : a;
      if (from === to) return;
      chart.timeScale().setVisibleRange({ from: from as Time, to: to as Time });
    };
    const onCrosshair = (param: { time?: Time }) => {
      if (param.time == null) return;
      const nextIndex = indexByDate.get(timeKey(param.time));
      if (nextIndex != null) setActiveCandleIndex(nextIndex);
    };

    chart.subscribeCrosshairMove(onCrosshair);
    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('keyup', onKeyUp);
    window.addEventListener('blur', onBlur);
    el.addEventListener('pointerdown', onPointerDown, true);
    el.addEventListener('pointermove', onPointerMove);
    el.addEventListener('pointerup', onPointerUp);
    el.addEventListener('pointercancel', onPointerUp);

    return () => {
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('keyup', onKeyUp);
      window.removeEventListener('blur', onBlur);
      el.removeEventListener('pointerdown', onPointerDown, true);
      el.removeEventListener('pointermove', onPointerMove);
      el.removeEventListener('pointerup', onPointerUp);
      el.removeEventListener('pointercancel', onPointerUp);
      chart.unsubscribeCrosshairMove(onCrosshair);
      chart.remove();
      chartRef.current = null;
    };
  }, [candles, symbol, trades]);

  if (error) return <div className="trade-chart-alert">{error}</div>;
  if (loading) return <div className="trade-chart-loading">{loadingMessage}</div>;
  if (!candles.length) return <div className="trade-chart-alert">{emptyMessage}</div>;

  const resetView = () => {
    if (!chartRef.current || !candles.length) return;
    const from = Math.max(0, candles.length - 260);
    chartRef.current.timeScale().setVisibleLogicalRange({ from: from - 0.5, to: candles.length - 0.5 });
  };
  const activeCandle = candles[activeCandleIndex ?? candles.length - 1];
  const price = (value: number) => Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const rising = Number(activeCandle.close) >= Number(activeCandle.open);

  return (
    <div className={`trade-lwc-chart ${className}`.trim()}>
      <div className="trade-chart-toolbar">
        <span className="trade-chart-symbol"><i />{symbol} <small>1D</small></span>
        <span className={`trade-chart-ohlc ${rising ? 'up' : 'down'}`} aria-live="polite">
          <span>O <b>{price(activeCandle.open)}</b></span>
          <span>H <b>{price(activeCandle.high)}</b></span>
          <span>L <b>{price(activeCandle.low)}</b></span>
          <span>C <b>{price(activeCandle.close)}</b></span>
          <span className="trade-chart-vol">Vol <b>{formatVolume(Number(activeCandle.volume || 0))}</b></span>
        </span>
        <span className="trade-chart-gesture">{zoomModifierLabel} to zoom · Drag to pan · Scroll to zoom</span>
        <a className="trade-chart-tv" href="https://www.tradingview.com/" target="_blank" rel="noreferrer">TradingView</a>
        <button type="button" onClick={resetView}>Reset view</button>
      </div>
      <div className="trade-chart-shell" ref={shellRef}>
        <div
          ref={ref}
          className="trade-chart-canvas"
          aria-label={`${symbol} candlestick chart. ${zoomModifierLabel} selects a range to zoom, drag to pan, and use the mouse wheel to zoom.`}
        />
        <div ref={bandRef} className="trade-chart-range-band" hidden aria-hidden="true" />
      </div>
    </div>
  );
};

export default TradeLightweightChart;
