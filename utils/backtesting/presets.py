"""Curated, auditable backtest presets built only from historical-safe fields."""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List


def _preset(
    preset_id: str, name: str, category: str, condition: str, description: str,
    *, stop: float = 5, target: float = 10, holding: int = 20, research_basis: str = "",
) -> Dict[str, Any]:
    source_hash = hashlib.sha256(f"{condition}|{stop}|{target}|{holding}".encode("utf-8")).hexdigest()
    return {
        "id": preset_id,
        "name": name,
        "category": category,
        "condition": condition,
        "description": description,
        "research_basis": research_basis,
        "family": preset_id.rsplit("_", 1)[0],
        "version": "preset-v1", "source_hash": source_hash,
        "defaults": {"stop_loss_pct": stop, "take_profit_pct": target, "max_holding_days": holding},
    }


def get_backtest_presets() -> List[Dict[str, Any]]:
    presets: List[Dict[str, Any]] = []
    for threshold in (25, 30, 35, 40, 45):
        presets.append(_preset(
            f"rsi_recovery_{threshold}", f"RSI Recovery ≤ {threshold}", "RSI",
            f"technical_rsi_14 <= {threshold} AND change_percent > 0",
            "Oversold-to-recovery entry confirmed by a positive close.", stop=5, target=10,
        ))
    for lower in (45, 50, 55, 60, 65):
        presets.append(_preset(
            f"rsi_momentum_{lower}", f"RSI Momentum {lower}–80", "RSI",
            f"technical_rsi_14 BETWEEN {lower} AND 80 AND change_percent > 0",
            "Positive momentum while RSI remains below the extreme zone.", stop=6, target=12,
        ))
    for period in (10, 20, 50, 200):
        presets.append(_preset(
            f"sma_trend_{period}", f"SMA {period} Trend", "Trend",
            f'technical_sma_{period} = "above" AND technical_macd = "Bullish"',
            f"Price above SMA {period} with bullish MACD regime.", stop=6, target=15, holding=30,
        ))
    for period in (10, 20, 50, 200):
        presets.append(_preset(
            f"sma_pullback_{period}", f"SMA {period} Pullback", "Mean reversion",
            f'technical_sma_{period} = "below" AND technical_rsi_14 < 40 AND change_percent > 0',
            f"Recovery attempt below SMA {period} from a weak RSI reading.", stop=5, target=9,
        ))
    for threshold in (10, 15, 20, 25, 30):
        presets.append(_preset(
            f"range_value_{threshold}", f"52W Value Zone {threshold}%", "52-week range",
            f"position_in_52_week_range_percent <= {threshold} AND change_percent > 0",
            "Positive session near the lower end of the rolling 52-week range.", stop=6, target=14, holding=30,
        ))
    for threshold in (70, 75, 80, 85, 90):
        presets.append(_preset(
            f"range_strength_{threshold}", f"52W Strength ≥ {threshold}%", "52-week range",
            f"position_in_52_week_range_percent >= {threshold} AND change_percent > 0",
            "Momentum entry near the upper end of the rolling 52-week range.", stop=7, target=16, holding=30,
        ))
    for index, ratio in enumerate((1.1, 1.25, 1.5, 2.0, 3.0), start=1):
        presets.append(_preset(
            f"volume_surge_{index}", f"Volume Surge {ratio:g}×", "Volume",
            f"volume > AVERAGE(field=volume, window=20) * {ratio:g} AND change_percent > 0",
            f"Positive close with volume above {ratio:g} times its 20-session average.", stop=6, target=13,
        ))
    for change in (0.25, 0.5, 1, 2, 3):
        presets.append(_preset(
            f"volume_momentum_{str(change).replace('.', '_')}", f"Volume Momentum +{change:g}%", "Volume",
            f"volume > AVERAGE(field=volume, window=10) AND change_percent >= {change:g}",
            "Above-average participation combined with a minimum daily price gain.", stop=6, target=12,
        ))
    for count in (2, 3, 4, 5):
        presets.append(_preset(
            f"consecutive_rises_{count}", f"{count}-Session Rise", "Price action",
            f"CONSECUTIVE_RISES(field=ltp, count={count}, min_total_change_pct=1)",
            f"Continuation after {count} consecutive rising closes.", stop=6, target=12,
        ))
    for count in (2, 3, 4, 5):
        presets.append(_preset(
            f"consecutive_drops_{count}", f"{count}-Session Capitulation", "Mean reversion",
            f"CONSECUTIVE_DROPS(field=ltp, count={count}, min_total_change_pct=2)",
            f"Contrarian entry after {count} consecutive declining closes.", stop=5, target=10,
        ))
    for period in (5, 10, 20, 50):
        presets.append(_preset(
            f"average_breakout_{period}", f"{period}-Session Average Breakout", "Breakout",
            f"CROSSES_ABOVE(field=ltp, threshold=AVERAGE(field=ltp, window={period})) AND volume > 0",
            f"Close crosses above its rolling {period}-session average.", stop=6, target=14,
        ))
    for window in (3, 5, 10, 20, 30):
        presets.append(_preset(
            f"slope_momentum_{window}", f"Slope Momentum {window}", "Trend",
            f'SLOPE(field=ltp, window={window}, operator="gt", threshold=0) AND change_percent > 0',
            f"Positive {window}-session price slope confirmed by a positive close.", stop=7, target=15, holding=30,
        ))
    combined = (
        ("balanced_recovery", "Balanced Recovery", 'technical_rsi_14 BETWEEN 30 AND 50 AND technical_macd = "Bullish" AND change_percent > 0'),
        ("trend_volume", "Trend + Volume", 'technical_sma_20 = "above" AND volume > AVERAGE(field=volume, window=20) AND change_percent > 0'),
        ("deep_value_reversal", "Deep Value Reversal", 'position_in_52_week_range_percent <= 20 AND technical_rsi_14 <= 40 AND change_percent > 0'),
        ("quality_momentum", "Quality Momentum", 'technical_sma_50 = "above" AND technical_macd = "Bullish" AND technical_rsi_14 BETWEEN 50 AND 75'),
        ("breakout_participation", "Breakout Participation", 'position_in_52_week_range_percent >= 80 AND volume > AVERAGE(field=volume, window=20) * 1.25'),
    )
    for preset_id, name, condition in combined:
        presets.append(_preset(preset_id, name, "Combined", condition, "Multi-factor confirmation preset.", stop=7, target=16, holding=30))
    professional = (
        ("supertrend_adx_confirmation", "Supertrend + ADX Confirmation", 'technical_supertrend = "Bullish" AND technical_adx_14 >= 20 AND technical_plus_di_14 > technical_minus_di_14', 6, 15, 30),
        ("supertrend_volume_momentum", "Supertrend Volume Momentum", 'technical_supertrend = "Bullish" AND technical_volume_ratio_20 >= 1.2 AND technical_rsi_14 BETWEEN 50 AND 72', 7, 17, 30),
        ("hma_ppo_momentum", "Hull MA + PPO Momentum", 'ltp > technical_hma_20 AND technical_ppo_histogram > 0 AND technical_rsi_14 < 75', 6, 14, 25),
        ("aroon_breakout_confirmation", "Aroon Breakout Confirmation", 'technical_aroon_up_14 >= 70 AND technical_aroon_oscillator_14 >= 50 AND technical_volume_ratio_20 >= 1.1', 7, 18, 35),
        ("vortex_supertrend", "Vortex + Supertrend", 'technical_vortex_positive_14 > technical_vortex_negative_14 AND technical_supertrend = "Bullish" AND change_percent > 0', 6, 16, 30),
        ("squeeze_release_volume", "Volatility Squeeze Release", 'technical_squeeze = "Released" AND technical_squeeze_momentum > 0 AND technical_volume_ratio_20 >= 1.2', 6, 18, 30),
        ("squeeze_accumulation", "Squeeze Accumulation", 'technical_squeeze = "On" AND technical_cmf_20 >= 0.1 AND ltp > technical_hma_20', 5, 14, 25),
        ("keltner_breakout_adx", "Keltner Breakout + ADX", 'ltp > technical_keltner_upper_20 AND technical_adx_14 >= 20 AND technical_volume_ratio_20 >= 1.2', 7, 20, 35),
        ("keltner_trend_pullback", "Keltner Trend Pullback", 'technical_supertrend = "Bullish" AND ltp <= technical_keltner_middle_20 AND technical_rsi_14 BETWEEN 40 AND 58', 5, 13, 25),
        ("psar_ppo_confirmation", "PSAR + PPO Confirmation", 'technical_psar = "Bullish" AND technical_ppo_histogram > 0 AND technical_ppo_12_26_9 > 0', 6, 15, 30),
        ("low_chop_supertrend", "Low-Chop Supertrend", 'technical_choppiness_14 < 38.2 AND technical_supertrend = "Bullish" AND technical_adx_14 >= 22', 7, 18, 35),
        ("quality_trend_risk", "Quality Trend Risk Filter", 'technical_adx_14 >= 25 AND technical_atr_percent <= 5 AND technical_cmf_20 > 0 AND technical_supertrend = "Bullish"', 6, 16, 30),
    )
    for preset_id, name, condition, stop, target, holding in professional:
        presets.append(_preset(
            preset_id, name, "Professional multi-factor", condition,
            "Point-in-time multi-factor setup powered by locally calculated OHLCV indicators.",
            stop=stop, target=target, holding=holding,
        ))
    research_backed = (
        ("tsm_3m_quality", "3-Month Momentum Quality", 'CHANGE_PERCENT(field=ltp, scans_back=63) >= 5 AND technical_sma_200 = "above" AND technical_adx_14 >= 20 AND technical_atr_percent <= 6', 7, 18, 45, "Time-series momentum; Moskowitz, Ooi & Pedersen (2012)."),
        ("tsm_6m_volume", "6-Month Momentum + Volume", 'CHANGE_PERCENT(field=ltp, scans_back=126) >= 10 AND position_in_52_week_range_percent >= 70 AND technical_volume_ratio_20 >= 1.1 AND technical_cmf_20 > 0', 8, 22, 60, "Time-series momentum with NEPSE liquidity confirmation."),
        ("tsm_12m_low_vol", "12-Month Momentum Low Volatility", 'CHANGE_PERCENT(field=ltp, scans_back=252) >= 15 AND technical_sma_200 = "above" AND technical_historical_volatility_20 <= 50 AND technical_atr_percent <= 6', 9, 26, 75, "Long-horizon time-series momentum with volatility control."),
        ("high_52w_accumulation", "52W High Accumulation", 'position_in_52_week_range_percent >= 90 AND technical_cmf_20 >= 0.05 AND technical_volume_ratio_20 >= 1.1 AND technical_sma_50 = "above"', 7, 20, 45, "52-week-high momentum; George & Hwang (2004)."),
        ("high_52w_breakout_adx", "52W High Breakout Strength", 'position_in_52_week_range_percent >= 95 AND technical_adx_14 >= 25 AND technical_plus_di_14 > technical_minus_di_14 AND technical_volume_ratio_20 >= 1.2', 8, 24, 50, "52-week-high momentum with trend-strength and participation filters."),
        ("vol_managed_supertrend", "Volatility-Managed Supertrend", 'technical_historical_volatility_20 <= 40 AND technical_atr_percent <= 4 AND technical_supertrend = "Bullish" AND technical_adx_14 >= 20', 5, 14, 35, "Volatility management; Moreira & Muir (2017), applied conservatively."),
        ("vol_managed_momentum", "Volatility-Managed Momentum", 'technical_historical_volatility_20 <= 45 AND technical_roc_12 >= 3 AND technical_ppo_histogram > 0 AND technical_sma_50 = "above"', 6, 16, 40, "Momentum with a realized-volatility regime filter."),
        ("multi_horizon_ema_stack", "Multi-Horizon EMA Stack", 'technical_ema_20_value > technical_ema_50_value AND technical_ema_50_value > technical_ema_200_value AND technical_ppo_12_26_9 > 0 AND technical_cmf_20 > 0', 7, 20, 50, "Multi-horizon trend persistence with accumulation confirmation."),
        ("donchian_liquid_breakout", "Liquid Donchian Breakout", 'ltp >= technical_donchian_upper_20 AND technical_adx_14 >= 25 AND technical_volume_ratio_20 >= 1.5 AND technical_atr_percent <= 6', 8, 24, 50, "Trend-following breakout with liquidity and volatility controls."),
        ("trend_pullback_accumulation", "Trend Pullback Accumulation", 'technical_sma_200 = "above" AND ltp <= technical_ema_20_value AND ltp > technical_ema_50_value AND technical_rsi_14 BETWEEN 40 AND 55 AND technical_cmf_20 > 0', 5, 15, 35, "Buy-the-pullback setup restricted to an established long-term trend."),
        ("momentum_breadth_confirmation", "Momentum Breadth Confirmation", 'technical_aroon_up_14 >= 70 AND technical_vortex_positive_14 > technical_vortex_negative_14 AND technical_ppo_12_26_9 > 0 AND technical_obv > AVERAGE(field=technical_obv, window=20)', 7, 21, 45, "Independent price-trend and volume-flow confirmations."),
        ("squeeze_trend_regime", "Squeeze Trend Regime", 'technical_squeeze = "Released" AND technical_choppiness_14 < 45 AND technical_supertrend = "Bullish" AND technical_cmf_20 > 0 AND technical_volume_ratio_20 >= 1.1', 7, 22, 45, "Volatility expansion only inside a confirmed directional regime."),
    )
    for preset_id, name, condition, stop, target, holding, research_basis in research_backed:
        presets.append(_preset(
            preset_id, name, "Research-backed multi-factor", condition,
            "Evidence-informed daily setup adapted to point-in-time NEPSE OHLCV data; validate out of sample.",
            stop=stop, target=target, holding=holding, research_basis=research_basis,
        ))
    if len(presets) != 84:
        raise RuntimeError(f"Expected 84 backtest presets, built {len(presets)}")
    return presets


def build_preset_query(preset: Dict[str, Any], symbol: str) -> str:
    return f'''STRATEGY_VERSION 1
SIDE BUY
RULE "{preset["name"]}" FOR SYMBOL "{symbol}" {{
  WHEN {preset["condition"]}
  ORDER PERCENT_OF_AVAILABLE_CASH 100
  EXECUTE MAX 100 TIMES PER SYMBOL
}}'''


def build_backtest_gpt_prompt(symbol: str = "NABIL") -> str:
    clean_symbol = str(symbol or "NABIL").strip().upper()
    return f'''Create a robust NEPSE BUY backtest strategy for symbol "{clean_symbol}".
Return ONLY valid strategy language, with no Markdown fences and no explanation.

Required structure:
STRATEGY_VERSION 1
SIDE BUY
BACKTEST {{
  INITIAL_CAPITAL 100000
  CHARGE_MODEL "nepse_equity"
  INVESTOR_TYPE "individual"
  APPLY_CGT TRUE
  DP_CHARGE 25
  SLIPPAGE_PCT 0.1
  STOP_LOSS_PCT 5
  TAKE_PROFIT_PCT 10
  TRAILING_STOP_PCT 3
  MIN_HOLDING_DAYS 0
  MAX_HOLDING_DAYS 20
  POSITION_SIZE_PCT 100
  MAX_VOLUME_PARTICIPATION_PCT 10
  RISK_FREE_RATE_PCT 4
  DATA_SOURCE "auto"
}}
RULE "Descriptive strategy name" FOR SYMBOL "{clean_symbol}" {{
  WHEN <historical condition>
  ORDER PERCENT_OF_AVAILABLE_CASH 100
  EXECUTE MAX 100 TIMES PER SYMBOL
}}

Historical fields: ltp, open, high, low, volume, previous_close, change, change_percent,
intraday_range_percent, distance_from_open_percent, distance_from_day_high_percent,
distance_from_day_low_percent, position_in_52_week_range_percent, technical_rsi_14,
technical_macd ("Bullish" or "Bearish"), technical_sma_10, technical_sma_20,
technical_sma_50, technical_sma_200 ("above" or "below"), technical_volume_trend.
Calculated numeric indicators also include SMA/EMA value fields, technical_macd_value,
technical_macd_signal_value, technical_macd_histogram, technical_adx_14,
technical_plus_di_14, technical_minus_di_14, technical_stochastic_k_14,
technical_stochastic_d_3, technical_williams_r_14, technical_roc_12,
technical_mfi_14, technical_cci_20, technical_atr_14, technical_atr_percent,
technical_percent_b, Bollinger/Donchian fields, technical_historical_volatility_20,
technical_obv, technical_volume_ratio_20, technical_cmf_20, and transparent
technical_buy_score / technical_sell_score / technical_signal_score fields. Professional
fields include technical_supertrend, technical_hma_20, technical_aroon_up_14,
technical_aroon_down_14, technical_aroon_oscillator_14,
technical_vortex_positive_14, technical_vortex_negative_14,
technical_ppo_12_26_9, technical_ppo_signal_9, technical_ppo_histogram,
technical_choppiness_14, technical_keltner_lower_20,
technical_keltner_middle_20, technical_keltner_upper_20, technical_psar,
technical_psar_value, technical_squeeze, and technical_squeeze_momentum.

Historical functions: PREVIOUS, CHANGE, CHANGE_PERCENT, CONSECUTIVE_DROPS,
CONSECUTIVE_RISES, CROSSES_ABOVE, CROSSES_BELOW, REMAINS_ABOVE, REMAINS_BELOW,
AVERAGE, MIN_VALUE, MAX_VALUE, SUM_VALUE, STDDEV, SLOPE, TREND.
Use uppercase AND/OR, double-quote enum strings and symbols, and realistic risk settings.
Do not use live-only market depth, holdings, REFERENCE, or named USE STRATEGY rules.'''
