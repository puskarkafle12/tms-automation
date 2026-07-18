"""Vectorized, historical-safe signal compiler for the versioned preset catalog."""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

import numpy as np


def _numbers(rows: Sequence[Dict[str, Any]], field: str) -> np.ndarray:
    values = []
    for row in rows:
        try:
            values.append(float(row.get(field)))
        except (TypeError, ValueError):
            values.append(np.nan)
    return np.asarray(values, dtype=np.float64)


def _rolling_mean(values: np.ndarray, window: int) -> np.ndarray:
    result = np.full(len(values), np.nan)
    if len(values) < window:
        return result
    clean = np.nan_to_num(values, nan=0.0)
    counts = np.convolve(np.isfinite(values).astype(float), np.ones(window), mode="valid")
    sums = np.convolve(clean, np.ones(window), mode="valid")
    result[window - 1:] = np.divide(sums, counts, out=np.full_like(sums, np.nan), where=counts > 0)
    return result


def _change_percent(values: np.ndarray, scans_back: int) -> np.ndarray:
    result = np.full(len(values), np.nan)
    if scans_back <= 0 or len(values) <= scans_back:
        return result
    previous = values[:-scans_back]
    current = values[scans_back:]
    result[scans_back:] = np.divide(
        current - previous, previous,
        out=np.full_like(current, np.nan), where=np.isfinite(previous) & (previous != 0),
    ) * 100
    return result


def _text_is(rows: Sequence[Dict[str, Any]], field: str, expected: str) -> np.ndarray:
    return np.asarray([str(row.get(field) or "").strip().lower() == expected.lower() for row in rows], dtype=bool)


def compile_preset_signals(preset_id: str, rows: Sequence[Dict[str, Any]]) -> List[bool]:
    """Compile one catalog preset without reading any future row."""
    count = len(rows)
    close = _numbers(rows, "ltp")
    change = _numbers(rows, "change_percent")
    volume = _numbers(rows, "volume")
    rsi = _numbers(rows, "technical_rsi_14")
    range_position = _numbers(rows, "position_in_52_week_range_percent")
    adx = _numbers(rows, "technical_adx_14")
    plus_di = _numbers(rows, "technical_plus_di_14")
    minus_di = _numbers(rows, "technical_minus_di_14")
    volume_ratio = _numbers(rows, "technical_volume_ratio_20")
    hma = _numbers(rows, "technical_hma_20")
    ppo = _numbers(rows, "technical_ppo_12_26_9")
    ppo_histogram = _numbers(rows, "technical_ppo_histogram")
    aroon_up = _numbers(rows, "technical_aroon_up_14")
    aroon_oscillator = _numbers(rows, "technical_aroon_oscillator_14")
    vortex_positive = _numbers(rows, "technical_vortex_positive_14")
    vortex_negative = _numbers(rows, "technical_vortex_negative_14")
    squeeze_momentum = _numbers(rows, "technical_squeeze_momentum")
    cmf = _numbers(rows, "technical_cmf_20")
    keltner_middle = _numbers(rows, "technical_keltner_middle_20")
    keltner_upper = _numbers(rows, "technical_keltner_upper_20")
    choppiness = _numbers(rows, "technical_choppiness_14")
    atr_percent = _numbers(rows, "technical_atr_percent")
    historical_volatility = _numbers(rows, "technical_historical_volatility_20")
    roc = _numbers(rows, "technical_roc_12")
    ema_20 = _numbers(rows, "technical_ema_20_value")
    ema_50 = _numbers(rows, "technical_ema_50_value")
    ema_200 = _numbers(rows, "technical_ema_200_value")
    donchian_upper = _numbers(rows, "technical_donchian_upper_20")
    obv = _numbers(rows, "technical_obv")
    positive = change > 0
    signal = np.zeros(count, dtype=bool)

    if preset_id.startswith("rsi_recovery_"):
        signal = (rsi <= float(preset_id.rsplit("_", 1)[1])) & positive
    elif preset_id.startswith("rsi_momentum_"):
        lower = float(preset_id.rsplit("_", 1)[1])
        signal = (rsi >= lower) & (rsi <= 80) & positive
    elif preset_id.startswith("sma_trend_"):
        period = preset_id.rsplit("_", 1)[1]
        signal = _text_is(rows, f"technical_sma_{period}", "above") & _text_is(rows, "technical_macd", "bullish")
    elif preset_id.startswith("sma_pullback_"):
        period = preset_id.rsplit("_", 1)[1]
        signal = _text_is(rows, f"technical_sma_{period}", "below") & (rsi < 40) & positive
    elif preset_id.startswith("range_value_"):
        signal = (range_position <= float(preset_id.rsplit("_", 1)[1])) & positive
    elif preset_id.startswith("range_strength_"):
        signal = (range_position >= float(preset_id.rsplit("_", 1)[1])) & positive
    elif preset_id.startswith("volume_surge_"):
        ratios = (1.1, 1.25, 1.5, 2.0, 3.0)
        ratio = ratios[int(preset_id.rsplit("_", 1)[1]) - 1]
        signal = (volume > _rolling_mean(volume, 20) * ratio) & positive
    elif preset_id.startswith("volume_momentum_"):
        threshold = float(preset_id.removeprefix("volume_momentum_").replace("_", "."))
        signal = (volume > _rolling_mean(volume, 10)) & (change >= threshold)
    elif preset_id.startswith("consecutive_rises_") or preset_id.startswith("consecutive_drops_"):
        rises = preset_id.startswith("consecutive_rises_")
        streak = int(preset_id.rsplit("_", 1)[1])
        min_change = 1 if rises else 2
        for index in range(streak - 1, count):
            start = index - streak + 1
            prior = close[start - 1] if start > 0 else np.nan
            window = close[start:index + 1]
            comparisons = np.diff(np.concatenate(([prior], window))) if np.isfinite(prior) else np.diff(window)
            direction_ok = bool(np.all(comparisons > 0)) if rises else bool(np.all(comparisons < 0))
            baseline = prior if np.isfinite(prior) else window[0]
            total = abs((window[-1] / baseline - 1) * 100) if baseline else 0
            signal[index] = direction_ok and total >= min_change
    elif preset_id.startswith("average_breakout_"):
        period = int(preset_id.rsplit("_", 1)[1])
        average = _rolling_mean(close, period)
        signal[1:] = (close[1:] > average[1:]) & (close[:-1] <= average[:-1]) & (volume[1:] > 0)
    elif preset_id.startswith("slope_momentum_"):
        window = int(preset_id.rsplit("_", 1)[1])
        signal = positive.copy()
        signal[:window - 1] = False
        for index in range(window - 1, count):
            values = close[index - window + 1:index + 1]
            signal[index] = signal[index] and bool(np.isfinite(values).all() and np.polyfit(np.arange(window), values, 1)[0] > 0)
    elif preset_id == "balanced_recovery":
        signal = (rsi >= 30) & (rsi <= 50) & _text_is(rows, "technical_macd", "bullish") & positive
    elif preset_id == "trend_volume":
        signal = _text_is(rows, "technical_sma_20", "above") & (volume > _rolling_mean(volume, 20)) & positive
    elif preset_id == "deep_value_reversal":
        signal = (range_position <= 20) & (rsi <= 40) & positive
    elif preset_id == "quality_momentum":
        signal = _text_is(rows, "technical_sma_50", "above") & _text_is(rows, "technical_macd", "bullish") & (rsi >= 50) & (rsi <= 75)
    elif preset_id == "breakout_participation":
        signal = (range_position >= 80) & (volume > _rolling_mean(volume, 20) * 1.25)
    elif preset_id == "supertrend_adx_confirmation":
        signal = _text_is(rows, "technical_supertrend", "bullish") & (adx >= 20) & (plus_di > minus_di)
    elif preset_id == "supertrend_volume_momentum":
        signal = _text_is(rows, "technical_supertrend", "bullish") & (volume_ratio >= 1.2) & (rsi >= 50) & (rsi <= 72)
    elif preset_id == "hma_ppo_momentum":
        signal = (close > hma) & (ppo_histogram > 0) & (rsi < 75)
    elif preset_id == "aroon_breakout_confirmation":
        signal = (aroon_up >= 70) & (aroon_oscillator >= 50) & (volume_ratio >= 1.1)
    elif preset_id == "vortex_supertrend":
        signal = (vortex_positive > vortex_negative) & _text_is(rows, "technical_supertrend", "bullish") & positive
    elif preset_id == "squeeze_release_volume":
        signal = _text_is(rows, "technical_squeeze", "released") & (squeeze_momentum > 0) & (volume_ratio >= 1.2)
    elif preset_id == "squeeze_accumulation":
        signal = _text_is(rows, "technical_squeeze", "on") & (cmf >= .1) & (close > hma)
    elif preset_id == "keltner_breakout_adx":
        signal = (close > keltner_upper) & (adx >= 20) & (volume_ratio >= 1.2)
    elif preset_id == "keltner_trend_pullback":
        signal = _text_is(rows, "technical_supertrend", "bullish") & (close <= keltner_middle) & (rsi >= 40) & (rsi <= 58)
    elif preset_id == "psar_ppo_confirmation":
        signal = _text_is(rows, "technical_psar", "bullish") & (ppo_histogram > 0) & (ppo > 0)
    elif preset_id == "low_chop_supertrend":
        signal = (choppiness < 38.2) & _text_is(rows, "technical_supertrend", "bullish") & (adx >= 22)
    elif preset_id == "quality_trend_risk":
        signal = (adx >= 25) & (atr_percent <= 5) & (cmf > 0) & _text_is(rows, "technical_supertrend", "bullish")
    elif preset_id == "tsm_3m_quality":
        signal = (_change_percent(close, 63) >= 5) & _text_is(rows, "technical_sma_200", "above") & (adx >= 20) & (atr_percent <= 6)
    elif preset_id == "tsm_6m_volume":
        signal = (_change_percent(close, 126) >= 10) & (range_position >= 70) & (volume_ratio >= 1.1) & (cmf > 0)
    elif preset_id == "tsm_12m_low_vol":
        signal = (_change_percent(close, 252) >= 15) & _text_is(rows, "technical_sma_200", "above") & (historical_volatility <= 50) & (atr_percent <= 6)
    elif preset_id == "high_52w_accumulation":
        signal = (range_position >= 90) & (cmf >= .05) & (volume_ratio >= 1.1) & _text_is(rows, "technical_sma_50", "above")
    elif preset_id == "high_52w_breakout_adx":
        signal = (range_position >= 95) & (adx >= 25) & (plus_di > minus_di) & (volume_ratio >= 1.2)
    elif preset_id == "vol_managed_supertrend":
        signal = (historical_volatility <= 40) & (atr_percent <= 4) & _text_is(rows, "technical_supertrend", "bullish") & (adx >= 20)
    elif preset_id == "vol_managed_momentum":
        signal = (historical_volatility <= 45) & (roc >= 3) & (ppo_histogram > 0) & _text_is(rows, "technical_sma_50", "above")
    elif preset_id == "multi_horizon_ema_stack":
        signal = (ema_20 > ema_50) & (ema_50 > ema_200) & (ppo > 0) & (cmf > 0)
    elif preset_id == "donchian_liquid_breakout":
        signal = (close >= donchian_upper) & (adx >= 25) & (volume_ratio >= 1.5) & (atr_percent <= 6)
    elif preset_id == "trend_pullback_accumulation":
        signal = _text_is(rows, "technical_sma_200", "above") & (close <= ema_20) & (close > ema_50) & (rsi >= 40) & (rsi <= 55) & (cmf > 0)
    elif preset_id == "momentum_breadth_confirmation":
        signal = (aroon_up >= 70) & (vortex_positive > vortex_negative) & (ppo > 0) & (obv > _rolling_mean(obv, 20))
    elif preset_id == "squeeze_trend_regime":
        signal = _text_is(rows, "technical_squeeze", "released") & (choppiness < 45) & _text_is(rows, "technical_supertrend", "bullish") & (cmf > 0) & (volume_ratio >= 1.1)
    else:
        raise ValueError(f"Preset {preset_id} is not supported by the accelerated compiler.")
    raw = np.nan_to_num(signal, nan=False).astype(bool)
    # Preset rules use ON_CROSS semantics by default: a sustained true level
    # produces one signal, not a fresh order on every subsequent session.
    triggered = raw.copy()
    if count > 1:
        triggered[1:] = raw[1:] & ~raw[:-1]
    return [bool(value) for value in triggered]
