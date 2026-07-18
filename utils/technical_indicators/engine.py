"""Native OHLCV indicator engine using standard Wilder and EMA definitions.

The output is aligned one-for-one with the input bars and never reads a future
row.  This makes the same fields safe for latest snapshots and backtests.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Sequence

import numpy as np
import pandas as pd
from ta.momentum import PercentagePriceOscillator
from ta.trend import AroonIndicator, PSARIndicator, VortexIndicator
from ta.volatility import KeltnerChannel

ENGINE_VERSION = "ohlcv-ta-v2-ta-0.11.0"

NUMERIC_FIELDS = (
    "technical_sma_10_value", "technical_sma_20_value", "technical_sma_50_value",
    "technical_sma_100_value", "technical_sma_200_value", "technical_ema_9_value",
    "technical_ema_12_value", "technical_ema_20_value", "technical_ema_26_value",
    "technical_ema_50_value", "technical_ema_200_value", "technical_rsi_14",
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
    "technical_buy_score", "technical_sell_score", "technical_signal_score",
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
    for period in (9, 12, 20, 26, 50, 200):
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
