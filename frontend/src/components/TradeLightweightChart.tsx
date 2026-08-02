import React, { useEffect, useRef, useState } from 'react';
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
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
export type TradeChartSignal = {
  date: string;
  side: 'buy' | 'sell';
  label?: string;
  status?: string;
};
export type TradeChartProjection = {
  points: Array<{ date: string; value: number }>;
  target_date: string;
  target_price: number;
  label: string;
  holding_sessions?: number;
  calendar_days?: number;
  disclaimer?: string;
};
export type TradeChartZone = {
  kind: 'support' | 'resistance';
  lower: number;
  upper: number;
  center: number;
  confidence: number;
  touches: number;
  label: string;
  start_date?: string;
  end_date?: string;
};
export type TradeChartZoneSnapshot = { date: string; zones: TradeChartZone[] };
export type TradeChartRiskLevel = {
  kind: 'buy_entry' | 'stop' | 'trailing_stop' | 'sell_target';
  value: number;
  range_low?: number | null;
  range_high?: number | null;
  label: string;
  start_date: string;
  end_date: string;
};

type TradeLightweightChartProps = {
  symbol: string;
  candles: TradeChartCandle[];
  trades?: TradeChartTrade[];
  signals?: TradeChartSignal[];
  projection?: TradeChartProjection | null;
  zones?: TradeChartZone[];
  zoneHistory?: TradeChartZoneSnapshot[];
  showZones?: boolean;
  riskLevels?: TradeChartRiskLevel[];
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
const EMPTY_SIGNALS: TradeChartSignal[] = [];

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
  signals = EMPTY_SIGNALS,
  projection = null,
  zones = [],
  zoneHistory = [],
  showZones = false,
  riskLevels = [],
  loading = false,
  error = '',
  emptyMessage = 'No cached OHLCV candles are available for this symbol.',
  className = '',
  loadingMessage = 'Loading daily price history…',
}) => {
  const ref = useRef<HTMLDivElement | null>(null);
  const shellRef = useRef<HTMLDivElement | null>(null);
  const bandRef = useRef<HTMLDivElement | null>(null);
  const measureLineRef = useRef<HTMLDivElement | null>(null);
  const measureLabelRef = useRef<HTMLSpanElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const rangeDragRef = useRef<{ startX: number; pointerId: number } | null>(null);
  const measureDragRef = useRef<{
    startX: number;
    startY: number;
    startIndex: number;
    startPrice: number;
    pointerId: number;
    mode: 'horizontal' | 'vertical' | null;
  } | null>(null);
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
    const percentReturn = (value: number) => `${value >= 0 ? '+' : '−'}${Math.abs(value).toFixed(2)}%`;
    const measurePrice = (value: number) => value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const markers: SeriesMarker<Time>[] = [];
    trades.forEach((trade) => {
      const entry = snapToCandleTime(dates, String(trade.entry_date || ''));
      const exit = snapToCandleTime(dates, String(trade.exit_date || ''));
      const entryPrice = Number(trade.entry_price);
      const exitPrice = Number(trade.exit_price);
      if (entry) markers.push({
        time: entry as Time,
        position: 'belowBar',
        color: '#42d392',
        shape: 'arrowUp',
        text: Number.isFinite(entryPrice) && entryPrice > 0 ? `BUY · NPR ${measurePrice(entryPrice)}` : 'BUY',
      });
      if (exit) {
        // return_pct is net P/L divided by invested entry cost. The backend
        // calculates it after commissions, SEBON, DP, CGT, and slippage.
        const netReturnPct = Number(trade.return_pct ?? trade.net_return_pct ?? 0);
        markers.push({
          time: exit as Time,
          position: 'aboveBar',
          color: netReturnPct >= 0 ? '#34d399' : '#ff5e66',
          shape: 'arrowDown',
          text: Number.isFinite(exitPrice) && exitPrice > 0
            ? `SELL · NPR ${measurePrice(exitPrice)} · ${percentReturn(netReturnPct)} NET`
            : `SELL · ${percentReturn(netReturnPct)} NET`,
        });
      }
    });
    signals.forEach((signal) => {
      const signalTime = snapToCandleTime(dates, signal.date);
      if (!signalTime) return;
      const isBuy = signal.side === 'buy';
      markers.push({
        time: signalTime as Time,
        position: isBuy ? 'belowBar' : 'aboveBar',
        color: signal.status === 'strong_buy' ? '#fbbf24' : isBuy ? '#38bdf8' : '#fb7185',
        shape: isBuy ? 'arrowUp' : 'arrowDown',
        text: signal.label || (isBuy ? 'BUY NOW' : 'SELL NOW'),
      });
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
    if (projection?.points?.length) {
      const projectionSeries = chart.addSeries(LineSeries, {
        color: '#fbbf24',
        lineWidth: 2,
        lineStyle: LineStyle.Dashed,
        title: 'Anticipated sell scenario',
        lastValueVisible: true,
        priceLineVisible: false,
      });
      projectionSeries.setData(projection.points.map((point) => ({
        time: toChartTime(point.date) as Time,
        value: Number(point.value),
      })));
      createSeriesMarkers(projectionSeries, [{
        time: toChartTime(projection.target_date) as Time,
        position: 'aboveBar',
        color: '#fb7185',
        shape: 'arrowDown',
        text: projection.label || 'ANTICIPATED SELL',
      }]);
    }

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

    const zoneLayer = document.createElement('div');
    zoneLayer.className = 'trade-chart-zone-layer';
    shell?.appendChild(zoneLayer);
    const syncZones = () => {
      zoneLayer.replaceChildren();
      if (!showZones) return;
      const range = chart.timeScale().getVisibleLogicalRange();
      const startIndex = Math.max(0, Math.min(
        candles.length - 1,
        Math.ceil(range?.from ?? 0),
      ));
      const endIndex = Math.max(0, Math.min(
        candles.length - 1,
        Math.floor(range?.to ?? candles.length - 1),
      ));
      let snapshot: TradeChartZoneSnapshot | undefined;
      for (let index = endIndex; index >= Math.max(startIndex, endIndex - 20); index -= 1) {
        if (zoneHistory[index]?.zones?.length) {
          snapshot = zoneHistory[index];
          break;
        }
      }
      const candidates = snapshot?.zones?.length
        ? snapshot.zones
        : endIndex === candles.length - 1 ? zones : [];
      const rank = (zone: TradeChartZone) => zone.confidence + zone.touches * 4;
      const activeZones = (['support', 'resistance'] as const).flatMap((kind) => {
        const prominent = candidates
          .filter((zone) => zone.kind === kind)
          .sort((a, b) => rank(b) - rank(a))[0];
        return prominent ? [prominent] : [];
      });
      activeZones.forEach((zone) => {
        const upper = candleSeries.priceToCoordinate(Number(zone.upper));
        const lower = candleSeries.priceToCoordinate(Number(zone.lower));
        if (upper == null || lower == null) return;
        const band = document.createElement('div');
        band.className = `trade-chart-zone-band ${zone.kind}`;
        band.setAttribute('aria-hidden', 'true');
        const label = document.createElement('span');
        label.textContent = zone.label;
        band.appendChild(label);
        zoneLayer.appendChild(band);
        const startCoordinate = zone.start_date
          ? chart.timeScale().timeToCoordinate(toChartTime(zone.start_date) as Time)
          : 0;
        const endCoordinate = zone.end_date
          ? chart.timeScale().timeToCoordinate(toChartTime(zone.end_date) as Time)
          : el.clientWidth - 64;
        const plotWidth = el.clientWidth - 64;
        const rawLeft = startCoordinate ?? 0;
        const rawRight = endCoordinate ?? plotWidth;
        if (rawRight < 0 || rawLeft > plotWidth) return;
        const left = Math.max(0, rawLeft);
        const right = Math.min(plotWidth, rawRight);
        band.style.left = `${left}px`;
        band.style.width = `${Math.max(20, right - left)}px`;
        band.style.right = 'auto';
        band.style.top = `${Math.min(upper, lower)}px`;
        band.style.height = `${Math.max(2, Math.min(10, Math.abs(lower - upper)))}px`;
      });
    };
    const riskLayer = document.createElement('div');
    riskLayer.className = 'trade-chart-risk-layer';
    shell?.appendChild(riskLayer);
    const syncRiskLevels = () => {
      riskLayer.replaceChildren();
      const plotWidth = el.clientWidth - 64;
      riskLevels.forEach((level) => {
        const y = candleSeries.priceToCoordinate(Number(level.value));
        if (y == null) return;
        const rangeTop = level.range_high == null
          ? null : candleSeries.priceToCoordinate(Number(level.range_high));
        const rangeBottom = level.range_low == null
          ? null : candleSeries.priceToCoordinate(Number(level.range_low));
        const start = chart.timeScale().timeToCoordinate(toChartTime(level.start_date) as Time);
        const end = chart.timeScale().timeToCoordinate(toChartTime(level.end_date) as Time);
        if (start == null) return;
        const rawEnd = end ?? start + 110;
        if (rawEnd < 0 || start > plotWidth) return;
        const line = document.createElement('div');
        line.className = `trade-chart-risk-segment ${level.kind}`;
        if (rangeTop != null && rangeBottom != null) {
          line.classList.add('has-range');
          line.style.top = `${Math.min(rangeTop, rangeBottom)}px`;
          line.style.height = `${Math.max(3, Math.abs(rangeBottom - rangeTop))}px`;
        } else {
          line.style.top = `${y}px`;
        }
        const left = Math.max(0, start);
        const availableWidth = Math.max(20, plotWidth - left);
        const requestedWidth = Math.max(70, Math.min(plotWidth, rawEnd) - left);
        line.style.left = `${left}px`;
        line.style.width = `${Math.min(availableWidth, requestedWidth)}px`;
        const label = document.createElement('span');
        label.textContent = level.label;
        line.appendChild(label);
        riskLayer.appendChild(line);
      });
    };
    chart.timeScale().subscribeVisibleLogicalRangeChange(syncZones);
    chart.timeScale().subscribeVisibleLogicalRangeChange(syncRiskLevels);
    window.addEventListener('resize', syncZones);
    window.addEventListener('resize', syncRiskLevels);

    const showRecent = () => {
      const from = Math.max(0, candleData.length - 260);
      chart.timeScale().setVisibleLogicalRange({ from: from - 0.5, to: candleData.length - 0.5 });
    };
    showRecent();
    window.requestAnimationFrame(syncZones);
    window.requestAnimationFrame(syncRiskLevels);

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
    const candleIndexAtCoordinate = (x: number): number | null => {
      const logical = chart.timeScale().coordinateToLogical(x);
      if (logical == null) return null;
      return Math.max(0, Math.min(candles.length - 1, Math.round(Number(logical))));
    };
    const setMeasurement = (
      startX: number,
      startY: number,
      endX: number,
      endY: number,
      startIndex: number,
      startPrice: number,
      mode: 'horizontal' | 'vertical',
    ) => {
      const line = measureLineRef.current;
      const label = measureLabelRef.current;
      if (!line || !label) return;
      if (mode === 'vertical') {
        const endPrice = Number(candleSeries.coordinateToPrice(endY));
        if (!Number.isFinite(endPrice) || endPrice <= 0 || startPrice <= 0) return;
        const change = (endPrice / startPrice - 1) * 100;
        const distance = Math.abs(endY - startY);
        line.hidden = false;
        line.style.left = `${startX}px`;
        line.style.top = `${startY}px`;
        line.style.width = `${distance}px`;
        line.style.transform = `rotate(${endY >= startY ? 90 : -90}deg)`;
        line.classList.toggle('positive', change >= 0);
        label.hidden = false;
        label.textContent = `Price · NPR ${measurePrice(startPrice)} → NPR ${measurePrice(endPrice)} · ${change >= 0 ? '+' : '−'}${Math.abs(change).toFixed(2)}%`;
        label.classList.toggle('positive', change >= 0);
        label.style.left = `${Math.max(8, Math.min(el.clientWidth - 220, startX + 12))}px`;
        label.style.top = `${Math.max(8, Math.min(el.clientHeight - 34, (startY + endY) / 2 - 14))}px`;
        return;
      }
      const endIndex = candleIndexAtCoordinate(endX);
      if (endIndex == null) return;
      const distance = Math.abs(endX - startX);
      const buyIndex = Math.min(startIndex, endIndex);
      const sellIndex = Math.max(startIndex, endIndex);
      const buyDate = toChartTime(candles[buyIndex]?.date);
      const sellDate = toChartTime(candles[sellIndex]?.date);
      const strategyTrade = trades.find((trade) => (
        snapToCandleTime(dates, String(trade.entry_date || '')) === buyDate
        && snapToCandleTime(dates, String(trade.exit_date || '')) === sellDate
      ));
      const persistedBuyPrice = Number(strategyTrade?.entry_price);
      const persistedSellPrice = Number(strategyTrade?.exit_price);
      const hasPersistedPrices = (
        Number.isFinite(persistedBuyPrice) && persistedBuyPrice > 0
        && Number.isFinite(persistedSellPrice) && persistedSellPrice > 0
      );
      const buyPrice = hasPersistedPrices ? persistedBuyPrice : Number(candles[buyIndex]?.close || 0);
      const sellPrice = hasPersistedPrices ? persistedSellPrice : Number(candles[sellIndex]?.close || 0);
      const persistedReturn = Number(strategyTrade?.return_pct ?? strategyTrade?.net_return_pct);
      const change = strategyTrade && Number.isFinite(persistedReturn)
        ? persistedReturn
        : buyPrice !== 0 ? (sellPrice / buyPrice - 1) * 100 : 0;
      const sessions = sellIndex - buyIndex;
      const startDate = Date.parse(`${toChartTime(candles[buyIndex]?.date)}T00:00:00Z`);
      const endDate = Date.parse(`${toChartTime(candles[sellIndex]?.date)}T00:00:00Z`);
      const calendarDays = Number.isFinite(startDate) && Number.isFinite(endDate)
        ? Math.round(Math.abs(endDate - startDate) / 86_400_000)
        : sessions;
      line.hidden = false;
      line.style.left = `${startX}px`;
      line.style.top = `${startY}px`;
      line.style.width = `${distance}px`;
      line.style.transform = `rotate(${endX >= startX ? 0 : 180}deg)`;
      line.classList.toggle('positive', change >= 0);
      label.hidden = false;
      label.textContent = strategyTrade
        ? `Strategy trade · Buy NPR ${measurePrice(buyPrice)} → Sell NPR ${measurePrice(sellPrice)} · ${change >= 0 ? '+' : '−'}${Math.abs(change).toFixed(2)}% net · ${sessions} session${sessions === 1 ? '' : 's'} · ${calendarDays} day${calendarDays === 1 ? '' : 's'}`
        : `${sessions} session${sessions === 1 ? '' : 's'} · ${calendarDays} day${calendarDays === 1 ? '' : 's'} · Close NPR ${measurePrice(buyPrice)} → NPR ${measurePrice(sellPrice)} · ${change >= 0 ? '+' : '−'}${Math.abs(change).toFixed(2)}%`;
      label.classList.toggle('positive', change >= 0);
      label.style.left = `${Math.max(8, Math.min(el.clientWidth - 220, (startX + endX) / 2 - 90))}px`;
      label.style.top = `${Math.max(8, Math.min(el.clientHeight - 34, startY - 30))}px`;
    };
    const syncModifierArm = (armed: boolean) => {
      shell?.classList.toggle('range-zoom-armed', armed);
      el.classList.toggle('range-zoom-armed', armed);
      if (!rangeDragRef.current) setScrollEnabled(!armed);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Meta' || event.key === 'Control') syncModifierArm(true);
      if (event.key === 'Shift') shell?.classList.add('measure-armed');
      if (event.key === 'Escape') {
        if (measureLineRef.current) measureLineRef.current.hidden = true;
        if (measureLabelRef.current) measureLabelRef.current.hidden = true;
      }
    };
    const onKeyUp = (event: KeyboardEvent) => {
      if (event.key === 'Meta' || event.key === 'Control') {
        if (rangeDragRef.current) return;
        syncModifierArm(false);
      }
      if (event.key === 'Shift' && !measureDragRef.current) shell?.classList.remove('measure-armed');
    };
    const onBlur = () => {
      clearRangeDrag();
      measureDragRef.current = null;
      shell?.classList.remove('measure-armed', 'measuring');
      syncModifierArm(false);
    };
    const onPointerDown = (event: PointerEvent) => {
      if (event.button !== 0) return;
      if (event.shiftKey) {
        const rect = el.getBoundingClientRect();
        const startX = event.clientX - rect.left;
        const startY = event.clientY - rect.top;
        const startIndex = candleIndexAtCoordinate(startX);
        const startPrice = Number(candleSeries.coordinateToPrice(startY));
        if (startIndex == null || !Number.isFinite(startPrice) || startPrice <= 0) return;
        event.preventDefault();
        event.stopPropagation();
        measureDragRef.current = {
          startX,
          startY,
          startIndex,
          startPrice,
          pointerId: event.pointerId,
          mode: null,
        };
        setScrollEnabled(false);
        shell?.classList.add('measuring');
        if (measureLineRef.current) measureLineRef.current.hidden = true;
        if (measureLabelRef.current) measureLabelRef.current.hidden = true;
        el.setPointerCapture(event.pointerId);
        return;
      }
      if (!(event.metaKey || event.ctrlKey)) return;
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
      const measurement = measureDragRef.current;
      if (measurement && measurement.pointerId === event.pointerId) {
        event.preventDefault();
        const rect = el.getBoundingClientRect();
        const endX = event.clientX - rect.left;
        const endY = event.clientY - rect.top;
        const deltaX = endX - measurement.startX;
        const deltaY = endY - measurement.startY;
        if (!measurement.mode && Math.hypot(deltaX, deltaY) >= 6) {
          measurement.mode = Math.abs(deltaY) > Math.abs(deltaX) ? 'vertical' : 'horizontal';
        }
        if (!measurement.mode) return;
        setMeasurement(
          measurement.startX,
          measurement.startY,
          endX,
          endY,
          measurement.startIndex,
          measurement.startPrice,
          measurement.mode,
        );
        return;
      }
      const drag = rangeDragRef.current;
      if (!drag || drag.pointerId !== event.pointerId) return;
      const rect = el.getBoundingClientRect();
      const startLocal = drag.startX - rect.left;
      const currentLocal = event.clientX - rect.left;
      setRangeBand(Math.min(startLocal, currentLocal), Math.abs(currentLocal - startLocal));
    };
    const onPointerUp = (event: PointerEvent) => {
      const measurement = measureDragRef.current;
      if (measurement && measurement.pointerId === event.pointerId) {
        const rect = el.getBoundingClientRect();
        const endX = event.clientX - rect.left;
        const endY = event.clientY - rect.top;
        const deltaX = endX - measurement.startX;
        const deltaY = endY - measurement.startY;
        const distance = Math.hypot(deltaX, deltaY);
        const mode = measurement.mode || (
          distance >= 6 ? (Math.abs(deltaY) > Math.abs(deltaX) ? 'vertical' : 'horizontal') : null
        );
        if (mode) {
          setMeasurement(
            measurement.startX,
            measurement.startY,
            endX,
            endY,
            measurement.startIndex,
            measurement.startPrice,
            mode,
          );
        } else {
          if (measureLineRef.current) measureLineRef.current.hidden = true;
          if (measureLabelRef.current) measureLabelRef.current.hidden = true;
        }
        measureDragRef.current = null;
        shell?.classList.remove('measuring');
        if (!event.shiftKey) shell?.classList.remove('measure-armed');
        setScrollEnabled(true);
        return;
      }
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
    const onWheel = (event: WheelEvent) => {
      // Keep wheel zoom focused on the chart instead of bubbling to the page.
      event.stopPropagation();
    };

    chart.subscribeCrosshairMove(onCrosshair);
    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('keyup', onKeyUp);
    window.addEventListener('blur', onBlur);
    el.addEventListener('pointerdown', onPointerDown);
    el.addEventListener('pointermove', onPointerMove);
    el.addEventListener('pointerup', onPointerUp);
    el.addEventListener('pointercancel', onPointerUp);
    el.addEventListener('wheel', onWheel);

    return () => {
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('keyup', onKeyUp);
      window.removeEventListener('blur', onBlur);
      el.removeEventListener('pointerdown', onPointerDown);
      el.removeEventListener('pointermove', onPointerMove);
      el.removeEventListener('pointerup', onPointerUp);
      el.removeEventListener('pointercancel', onPointerUp);
      el.removeEventListener('wheel', onWheel);
      chart.unsubscribeCrosshairMove(onCrosshair);
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(syncZones);
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(syncRiskLevels);
      window.removeEventListener('resize', syncZones);
      window.removeEventListener('resize', syncRiskLevels);
      zoneLayer.remove();
      riskLayer.remove();
      chart.remove();
      chartRef.current = null;
    };
  }, [candles, projection, riskLevels, showZones, signals, symbol, trades, zoneHistory, zones]);

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
        <span className="trade-chart-gesture">Shift+drag: vertical % · horizontal days · {zoomModifierLabel} zoom · Drag pan · Scroll zoom</span>
        <a className="trade-chart-tv" href="https://www.tradingview.com/" target="_blank" rel="noreferrer">TradingView</a>
        <button type="button" onClick={resetView}>Reset view</button>
      </div>
      <div className="trade-chart-shell" ref={shellRef}>
        <div
          ref={ref}
          className="trade-chart-canvas"
          aria-label={`${symbol} candlestick chart. Shift and drag vertically measures price percentage change; Shift and drag horizontally measures trading sessions and calendar days. ${zoomModifierLabel} selects a range to zoom, drag pans, and the mouse wheel zooms.`}
        />
        <div ref={bandRef} className="trade-chart-range-band" hidden aria-hidden="true" />
        <div ref={measureLineRef} className="trade-chart-measure-line" hidden aria-hidden="true" />
        <span ref={measureLabelRef} className="trade-chart-measure-label" hidden aria-live="polite" />
      </div>
    </div>
  );
};

export default TradeLightweightChart;
