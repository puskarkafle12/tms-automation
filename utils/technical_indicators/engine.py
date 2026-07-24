"""Native OHLCV indicator engine using standard Wilder and EMA definitions.

The output is aligned one-for-one with the input bars and never reads a future
row.  This makes the same fields safe for latest snapshots and backtests.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Sequence

import numpy as np
import pandas as pd
from ta.momentum import KAMAIndicator, PercentagePriceOscillator, UltimateOscillator
from ta.trend import AroonIndicator, MassIndex, PSARIndicator, TRIXIndicator, VortexIndicator
from ta.volatility import KeltnerChannel, UlcerIndex
from ta.volume import ForceIndexIndicator, VolumePriceTrendIndicator, VolumeWeightedAveragePrice

ENGINE_VERSION = "ohlcv-ta-v5-zones-ta-0.11.0"

NUMERIC_FIELDS = (
    "technical_sma_10_value", "technical_sma_20_value", "technical_sma_50_value",
    "technical_sma_100_value", "technical_sma_200_value", "technical_ema_9_value",
    "technical_ema_10_value", "technical_ema_12_value", "technical_ema_20_value",
    "technical_ema_26_value", "technical_ema_30_value", "technical_ema_50_value",
    "technical_ema_200_value", "technical_rsi_14",
    "technical_macd_value", "technical_macd_signal_value", "technical_macd_histogram",
    "technical_adx_14", "technical_plus_di_14", "technical_minus_di_14",
    "technical_stochastic_k_14", "technical_stochastic_d_3", "technical_williams_r_14",
    "technical_roc_12", "technical_mfi_14", "technical_cci_20", "technical_atr_14",
    "technical_atr_percent", "technical_bollinger_upper_20", "technical_bollinger_middle_20",
    "technical_bollinger_lower_20", "technical_percent_b", "technical_bollinger_bandwidth_20",
    "technical_donchian_upper_20", "technical_donchian_middle_20", "technical_donchian_lower_20",
    "technical_historical_volatility_20", "technical_obv", "technical_volume_sma_20",
    "technical_volume_ratio_20", "technical_cmf_20", "technical_accumulation_distribution",
    "technical_supertrend_10_3", "technical_supertrend_direction_10_3",
    "technical_hma_20", "technical_aroon_up_14", "technical_aroon_down_14",
    "technical_aroon_oscillator_14", "technical_vortex_positive_14",
    "technical_vortex_negative_14", "technical_ppo_12_26_9",
    "technical_ppo_signal_9", "technical_ppo_histogram",
    "technical_choppiness_14", "technical_keltner_lower_20",
    "technical_keltner_middle_20", "technical_keltner_upper_20",
    "technical_psar_value", "technical_squeeze_momentum",
    "technical_squeeze_on", "technical_squeeze_off",
    "technical_kama_10", "technical_ultimate_oscillator_7_14_28",
    "technical_trix_15", "technical_kst", "technical_kst_signal", "technical_kst_diff",
    "technical_mass_index_9_25", "technical_ulcer_index_14", "technical_force_index_13",
    "technical_volume_price_trend", "technical_vwap_20",
    "technical_ichimoku_conversion_9", "technical_ichimoku_base_26",
    "technical_ichimoku_span_a_26", "technical_ichimoku_span_b_52",
    "technical_price_zscore_20", "technical_efficiency_ratio_20",
    "technical_candle_body_percent", "technical_upper_wick_percent",
    "technical_lower_wick_percent", "technical_close_location_value",
    "technical_gap_percent", "technical_prior_high_20", "technical_prior_low_20",
    "technical_breakout_20", "technical_breakdown_20",
    "technical_bullish_engulfing", "technical_hammer", "technical_inside_bar",
    "technical_outside_bar", "technical_bullish_marubozu",
    "technical_higher_high_3", "technical_higher_low_3",
    "technical_sr_support_lower", "technical_sr_support_upper",
    "technical_sr_support_confidence", "technical_sr_support_touches",
    "technical_sr_resistance_lower", "technical_sr_resistance_upper",
    "technical_sr_resistance_confidence", "technical_sr_resistance_touches",
    "technical_sr_support_bounce", "technical_sr_resistance_breakout",
    "technical_sr_resistance_rejection", "technical_sr_support_breakdown",
    "technical_fib_range_high_63", "technical_fib_range_low_63",
    "technical_fib_retracement_382", "technical_fib_retracement_500",
    "technical_fib_retracement_618", "technical_fib_pullback_entry",
    "technical_fib_resistance_exit",
    "technical_buy_score", "technical_sell_score", "technical_signal_score",
    *(f"technical_nepse15_entry_{index}" for index in range(1, 16)),
    *(f"technical_nepse15_exit_{index}" for index in range(1, 16)),
)
TEXT_FIELDS = (
    "technical_macd", "technical_sma_10", "technical_sma_20", "technical_sma_50",
    "technical_sma_200", "technical_volume_trend", "technical_supertrend",
    "technical_psar", "technical_squeeze", "technical_signal",
)
INDICATOR_FIELDS = frozenset((*NUMERIC_FIELDS, *TEXT_FIELDS))


def _wilder(series: pd.Series, period: int) -> pd.Series:
    """Wilder RMA seeded by an SMA, matching the published RSI/ATR method."""
    values = series.astype(float).to_numpy()
    output = np.full(len(values), np.nan, dtype=float)
    valid = np.flatnonzero(np.isfinite(values))
    if len(valid) < period:
        return pd.Series(output, index=series.index)
    seed_position = valid[period - 1]
    seed_values = values[valid[:period]]
    output[seed_position] = float(np.mean(seed_values))
    previous = output[seed_position]
    for index in range(seed_position + 1, len(values)):
        if not np.isfinite(values[index]):
            continue
        previous = ((previous * (period - 1)) + values[index]) / period
        output[index] = previous
    return pd.Series(output, index=series.index)


def _finite(value: Any) -> Any:
    if value is None or isinstance(value, str):
        return value
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, 6) if math.isfinite(number) else None


def _weighted_average(series: pd.Series, window: int) -> pd.Series:
    weights = np.arange(1, window + 1, dtype=float)
    return series.rolling(window, min_periods=window).apply(
        lambda values: float(np.dot(values, weights) / weights.sum()), raw=True,
    )


def _supertrend(high: pd.Series, low: pd.Series, close: pd.Series, *, window: int = 10, multiplier: float = 3.0) -> tuple[pd.Series, pd.Series]:
    previous_close = close.shift(1)
    true_range = pd.concat((high - low, (high - previous_close).abs(), (low - previous_close).abs()), axis=1).max(axis=1)
    atr = _wilder(true_range, window)
    midpoint = (high + low) / 2
    basic_upper, basic_lower = midpoint + multiplier * atr, midpoint - multiplier * atr
    final_upper = basic_upper.copy()
    final_lower = basic_lower.copy()
    trend = pd.Series(np.nan, index=close.index, dtype=float)
    value = pd.Series(np.nan, index=close.index, dtype=float)
    for index in range(len(close)):
        if not math.isfinite(float(atr.iloc[index])):
            continue
        if index > 0 and math.isfinite(float(final_upper.iloc[index - 1])):
            final_upper.iloc[index] = basic_upper.iloc[index] if basic_upper.iloc[index] < final_upper.iloc[index - 1] or close.iloc[index - 1] > final_upper.iloc[index - 1] else final_upper.iloc[index - 1]
            final_lower.iloc[index] = basic_lower.iloc[index] if basic_lower.iloc[index] > final_lower.iloc[index - 1] or close.iloc[index - 1] < final_lower.iloc[index - 1] else final_lower.iloc[index - 1]
        prior_trend = trend.iloc[index - 1] if index > 0 and math.isfinite(float(trend.iloc[index - 1])) else 1.0
        if prior_trend < 0 and close.iloc[index] > final_upper.iloc[index]:
            trend.iloc[index] = 1.0
        elif prior_trend > 0 and close.iloc[index] < final_lower.iloc[index]:
            trend.iloc[index] = -1.0
        else:
            trend.iloc[index] = prior_trend
        value.iloc[index] = final_lower.iloc[index] if trend.iloc[index] > 0 else final_upper.iloc[index]
    return value, trend


def _signal_frame(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """Transparent 0..100 composite: five equally weighted confirmations."""
    buy = pd.Series(0.0, index=frame.index)
    sell = pd.Series(0.0, index=frame.index)
    pairs = (
        (frame["technical_rsi_14"] < 35, frame["technical_rsi_14"] > 65),
        (frame["technical_macd_histogram"] > 0, frame["technical_macd_histogram"] < 0),
        (frame["close"] > frame["technical_sma_50_value"], frame["close"] < frame["technical_sma_50_value"]),
        (frame["technical_plus_di_14"] > frame["technical_minus_di_14"], frame["technical_plus_di_14"] < frame["technical_minus_di_14"]),
        (frame["technical_mfi_14"] < 35, frame["technical_mfi_14"] > 65),
    )
    for bullish, bearish in pairs:
        buy += bullish.fillna(False).astype(float) * 20.0
        sell += bearish.fillna(False).astype(float) * 20.0
    score = buy - sell
    label = pd.Series("Neutral", index=frame.index, dtype=object)
    label[score >= 60] = "Strong Buy"
    label[(score >= 20) & (score < 60)] = "Buy"
    label[score <= -60] = "Strong Sell"
    label[(score <= -20) & (score > -60)] = "Sell"
    return buy, sell, score, label


def calculate_indicator_rows(bars: Sequence[Any]) -> List[Dict[str, Any]]:
    """Calculate aligned point-in-time fields from objects with OHLCV attributes."""
    if not bars:
        return []
    frame = pd.DataFrame({
        "open": [float(item.open) for item in bars],
        "high": [float(item.high) for item in bars],
        "low": [float(item.low) for item in bars],
        "close": [float(item.close) for item in bars],
        "volume": [float(item.volume) for item in bars],
    })
    close, high, low, volume = frame["close"], frame["high"], frame["low"], frame["volume"]

    for period in (10, 20, 50, 100, 200):
        frame[f"technical_sma_{period}_value"] = close.rolling(period, min_periods=period).mean()
    for period in (9, 10, 12, 20, 26, 30, 50, 200):
        frame[f"technical_ema_{period}_value"] = close.ewm(span=period, adjust=False, min_periods=period).mean()

    delta = close.diff()
    gain, loss = delta.clip(lower=0), -delta.clip(upper=0)
    rs = _wilder(gain, 14) / _wilder(loss, 14).replace(0, np.nan)
    frame["technical_rsi_14"] = 100 - (100 / (1 + rs))
    frame.loc[(_wilder(loss, 14) == 0) & (_wilder(gain, 14) > 0), "technical_rsi_14"] = 100.0

    macd = frame["technical_ema_12_value"] - frame["technical_ema_26_value"]
    macd_signal = macd.ewm(span=9, adjust=False, min_periods=9).mean()
    frame["technical_macd_value"] = macd
    frame["technical_macd_signal_value"] = macd_signal
    frame["technical_macd_histogram"] = macd - macd_signal

    previous_close = close.shift(1)
    true_range = pd.concat((high - low, (high - previous_close).abs(), (low - previous_close).abs()), axis=1).max(axis=1)
    atr = _wilder(true_range, 14)
    up_move, down_move = high.diff(), -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    plus_di = 100 * _wilder(plus_dm, 14) / atr.replace(0, np.nan)
    minus_di = 100 * _wilder(minus_dm, 14) / atr.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    frame["technical_atr_14"], frame["technical_atr_percent"] = atr, atr / close * 100
    frame["technical_plus_di_14"], frame["technical_minus_di_14"] = plus_di, minus_di
    frame["technical_adx_14"] = _wilder(dx, 14)

    lowest14, highest14 = low.rolling(14).min(), high.rolling(14).max()
    stochastic = 100 * (close - lowest14) / (highest14 - lowest14).replace(0, np.nan)
    frame["technical_stochastic_k_14"] = stochastic
    frame["technical_stochastic_d_3"] = stochastic.rolling(3).mean()
    frame["technical_williams_r_14"] = -100 * (highest14 - close) / (highest14 - lowest14).replace(0, np.nan)
    frame["technical_roc_12"] = close.pct_change(12, fill_method=None) * 100

    typical = (high + low + close) / 3
    raw_money = typical * volume
    positive = raw_money.where(typical.diff() > 0, 0.0).rolling(14).sum()
    negative = raw_money.where(typical.diff() < 0, 0.0).rolling(14).sum()
    money_ratio = positive / negative.replace(0, np.nan)
    frame["technical_mfi_14"] = 100 - (100 / (1 + money_ratio))
    typical_mean = typical.rolling(20).mean()
    mean_deviation = typical.rolling(20).apply(lambda values: np.mean(np.abs(values - np.mean(values))), raw=True)
    frame["technical_cci_20"] = (typical - typical_mean) / (0.015 * mean_deviation.replace(0, np.nan))

    middle = close.rolling(20).mean()
    deviation = close.rolling(20).std(ddof=0)
    upper, lower = middle + 2 * deviation, middle - 2 * deviation
    frame["technical_bollinger_upper_20"], frame["technical_bollinger_middle_20"], frame["technical_bollinger_lower_20"] = upper, middle, lower
    frame["technical_percent_b"] = (close - lower) / (upper - lower).replace(0, np.nan)
    frame["technical_bollinger_bandwidth_20"] = (upper - lower) / middle.replace(0, np.nan) * 100
    dc_upper, dc_lower = high.rolling(20).max(), low.rolling(20).min()
    frame["technical_donchian_upper_20"], frame["technical_donchian_lower_20"] = dc_upper, dc_lower
    frame["technical_donchian_middle_20"] = (dc_upper + dc_lower) / 2
    frame["technical_historical_volatility_20"] = np.log(close / close.shift(1)).rolling(20).std(ddof=1) * math.sqrt(252) * 100

    direction = np.sign(close.diff()).fillna(0)
    frame["technical_obv"] = (direction * volume).cumsum()
    frame["technical_volume_sma_20"] = volume.rolling(20).mean()
    frame["technical_volume_ratio_20"] = volume / frame["technical_volume_sma_20"].replace(0, np.nan)
    multiplier = ((close - low) - (high - close)) / (high - low).replace(0, np.nan)
    money_flow_volume = multiplier.fillna(0) * volume
    frame["technical_cmf_20"] = money_flow_volume.rolling(20).sum() / volume.rolling(20).sum().replace(0, np.nan)
    frame["technical_accumulation_distribution"] = money_flow_volume.cumsum()

    # Extended professional studies use the MIT-licensed `ta` library for
    # independently maintained implementations and transparent standard
    # formulas for the studies it does not provide. All are past-only.
    supertrend_value, supertrend_direction = _supertrend(high, low, close)
    frame["technical_supertrend_10_3"] = supertrend_value
    frame["technical_supertrend_direction_10_3"] = supertrend_direction
    frame["technical_supertrend"] = np.where(
        frame["technical_supertrend_direction_10_3"].isna(), None,
        np.where(frame["technical_supertrend_direction_10_3"] > 0, "Bullish", "Bearish"),
    )
    half_hma = _weighted_average(close, 10)
    frame["technical_hma_20"] = _weighted_average(2 * half_hma - _weighted_average(close, 20), int(math.sqrt(20)))
    aroon = AroonIndicator(high=high, low=low, window=14, fillna=False)
    frame["technical_aroon_down_14"] = aroon.aroon_down()
    frame["technical_aroon_up_14"] = aroon.aroon_up()
    frame["technical_aroon_oscillator_14"] = aroon.aroon_indicator()
    vortex = VortexIndicator(high=high, low=low, close=close, window=14, fillna=False)
    frame["technical_vortex_positive_14"] = vortex.vortex_indicator_pos()
    frame["technical_vortex_negative_14"] = vortex.vortex_indicator_neg()
    ppo = PercentagePriceOscillator(close=close, window_fast=12, window_slow=26, window_sign=9, fillna=False)
    frame["technical_ppo_12_26_9"] = ppo.ppo()
    frame["technical_ppo_histogram"] = ppo.ppo_hist()
    frame["technical_ppo_signal_9"] = ppo.ppo_signal()
    chop_range = high.rolling(14).max() - low.rolling(14).min()
    frame["technical_choppiness_14"] = 100 * np.log10(true_range.rolling(14).sum() / chop_range.replace(0, np.nan)) / math.log10(14)
    if len(frame) >= 10:
        keltner = KeltnerChannel(high=high, low=low, close=close, window=20, window_atr=10, original_version=False, multiplier=2, fillna=False)
        frame["technical_keltner_lower_20"] = keltner.keltner_channel_lband()
        frame["technical_keltner_middle_20"] = keltner.keltner_channel_mband()
        frame["technical_keltner_upper_20"] = keltner.keltner_channel_hband()
    else:
        frame["technical_keltner_lower_20"] = np.nan
        frame["technical_keltner_middle_20"] = np.nan
        frame["technical_keltner_upper_20"] = np.nan
    if len(frame) >= 2:
        psar = PSARIndicator(high=high, low=low, close=close, fillna=False)
        psar_value = psar.psar()
        frame["technical_psar_value"] = psar_value
        frame["technical_psar"] = np.where(psar_value.isna(), None, np.where(close >= psar_value, "Bullish", "Bearish"))
    else:
        frame["technical_psar_value"], frame["technical_psar"] = np.nan, None
    squeeze_on = (lower > frame["technical_keltner_lower_20"]) & (upper < frame["technical_keltner_upper_20"])
    squeeze_released = squeeze_on.shift(1, fill_value=False) & ~squeeze_on
    momentum_basis = (((high.rolling(20).max() + low.rolling(20).min()) / 2) + middle) / 2
    frame["technical_squeeze_momentum"] = close - momentum_basis
    frame["technical_squeeze_on"] = squeeze_on.astype(float)
    frame["technical_squeeze_off"] = squeeze_released.astype(float)
    frame["technical_squeeze"] = np.where(
        frame["technical_squeeze_on"] == 1, "On",
        np.where(frame["technical_squeeze_off"] == 1, "Released", "Neutral"),
    )

    # Adaptive/multi-horizon studies from the same open-source `ta` package.
    # Each output at index N is calculated only from rows <= N.
    frame["technical_kama_10"] = KAMAIndicator(close=close, window=10, pow1=2, pow2=30, fillna=False).kama()
    frame["technical_ultimate_oscillator_7_14_28"] = UltimateOscillator(
        high=high, low=low, close=close, window1=7, window2=14, window3=28, fillna=False,
    ).ultimate_oscillator()
    frame["technical_trix_15"] = TRIXIndicator(close=close, window=15, fillna=False).trix()
    # `ta` 0.11.0's KST uses the full-series mean as a shift fill value,
    # which leaks future observations into early rows. Use the published
    # past-only ROC/SMA construction instead.
    rocma1 = close.pct_change(10, fill_method=None).rolling(10, min_periods=10).mean()
    rocma2 = close.pct_change(15, fill_method=None).rolling(10, min_periods=10).mean()
    rocma3 = close.pct_change(20, fill_method=None).rolling(10, min_periods=10).mean()
    rocma4 = close.pct_change(30, fill_method=None).rolling(15, min_periods=15).mean()
    kst_value = 100 * (rocma1 + 2 * rocma2 + 3 * rocma3 + 4 * rocma4)
    kst_signal = kst_value.rolling(9, min_periods=9).mean()
    frame["technical_kst"] = kst_value
    frame["technical_kst_signal"] = kst_signal
    frame["technical_kst_diff"] = kst_value - kst_signal
    frame["technical_mass_index_9_25"] = MassIndex(high=high, low=low, window_fast=9, window_slow=25, fillna=False).mass_index()
    frame["technical_ulcer_index_14"] = UlcerIndex(close=close, window=14, fillna=False).ulcer_index()
    frame["technical_force_index_13"] = ForceIndexIndicator(close=close, volume=volume, window=13, fillna=False).force_index()
    frame["technical_volume_price_trend"] = VolumePriceTrendIndicator(close=close, volume=volume, fillna=False).volume_price_trend()
    frame["technical_vwap_20"] = VolumeWeightedAveragePrice(
        high=high, low=low, close=close, volume=volume, window=20, fillna=False,
    ).volume_weighted_average_price()

    # Ichimoku values are intentionally plotted without future displacement.
    # The decision row therefore never reads a future cloud value.
    conversion = (high.rolling(9).max() + low.rolling(9).min()) / 2
    base = (high.rolling(26).max() + low.rolling(26).min()) / 2
    frame["technical_ichimoku_conversion_9"] = conversion
    frame["technical_ichimoku_base_26"] = base
    frame["technical_ichimoku_span_a_26"] = (conversion + base) / 2
    frame["technical_ichimoku_span_b_52"] = (high.rolling(52).max() + low.rolling(52).min()) / 2

    # Price-action geometry and breakout state. Previous levels are shifted by
    # one session so today's high/low cannot define its own breakout threshold.
    open_price = frame["open"]
    candle_range = (high - low).replace(0, np.nan)
    body = close - open_price
    absolute_body = body.abs()
    upper_wick = high - pd.concat((open_price, close), axis=1).max(axis=1)
    lower_wick = pd.concat((open_price, close), axis=1).min(axis=1) - low
    frame["technical_candle_body_percent"] = body / open_price.replace(0, np.nan) * 100
    frame["technical_upper_wick_percent"] = upper_wick / candle_range * 100
    frame["technical_lower_wick_percent"] = lower_wick / candle_range * 100
    frame["technical_close_location_value"] = (close - low) / candle_range
    frame["technical_gap_percent"] = (open_price - previous_close) / previous_close.replace(0, np.nan) * 100
    frame["technical_price_zscore_20"] = (close - middle) / deviation.replace(0, np.nan)
    frame["technical_efficiency_ratio_20"] = close.diff(20).abs() / close.diff().abs().rolling(20).sum().replace(0, np.nan)

    prior_high_20 = high.shift(1).rolling(20).max()
    prior_low_20 = low.shift(1).rolling(20).min()
    frame["technical_prior_high_20"] = prior_high_20
    frame["technical_prior_low_20"] = prior_low_20
    frame["technical_breakout_20"] = (close > prior_high_20).astype(float)
    frame["technical_breakdown_20"] = (close < prior_low_20).astype(float)
    bullish = close > open_price
    prior_bearish = previous_close < open_price.shift(1)
    frame["technical_bullish_engulfing"] = (
        bullish & prior_bearish & (open_price <= previous_close) & (close >= open_price.shift(1))
    ).astype(float)
    frame["technical_hammer"] = (
        bullish & (lower_wick >= absolute_body * 2) & (upper_wick <= absolute_body) &
        (absolute_body / candle_range <= 0.5)
    ).astype(float)
    frame["technical_inside_bar"] = ((high < high.shift(1)) & (low > low.shift(1))).astype(float)
    frame["technical_outside_bar"] = ((high > high.shift(1)) & (low < low.shift(1)) & bullish).astype(float)
    frame["technical_bullish_marubozu"] = (
        bullish & (absolute_body / candle_range >= 0.8) &
        (upper_wick / candle_range <= 0.1) & (lower_wick / candle_range <= 0.1)
    ).astype(float)
    frame["technical_higher_high_3"] = (high > high.shift(1).rolling(2).max()).astype(float)
    frame["technical_higher_low_3"] = (low > low.shift(1).rolling(2).max()).astype(float)

    # Causal multi-touch support/resistance zones. A pivot is not available
    # until three later daily sessions confirm it, preventing retrospective
    # swing placement in both current charts and historical backtests.
    from utils.backtesting.support_resistance import calculate_zone_history
    zone_history = calculate_zone_history(frame.to_dict("records"))
    support_lower = pd.Series(
        [item["support"]["lower"] if item["support"] else np.nan for item in zone_history],
        index=frame.index,
    )
    support_upper = pd.Series(
        [item["support"]["upper"] if item["support"] else np.nan for item in zone_history],
        index=frame.index,
    )
    support_center = (support_lower + support_upper) / 2
    resistance_lower = pd.Series(
        [item["resistance"]["lower"] if item["resistance"] else np.nan for item in zone_history],
        index=frame.index,
    )
    resistance_upper = pd.Series(
        [item["resistance"]["upper"] if item["resistance"] else np.nan for item in zone_history],
        index=frame.index,
    )
    resistance_center = (resistance_lower + resistance_upper) / 2
    support_confidence = pd.Series([
        item["support"]["confidence"] if item["support"] else np.nan for item in zone_history
    ], index=frame.index)
    support_touches = pd.Series([
        item["support"]["touches"] if item["support"] else np.nan for item in zone_history
    ], index=frame.index)
    resistance_confidence = pd.Series([
        item["resistance"]["confidence"] if item["resistance"] else np.nan for item in zone_history
    ], index=frame.index)
    resistance_touches = pd.Series([
        item["resistance"]["touches"] if item["resistance"] else np.nan for item in zone_history
    ], index=frame.index)
    support_bounce = (
        (low <= support_upper) & (close >= support_center) &
        (frame["technical_close_location_value"] >= .60) &
        (frame["technical_volume_ratio_20"] >= 1.0) &
        (support_confidence >= 45)
    ).astype(float)
    resistance_breakout = (
        (close > resistance_upper) & (close.shift(1) <= resistance_upper.shift(1)) &
        (frame["technical_volume_ratio_20"] >= 1.25)
    ).astype(float)
    resistance_rejection = (
        (high >= resistance_lower) & (close < resistance_center) &
        (frame["technical_upper_wick_percent"] >= 25) &
        (resistance_confidence >= 45)
    ).astype(float)
    support_breakdown = (
        (close < support_lower) & (close.shift(1) >= support_lower.shift(1))
    ).astype(float)

    # Past-only 63-session Fibonacci retracement grid. The range excludes the
    # current bar, so today's signal cannot change its own reference anchors.
    fib_high = high.shift(1).rolling(63, min_periods=63).max()
    fib_low = low.shift(1).rolling(63, min_periods=63).min()
    fib_range = fib_high - fib_low
    fib_382 = fib_high - fib_range * .382
    fib_500 = fib_high - fib_range * .500
    fib_618 = fib_high - fib_range * .618
    fib_pullback_entry = (
        (frame["technical_ema_50_value"] > frame["technical_ema_200_value"]) &
        (low <= fib_500) & (close >= fib_618) & (close > open_price) &
        frame["technical_rsi_14"].between(38, 58) &
        (frame["technical_volume_ratio_20"] >= .9)
    ).astype(float)
    fib_resistance_exit = (
        ((high >= fib_high * .995) & (close < fib_high)) |
        ((close < fib_618) & (close.shift(1) >= fib_618.shift(1)))
    ).astype(float)
    frame = pd.concat([frame, pd.DataFrame({
        "technical_sr_support_lower": support_lower,
        "technical_sr_support_upper": support_upper,
        "technical_sr_support_confidence": support_confidence,
        "technical_sr_support_touches": support_touches,
        "technical_sr_resistance_lower": resistance_lower,
        "technical_sr_resistance_upper": resistance_upper,
        "technical_sr_resistance_confidence": resistance_confidence,
        "technical_sr_resistance_touches": resistance_touches,
        "technical_sr_support_bounce": support_bounce,
        "technical_sr_resistance_breakout": resistance_breakout,
        "technical_sr_resistance_rejection": resistance_rejection,
        "technical_sr_support_breakdown": support_breakdown,
        "technical_fib_range_high_63": fib_high,
        "technical_fib_range_low_63": fib_low,
        "technical_fib_retracement_382": fib_382,
        "technical_fib_retracement_500": fib_500,
        "technical_fib_retracement_618": fib_618,
        "technical_fib_pullback_entry": fib_pullback_entry,
        "technical_fib_resistance_exit": fib_resistance_exit,
    }, index=frame.index)], axis=1)

    # User-supplied NEPSE research set.  These setup/exit states are calculated
    # once from completed daily bars and are shared by backtests and live
    # monitoring.  The common liquidity/history gates are deliberately part of
    # every entry so a UI name cannot accidentally bypass them.
    frame = frame.copy()
    ema10 = frame["technical_ema_10_value"]
    ema20 = frame["technical_ema_20_value"]
    ema30 = frame["technical_ema_30_value"]
    ema50 = frame["technical_ema_50_value"]
    ema200 = frame["technical_ema_200_value"]
    rsi = frame["technical_rsi_14"]
    adx = frame["technical_adx_14"]
    plus_di = frame["technical_plus_di_14"]
    minus_di = frame["technical_minus_di_14"]
    volume_ratio = frame["technical_volume_ratio_20"]
    atr_value = frame["technical_atr_14"]
    stoch_k = frame["technical_stochastic_k_14"]
    stoch_d = frame["technical_stochastic_d_3"]
    macd_value = frame["technical_macd_value"]
    macd_signal_value = frame["technical_macd_signal_value"]
    macd_histogram = frame["technical_macd_histogram"]
    obv = frame["technical_obv"]
    turnover20 = (close * volume).rolling(20, min_periods=20).mean()
    common = (turnover20 >= 2_000_000) & (rsi <= 80) & (pd.Series(np.arange(len(frame)), index=frame.index) >= 249)
    cross_up = lambda left, right: (left > right) & (left.shift(1) <= right.shift(1))
    cross_down = lambda left, right: (left < right) & (left.shift(1) >= right.shift(1))
    ema_stack = (ema20 > ema50) & (ema50 > ema200)
    close_up = close > close.shift(1)
    close_below_ema20_twice = (close < ema20) & (close.shift(1) < ema20.shift(1))
    prior_high10 = high.shift(1).rolling(10, min_periods=10).max()
    prior_low10 = low.shift(1).rolling(10, min_periods=10).min()

    # 1 Trend Pullback + ADX + Volume.
    frame["technical_nepse15_entry_1"] = (
        common & (close > ema50) & ema_stack & (adx > 20) & rsi.between(42, 62) &
        ((low <= ema20) | ((close - ema20).abs() <= atr_value)) & close_up & (volume_ratio > 1.10)
    ).astype(float)
    frame["technical_nepse15_exit_1"] = close_below_ema20_twice.astype(float)

    # 2 20-session breakout + participation.
    frame["technical_nepse15_entry_2"] = (
        common & (close > frame["technical_prior_high_20"]) & (close > ema50) & (ema20 > ema50) &
        (adx > 20) & rsi.between(55, 75) & (volume_ratio > 1.5)
    ).astype(float)
    frame["technical_nepse15_exit_2"] = (close < ema20).astype(float)

    # 3 MACD momentum + trend.
    frame["technical_nepse15_entry_3"] = (
        common & (close > ema50) & (ema20 > ema50) & cross_up(macd_value, macd_signal_value) &
        (macd_histogram > macd_histogram.shift(1)) & rsi.between(50, 68) & (adx > 18) & (volume_ratio > 1)
    ).astype(float)
    frame["technical_nepse15_exit_3"] = cross_down(macd_value, macd_signal_value).astype(float)

    # 4 Oversold Bollinger recovery.  The recovery must occur no more than
    # three sessions after an oversold lower-band touch.
    oversold_touch = (close > frame["technical_sma_200_value"]) & (frame["technical_sma_50_value"] > frame["technical_sma_200_value"]) & (rsi < 35) & (low <= lower)
    recent_touch = oversold_touch.shift(1).rolling(3, min_periods=1).max().fillna(0).astype(bool)
    frame["technical_nepse15_entry_4"] = (common & recent_touch & cross_up(close, lower) & close_up).astype(float)
    frame["technical_nepse15_exit_4"] = (rsi > 70).astype(float)

    # 5 52-week high breakout.
    frame["technical_nepse15_entry_5"] = (
        common & (close >= high.rolling(252, min_periods=252).max() * .98) &
        (close > high.shift(1).rolling(60, min_periods=60).max()) & ema_stack &
        (adx > 22) & rsi.between(55, 78) & (volume_ratio > 1.5)
    ).astype(float)
    frame["technical_nepse15_exit_5"] = close_below_ema20_twice.astype(float)

    # 6 EMA 10/30 crossover + ADX.
    frame["technical_nepse15_entry_6"] = (
        common & cross_up(ema10, ema30) & (close > ema50) & (adx > 20) &
        (plus_di > minus_di) & rsi.between(50, 70) & (volume_ratio > 1)
    ).astype(float)
    frame["technical_nepse15_exit_6"] = cross_down(ema10, ema30).astype(float)

    # 7 Bollinger squeeze release.
    bandwidth = frame["technical_bollinger_bandwidth_20"]
    prior_squeeze_low = bandwidth.shift(1) <= bandwidth.shift(1).rolling(20, min_periods=20).min()
    frame["technical_nepse15_entry_7"] = (
        common & prior_squeeze_low & (bandwidth > bandwidth.shift(1)) & (close > upper) &
        (close > ema50) & (volume_ratio > 1.5) & rsi.between(55, 75)
    ).astype(float)
    frame["technical_nepse15_exit_7"] = (close < middle).astype(float)

    # 8 Past-only Ichimoku cloud breakout (cloud values are intentionally not
    # displaced into the future; see the engine comment above).
    cloud_top = pd.concat((frame["technical_ichimoku_span_a_26"], frame["technical_ichimoku_span_b_52"]), axis=1).max(axis=1)
    cloud_bottom = pd.concat((frame["technical_ichimoku_span_a_26"], frame["technical_ichimoku_span_b_52"]), axis=1).min(axis=1)
    frame["technical_nepse15_entry_8"] = (
        common & cross_up(close, cloud_top) & (conversion > base) &
        (frame["technical_ichimoku_span_a_26"] > frame["technical_ichimoku_span_b_52"]) &
        (close > close.shift(26)) & (adx > 20) & (volume_ratio > 1)
    ).astype(float)
    frame["technical_nepse15_exit_8"] = (cross_down(conversion, base) | close.between(cloud_bottom, cloud_top)).astype(float)

    # 9 Donchian 20/10 trend.
    frame["technical_nepse15_entry_9"] = (
        common & (close > frame["technical_prior_high_20"]) & (ema50 > ema50.shift(5)) &
        (adx > 22) & (volume_ratio > 1.2) & (rsi < 78)
    ).astype(float)
    frame["technical_nepse15_exit_9"] = (close < prior_low10).astype(float)

    # 10 Support bounce + bullish reversal.  Support is the prior 20-session
    # low and must have been approached at least twice before today's candle.
    support = low.shift(1).rolling(20, min_periods=20).min()
    support_tests = ((low.shift(1) - support).abs() / support.replace(0, np.nan) <= .015).rolling(20, min_periods=20).sum()
    morning_star = (close.shift(2) < open_price.shift(2)) & ((close.shift(1) - open_price.shift(1)).abs() <= (high.shift(1) - low.shift(1)) * .35) & (close > open_price) & (close > (open_price.shift(2) + close.shift(2)) / 2)
    bullish_reversal = (frame["technical_bullish_engulfing"] == 1) | (frame["technical_hammer"] == 1) | morning_star
    frame["technical_nepse15_entry_10"] = (
        common & (close > ema200) & ((close - support).abs() / support.replace(0, np.nan) <= .015) &
        (support_tests >= 2) & rsi.between(35, 50) & bullish_reversal & (close > high.shift(1)) & (volume_ratio > 1.2)
    ).astype(float)
    frame["technical_nepse15_exit_10"] = (close < support).astype(float)

    # 11 Stochastic pullback continuation.
    stoch_was_oversold = stoch_k.shift(1).rolling(5, min_periods=1).min() < 25
    frame["technical_nepse15_entry_11"] = (
        common & (ema20 > ema50) & (close > ema50) & stoch_was_oversold & cross_up(stoch_k, stoch_d) &
        (rsi > 40) & (adx > 18) & close_up
    ).astype(float)
    frame["technical_nepse15_exit_11"] = (cross_down(stoch_k, stoch_d) & (stoch_k.shift(1) > 80)).astype(float)

    # 12 OBV accumulation breakout.
    consolidation_high = high.shift(1).rolling(10, min_periods=10).max()
    consolidation_low = low.shift(1).rolling(10, min_periods=10).min()
    consolidation = (consolidation_high / consolidation_low.replace(0, np.nan) - 1) <= .08
    frame["technical_nepse15_entry_12"] = (
        common & consolidation & (obv > obv.shift(1).rolling(20, min_periods=20).max()) &
        (close > close.shift(1).rolling(10, min_periods=10).max()) & (volume_ratio > 1.3) & (close > ema50)
    ).astype(float)
    frame["technical_nepse15_exit_12"] = (obv < obv.ewm(span=10, adjust=False, min_periods=10).mean()).astype(float)

    # 13 Five-session momentum followed by a controlled 1-3 session pullback.
    rises5 = (close.diff() > 0).rolling(5, min_periods=5).sum() >= 4
    return5 = close.pct_change(5, fill_method=None) * 100
    momentum = rises5 & return5.between(3, 12) & (close > ema20) & (ema20 > ema50)
    recent_momentum = momentum.shift(1).rolling(3, min_periods=1).max().fillna(0).astype(bool)
    controlled_volume = volume.shift(1).rolling(3, min_periods=1).mean() < frame["technical_volume_sma_20"]
    frame["technical_nepse15_entry_13"] = (common & recent_momentum & controlled_volume & (close > high.shift(1))).astype(float)
    frame["technical_nepse15_exit_13"] = (close < ema20).astype(float)

    # 14 Volatility contraction: three consecutive five-session ranges shrink,
    # followed by a high-volume escape from the prior contraction.
    range_5 = high.rolling(5, min_periods=5).max() - low.rolling(5, min_periods=5).min()
    contractions = (range_5.shift(5) < range_5.shift(10)) & (range_5.shift(10) < range_5.shift(15))
    declining_volume = volume.shift(1).rolling(5).mean() < volume.shift(6).rolling(5).mean()
    contraction_high = high.shift(1).rolling(15, min_periods=15).max()
    frame["technical_nepse15_entry_14"] = (
        common & contractions & declining_volume & (close > ema50) &
        (close > contraction_high) & (volume_ratio > 1.5)
    ).astype(float)
    frame["technical_nepse15_exit_14"] = (close < ema10).astype(float)

    # 15 Relative-strength leader.  Until a versioned NEPSE index series is
    # available, this uses auditable absolute 20/60-session strength instead
    # of inventing benchmark-relative observations.
    return20 = close.pct_change(20, fill_method=None) * 100
    return60 = close.pct_change(60, fill_method=None) * 100
    frame["technical_nepse15_entry_15"] = (
        common & (return20 >= 5) & (return60 > 0) & (close > ema20) & ema_stack &
        (adx > 20) & rsi.between(55, 75) & (volume_ratio > 1.1) & (close > prior_high10)
    ).astype(float)
    frame["technical_nepse15_exit_15"] = close_below_ema20_twice.astype(float)

    # Consolidate blocks after the extended field insertions. This keeps the
    # final label/score calculations fast when a whole market is prepared.
    frame = frame.copy()

    frame["technical_macd"] = np.where(frame["technical_macd_histogram"].isna(), None, np.where(frame["technical_macd_histogram"] >= 0, "Bullish", "Bearish"))
    for period in (10, 20, 50, 200):
        average = frame[f"technical_sma_{period}_value"]
        frame[f"technical_sma_{period}"] = np.where(average.isna(), None, np.where(close >= average, "above", "below"))
    ratio = frame["technical_volume_ratio_20"]
    frame["technical_volume_trend"] = np.where(ratio.isna(), None, np.where(ratio > 1.05, "Trending Up", np.where(ratio < .95, "Trending Down", "Flat")))
    buy, sell, score, label = _signal_frame(frame)
    frame["technical_buy_score"], frame["technical_sell_score"] = buy, sell
    frame["technical_signal_score"], frame["technical_signal"] = score, label

    return [{key: _finite(row.get(key)) for key in INDICATOR_FIELDS} for row in frame.to_dict("records")]
