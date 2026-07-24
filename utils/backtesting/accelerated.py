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


def _positive_slope(values: np.ndarray, window: int) -> np.ndarray:
    result = np.zeros(len(values), dtype=bool)
    for index in range(window - 1, len(values)):
        scoped = values[index - window + 1:index + 1]
        result[index] = bool(np.isfinite(scoped).all() and np.polyfit(np.arange(window), scoped, 1)[0] > 0)
    return result


def compile_preset_signals(
    preset_id: str,
    rows: Sequence[Dict[str, Any]],
    *,
    trigger_on_cross: bool = True,
) -> List[bool]:
    """Compile one catalog preset without reading any future row.

    ``trigger_on_cross=False`` returns the rule's completed-session state. This
    is important for discovery: component states are combined first and the
    conjunction is crossed once, instead of requiring every component to have
    independently crossed on exactly the same session.
    """
    count = len(rows)
    close = _numbers(rows, "ltp")
    high = _numbers(rows, "high")
    low = _numbers(rows, "low")
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
    kama = _numbers(rows, "technical_kama_10")
    ultimate = _numbers(rows, "technical_ultimate_oscillator_7_14_28")
    trix = _numbers(rows, "technical_trix_15")
    kst = _numbers(rows, "technical_kst")
    kst_diff = _numbers(rows, "technical_kst_diff")
    ulcer = _numbers(rows, "technical_ulcer_index_14")
    force_index = _numbers(rows, "technical_force_index_13")
    vpt = _numbers(rows, "technical_volume_price_trend")
    vwap = _numbers(rows, "technical_vwap_20")
    ichimoku_conversion = _numbers(rows, "technical_ichimoku_conversion_9")
    ichimoku_base = _numbers(rows, "technical_ichimoku_base_26")
    ichimoku_span_a = _numbers(rows, "technical_ichimoku_span_a_26")
    ichimoku_span_b = _numbers(rows, "technical_ichimoku_span_b_52")
    price_zscore = _numbers(rows, "technical_price_zscore_20")
    efficiency = _numbers(rows, "technical_efficiency_ratio_20")
    candle_body = _numbers(rows, "technical_candle_body_percent")
    close_location = _numbers(rows, "technical_close_location_value")
    gap = _numbers(rows, "technical_gap_percent")
    prior_low = _numbers(rows, "technical_prior_low_20")
    breakout = _numbers(rows, "technical_breakout_20")
    bullish_engulfing = _numbers(rows, "technical_bullish_engulfing")
    hammer = _numbers(rows, "technical_hammer")
    inside_bar = _numbers(rows, "technical_inside_bar")
    outside_bar = _numbers(rows, "technical_outside_bar")
    bullish_marubozu = _numbers(rows, "technical_bullish_marubozu")
    higher_high = _numbers(rows, "technical_higher_high_3")
    higher_low = _numbers(rows, "technical_higher_low_3")
    percent_b = _numbers(rows, "technical_percent_b")
    bollinger_upper = _numbers(rows, "technical_bollinger_upper_20")
    sr_support_bounce = _numbers(rows, "technical_sr_support_bounce")
    sr_resistance_breakout = _numbers(rows, "technical_sr_resistance_breakout")
    fib_pullback_entry = _numbers(rows, "technical_fib_pullback_entry")
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
    elif preset_id == "pa_engulfing_trend_volume":
        signal = (bullish_engulfing == 1) & _text_is(rows, "technical_sma_200", "above") & (volume_ratio >= 1.1) & (rsi >= 35) & (rsi <= 65)
    elif preset_id == "pa_hammer_trend_reclaim":
        signal = (hammer == 1) & (close > ema_50) & _text_is(rows, "technical_sma_200", "above") & (close_location >= .65) & (cmf > 0)
    elif preset_id == "pa_inside_bar_trend":
        signal = (inside_bar == 1) & (ema_20 > ema_50) & (adx >= 20) & (volume_ratio <= 1.2)
    elif preset_id == "pa_outside_bar_momentum":
        signal = (outside_bar == 1) & (close_location >= .75) & (candle_body >= 1) & (volume_ratio >= 1.2)
    elif preset_id == "pa_marubozu_participation":
        signal = (bullish_marubozu == 1) & (volume_ratio >= 1.3) & (adx >= 20) & (atr_percent <= 7)
    elif preset_id == "pa_20d_breakout_volume":
        signal = (breakout == 1) & (volume_ratio >= 1.5) & (adx >= 20) & (atr_percent <= 7)
    elif preset_id == "pa_false_breakdown_reclaim":
        signal = (low < prior_low) & (close > prior_low) & (close_location >= .7) & (volume_ratio >= 1.1)
    elif preset_id == "pa_higher_high_low_continuation":
        signal = (higher_high == 1) & (higher_low == 1) & (ema_20 > ema_50) & (cmf > 0)
    elif preset_id == "pa_gap_momentum":
        signal = (gap >= 1) & (close_location >= .7) & (volume_ratio >= 1.3) & _text_is(rows, "technical_sma_50", "above")
    elif preset_id == "pa_vwap_reclaim":
        signal = (close > vwap) & (price_zscore <= 1.5) & (cmf > 0) & positive
    elif preset_id == "pv_dryup_trend_pullback":
        signal = (close <= ema_20) & (close > ema_50) & (ema_20 > ema_50) & (volume_ratio <= .75) & (rsi >= 40) & (rsi <= 60)
    elif preset_id == "pv_obv_breakout":
        signal = (breakout == 1) & (obv > _rolling_mean(obv, 20)) & (volume_ratio >= 1.3) & (close_location >= .7)
    elif preset_id == "pv_52w_high_volume":
        signal = (range_position >= 85) & (change >= 1) & (volume_ratio >= 1.5) & (cmf > 0)
    elif preset_id == "pv_squeeze_breakout":
        signal = _text_is(rows, "technical_squeeze", "released") & (breakout == 1) & (volume_ratio >= 1.5) & (choppiness < 45)
    elif preset_id == "pv_engulfing_accumulation":
        signal = (bullish_engulfing == 1) & (close > ema_50) & (cmf >= .05) & (volume_ratio >= 1.2)
    elif preset_id == "pv_liquid_momentum_risk":
        momentum_63 = _change_percent(close, 63)
        signal = (momentum_63 >= 5) & (momentum_63 <= 25) & (volume_ratio >= 1.2) & (atr_percent <= 5) & (adx >= 20) & _text_is(rows, "technical_sma_200", "above")
    elif preset_id == "pv_vwap_obv_reclaim":
        signal = (close > vwap) & (obv > _rolling_mean(obv, 20)) & (cmf > 0) & (volume_ratio >= 1.1)
    elif preset_id == "pv_cmf_low_chop_breakout":
        signal = (breakout == 1) & (cmf >= .1) & (choppiness < 40) & (volume_ratio >= 1.25)
    elif preset_id == "pv_force_kama_impulse":
        signal = (force_index > 0) & (close > kama) & (ppo_histogram > 0) & (volume_ratio >= 1.1)
    elif preset_id == "pv_donchian_low_vol":
        signal = (close >= donchian_upper) & (volume_ratio >= 1.3) & (historical_volatility <= 40) & (atr_percent <= 5)
    elif preset_id == "pv_supertrend_squeeze_flow":
        signal = _text_is(rows, "technical_supertrend", "bullish") & _text_is(rows, "technical_squeeze", "released") & (cmf > 0) & (volume_ratio >= 1.2)
    elif preset_id == "pv_multi_horizon_flow":
        signal = (_change_percent(close, 63) >= 5) & (_change_percent(close, 126) >= 10) & (cmf > 0) & (volume_ratio >= 1.1) & _text_is(rows, "technical_sma_200", "above")
    elif preset_id == "ichimoku_cloud_adx":
        signal = (close > ichimoku_span_a) & (close > ichimoku_span_b) & (ichimoku_conversion > ichimoku_base) & (adx >= 20)
    elif preset_id == "kama_adaptive_momentum":
        signal = (close > kama) & _positive_slope(kama, 5) & (ppo_histogram > 0) & (efficiency >= .3)
    elif preset_id == "kst_multi_cycle_trend":
        signal = (kst_diff > 0) & (kst > 0) & _text_is(rows, "technical_sma_200", "above") & (cmf > 0)
    elif preset_id == "trix_volume_trend":
        signal = (trix > 0) & (ppo_histogram > 0) & (volume_ratio >= 1.1) & _text_is(rows, "technical_sma_50", "above")
    elif preset_id == "ultimate_pullback_trend":
        signal = (ultimate >= 40) & (ultimate <= 60) & _text_is(rows, "technical_sma_200", "above") & (close > ema_50) & positive
    elif preset_id == "force_index_breakout":
        signal = (force_index > 0) & (breakout == 1) & (volume_ratio >= 1.2) & (adx >= 20)
    elif preset_id == "efficiency_trend_defense":
        signal = (efficiency >= .35) & (choppiness < 45) & (ema_20 > ema_50) & (ema_50 > ema_200) & (ppo_histogram > 0)
    elif preset_id == "low_ulcer_momentum":
        signal = (ulcer <= 8) & (_change_percent(close, 63) >= 5) & _text_is(rows, "technical_sma_200", "above") & (atr_percent <= 5)
    elif preset_id == "vpt_vwap_confirmation":
        signal = (vpt > _rolling_mean(vpt, 20)) & (close > vwap) & (cmf > 0) & _text_is(rows, "technical_sma_50", "above")
    elif preset_id == "nonlinear_momentum_regime":
        momentum_63 = _change_percent(close, 63)
        signal = (momentum_63 >= 5) & (momentum_63 <= 25) & (_change_percent(close, 126) >= 10) & (historical_volatility <= 45) & (adx >= 20) & _text_is(rows, "technical_sma_200", "above")
    elif preset_id.startswith("sr_bounce_"):
        signal = (sr_support_bounce == 1) & _text_is(rows, "technical_sma_200", "above")
    elif preset_id == "sr_breakout_participation":
        signal = (sr_resistance_breakout == 1) & (adx >= 20)
    elif preset_id in {
        "bollinger_lower_recovery_middle", "bollinger_lower_recovery_upper",
        "bollinger_pullback_fixed_4", "bollinger_pullback_trailing_5",
    }:
        signal = (percent_b >= 0) & (percent_b <= .25) & positive & (rsi >= 30) & (rsi <= 50)
    elif preset_id == "bollinger_trend_pullback":
        signal = (percent_b >= .10) & (percent_b <= .40) & _text_is(rows, "technical_supertrend", "bullish") & (cmf > 0)
    elif preset_id == "bollinger_squeeze_paired_exit":
        signal = _text_is(rows, "technical_squeeze", "released") & (close > bollinger_upper) & (volume_ratio >= 1.3)
    elif preset_id in {
        "fibonacci_pullback_resistance", "fibonacci_pullback_trend",
        "fibonacci_pullback_trailing_6",
    }:
        signal = fib_pullback_entry == 1
    elif preset_id == "fibonacci_volume_confirmation":
        signal = (fib_pullback_entry == 1) & (cmf > 0) & (volume_ratio >= 1.1)
    elif preset_id == "zone_bollinger_confluence":
        signal = (sr_support_bounce == 1) & (percent_b <= .35) & (cmf > 0)
    elif preset_id == "zone_momentum_quality":
        signal = (sr_support_bounce == 1) & (ppo_histogram > 0) & (adx >= 18)
    elif preset_id.startswith("nepse15_"):
        number = int(preset_id.rsplit("_", 1)[1])
        signal = _numbers(rows, f"technical_nepse15_entry_{number}") == 1
    else:
        raise ValueError(f"Preset {preset_id} is not supported by the accelerated compiler.")
    raw = np.nan_to_num(signal, nan=False).astype(bool)
    if not trigger_on_cross:
        return [bool(value) for value in raw]
    # Preset rules use ON_CROSS semantics by default: a sustained true level
    # produces one signal, not a fresh order on every subsequent session.
    triggered = raw.copy()
    if count > 1:
        triggered[1:] = raw[1:] & ~raw[:-1]
    return [bool(value) for value in triggered]


def compile_preset_exit_signals(preset_id: str, rows: Sequence[Dict[str, Any]]) -> List[bool]:
    """Return the preset's completed-session condition exit without look-ahead."""
    if preset_id.startswith("nepse15_"):
        number = int(preset_id.rsplit("_", 1)[1])
        return [bool(value) for value in (_numbers(rows, f"technical_nepse15_exit_{number}") == 1)]
    from utils.backtesting.presets import get_backtest_presets
    from utils.backtesting.strategy_discovery import compile_discovery_exit_signals
    preset = next((item for item in get_backtest_presets() if item["id"] == preset_id), None)
    if not preset or not preset.get("exit_rule_id"):
        return [False] * len(rows)
    return compile_discovery_exit_signals(preset, rows)
