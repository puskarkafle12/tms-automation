"""Curated, auditable backtest presets built only from historical-safe fields."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List


def _preset(
    preset_id: str, name: str, category: str, condition: str, description: str,
    *, stop: float = 5, target: float = 10, holding: int = 20, research_basis: str = "",
    exit_rule_id: str | None = None, exit_condition: str | None = None,
) -> Dict[str, Any]:
    if not exit_rule_id or not exit_condition:
        category_key = category.lower()
        if "mean reversion" in category_key or category_key == "rsi":
            exit_rule_id = "momentum_rollover_exit"
            exit_condition = "technical_rsi_14 >= 65 AND technical_ppo_histogram < 0"
        elif "volume" in category_key:
            exit_rule_id = "flow_breakdown_exit"
            exit_condition = "technical_cmf_20 < 0 AND technical_plus_di_14 < technical_minus_di_14"
        else:
            exit_rule_id = "trend_breakdown_exit"
            exit_condition = 'ltp < technical_ema_20_value AND technical_macd = "Bearish"'
    source_hash = hashlib.sha256(
        f"{condition}|{exit_rule_id}|{exit_condition}|{stop}|{target}|{holding}|paired-every-match-v4".encode("utf-8")
    ).hexdigest()
    return {
        "id": preset_id,
        "name": name,
        "category": category,
        "condition": condition,
        "description": description,
        "research_basis": research_basis,
        "family": preset_id.rsplit("_", 1)[0],
        "version": "preset-v4", "source_hash": source_hash,
        "exit_rule_id": exit_rule_id, "exit_condition": exit_condition,
        "defaults": {"stop_loss_pct": stop, "take_profit_pct": target, "max_holding_days": holding},
    }


def _supplied_nepse15_preset(
    number: int, name: str, stop: float, target: float, holding: int,
    *, trailing: float | None = None, limitation: str = "",
) -> Dict[str, Any]:
    """Create one executable, content-addressed member of the supplied set."""
    condition = f"technical_nepse15_entry_{number} = 1"
    exit_condition = f"technical_nepse15_exit_{number} = 1"
    preset = _preset(
        f"nepse15_{number:02d}", name, "User-supplied NEPSE 15", condition,
        "Completed-session OHLCV setup with its own condition exit, conservative daily execution, and Nepal charges.",
        stop=stop, target=target, holding=holding,
        research_basis=(
            "User-supplied research hypothesis; require locked OOS and walk-forward validation. "
            "The common NEPSE-index-above-EMA50 gate is intentionally not asserted until a versioned "
            "point-in-time index series is stored. " + limitation
        ),
    )
    preset["family"] = "user_supplied_nepse15"
    preset["version"] = "nepse15-v1"
    preset["exit_rule_id"] = f"nepse15_exit_{number}"
    preset["exit_condition"] = exit_condition
    preset["order_clause"] = "RISK_PERCENT 1"
    preset["enforce_preset_holding"] = True
    preset["defaults"]["min_holding_days"] = 5
    recommended_order = {1: 1, 2: 2, 6: 3, 4: 4, 15: 5}
    preset["team_recommended_priority"] = recommended_order.get(number)
    if trailing is not None:
        preset["defaults"]["trailing_stop_pct"] = trailing
    identity = {
        "condition": condition, "exit_condition": exit_condition,
        "defaults": preset["defaults"], "order_clause": preset["order_clause"],
        "engine": "nepse15-v1",
    }
    preset["source_hash"] = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return preset


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

    price_action = (
        ("pa_engulfing_trend_volume", "Engulfing Trend + Volume", 'technical_bullish_engulfing = 1 AND technical_sma_200 = "above" AND technical_volume_ratio_20 >= 1.1 AND technical_rsi_14 BETWEEN 35 AND 65', 5, 14, 25),
        ("pa_hammer_trend_reclaim", "Hammer Trend Reclaim", 'technical_hammer = 1 AND ltp > technical_ema_50_value AND technical_sma_200 = "above" AND technical_close_location_value >= 0.65 AND technical_cmf_20 > 0', 5, 13, 25),
        ("pa_inside_bar_trend", "Inside-Bar Trend Compression", 'technical_inside_bar = 1 AND technical_ema_20_value > technical_ema_50_value AND technical_adx_14 >= 20 AND technical_volume_ratio_20 <= 1.2', 5, 15, 30),
        ("pa_outside_bar_momentum", "Outside-Bar Momentum", 'technical_outside_bar = 1 AND technical_close_location_value >= 0.75 AND technical_candle_body_percent >= 1 AND technical_volume_ratio_20 >= 1.2', 6, 16, 30),
        ("pa_marubozu_participation", "Marubozu Participation", 'technical_bullish_marubozu = 1 AND technical_volume_ratio_20 >= 1.3 AND technical_adx_14 >= 20 AND technical_atr_percent <= 7', 6, 17, 30),
        ("pa_20d_breakout_volume", "20-Day Price + Volume Breakout", 'technical_breakout_20 = 1 AND technical_volume_ratio_20 >= 1.5 AND technical_adx_14 >= 20 AND technical_atr_percent <= 7', 7, 20, 40),
        ("pa_false_breakdown_reclaim", "False-Breakdown Reclaim", 'low < technical_prior_low_20 AND ltp > technical_prior_low_20 AND technical_close_location_value >= 0.7 AND technical_volume_ratio_20 >= 1.1', 5, 14, 25),
        ("pa_higher_high_low_continuation", "Higher-High / Higher-Low Continuation", 'technical_higher_high_3 = 1 AND technical_higher_low_3 = 1 AND technical_ema_20_value > technical_ema_50_value AND technical_cmf_20 > 0', 6, 17, 35),
        ("pa_gap_momentum", "Gap Momentum Confirmation", 'technical_gap_percent >= 1 AND technical_close_location_value >= 0.7 AND technical_volume_ratio_20 >= 1.3 AND technical_sma_50 = "above"', 6, 16, 25),
        ("pa_vwap_reclaim", "20-Day VWAP Reclaim", 'ltp > technical_vwap_20 AND technical_price_zscore_20 <= 1.5 AND technical_cmf_20 > 0 AND change_percent > 0', 5, 14, 25),
    )
    for preset_id, name, condition, stop, target, holding in price_action:
        presets.append(_preset(
            preset_id, name, "Price action + regime", condition,
            "Daily candle or structure signal confirmed by trend, participation, or liquidity context.",
            stop=stop, target=target, holding=holding,
            research_basis="Candlestick and price-action hypotheses require regime confirmation and out-of-sample validation.",
        ))

    price_volume_research = (
        ("pv_dryup_trend_pullback", "Volume Dry-Up Trend Pullback", 'ltp <= technical_ema_20_value AND ltp > technical_ema_50_value AND technical_ema_20_value > technical_ema_50_value AND technical_volume_ratio_20 <= 0.75 AND technical_rsi_14 BETWEEN 40 AND 60', 5, 15, 30, "Low-participation pullback inside an established daily uptrend."),
        ("pv_obv_breakout", "OBV Participation Breakout", 'technical_breakout_20 = 1 AND technical_obv > AVERAGE(field=technical_obv, window=20) AND technical_volume_ratio_20 >= 1.3 AND technical_close_location_value >= 0.7', 7, 20, 40, "Range breakout confirmed by independent volume-flow and closing-strength measures."),
        ("pv_52w_high_volume", "52W High + Volume Momentum", 'position_in_52_week_range_percent >= 85 AND change_percent >= 1 AND technical_volume_ratio_20 >= 1.5 AND technical_cmf_20 > 0', 7, 21, 45, "52-week-high momentum with high-volume accumulation confirmation."),
        ("pv_squeeze_breakout", "Squeeze + Volume Breakout", 'technical_squeeze = "Released" AND technical_breakout_20 = 1 AND technical_volume_ratio_20 >= 1.5 AND technical_choppiness_14 < 45', 7, 22, 40, "Volatility expansion, range escape, and participation must agree on the same completed session."),
        ("pv_engulfing_accumulation", "Engulfing Accumulation", 'technical_bullish_engulfing = 1 AND ltp > technical_ema_50_value AND technical_cmf_20 >= 0.05 AND technical_volume_ratio_20 >= 1.2', 5, 15, 30, "Bullish reversal candle restricted to positive money flow and above-average volume."),
        ("pv_liquid_momentum_risk", "Liquid Momentum Risk Control", 'CHANGE_PERCENT(field=ltp, scans_back=63) BETWEEN 5 AND 25 AND technical_volume_ratio_20 >= 1.2 AND technical_atr_percent <= 5 AND technical_adx_14 >= 20 AND technical_sma_200 = "above"', 6, 18, 45, "Medium-horizon momentum with liquidity, volatility, trend, and crash-risk controls."),
        ("pv_vwap_obv_reclaim", "VWAP + OBV Reclaim", 'ltp > technical_vwap_20 AND technical_obv > AVERAGE(field=technical_obv, window=20) AND technical_cmf_20 > 0 AND technical_volume_ratio_20 >= 1.1', 5, 16, 30, "Fair-value reclaim confirmed by two independent accumulation measures."),
        ("pv_cmf_low_chop_breakout", "CMF Low-Chop Breakout", 'technical_breakout_20 = 1 AND technical_cmf_20 >= 0.1 AND technical_choppiness_14 < 40 AND technical_volume_ratio_20 >= 1.25', 7, 21, 40, "Range escape requires accumulation, participation, and a non-choppy regime."),
        ("pv_force_kama_impulse", "Force + KAMA Impulse", 'technical_force_index_13 > 0 AND ltp > technical_kama_10 AND technical_ppo_histogram > 0 AND technical_volume_ratio_20 >= 1.1', 6, 18, 35, "Volume-weighted price impulse aligned with an adaptive trend and momentum."),
        ("pv_donchian_low_vol", "Donchian Low-Vol Participation", 'ltp >= technical_donchian_upper_20 AND technical_volume_ratio_20 >= 1.3 AND technical_historical_volatility_20 <= 40 AND technical_atr_percent <= 5', 6, 19, 40, "Liquid breakout filtered against excessive historical and current volatility."),
        ("pv_supertrend_squeeze_flow", "Supertrend Squeeze Flow", 'technical_supertrend = "Bullish" AND technical_squeeze = "Released" AND technical_cmf_20 > 0 AND technical_volume_ratio_20 >= 1.2', 7, 20, 40, "Trend, volatility expansion, money flow, and participation must align."),
        ("pv_multi_horizon_flow", "Multi-Horizon Momentum Flow", 'CHANGE_PERCENT(field=ltp, scans_back=63) >= 5 AND CHANGE_PERCENT(field=ltp, scans_back=126) >= 10 AND technical_cmf_20 > 0 AND technical_volume_ratio_20 >= 1.1 AND technical_sma_200 = "above"', 7, 22, 60, "Three- and six-month momentum confirmed by long trend and current accumulation."),
    )
    for preset_id, name, condition, stop, target, holding, research_basis in price_volume_research:
        presets.append(_preset(
            preset_id, name, "Price-volume research", condition,
            "Evidence-informed daily OHLCV hypothesis; rank by locked out-of-sample results, not headline win rate.",
            stop=stop, target=target, holding=holding, research_basis=research_basis,
        ))

    adaptive_regime = (
        ("ichimoku_cloud_adx", "Ichimoku Cloud + ADX", 'ltp > technical_ichimoku_span_a_26 AND ltp > technical_ichimoku_span_b_52 AND technical_ichimoku_conversion_9 > technical_ichimoku_base_26 AND technical_adx_14 >= 20', 7, 20, 45, "Multi-horizon trend state with independent trend-strength confirmation."),
        ("kama_adaptive_momentum", "KAMA Adaptive Momentum", 'ltp > technical_kama_10 AND SLOPE(field=technical_kama_10, window=5, operator="gt", threshold=0) AND technical_ppo_histogram > 0 AND technical_efficiency_ratio_20 >= 0.3', 6, 17, 35, "Adaptive trend filter with path-efficiency and momentum confirmation."),
        ("kst_multi_cycle_trend", "KST Multi-Cycle Trend", 'technical_kst_diff > 0 AND technical_kst > 0 AND technical_sma_200 = "above" AND technical_cmf_20 > 0', 7, 20, 45, "Multiple rate-of-change horizons combined with accumulation and long-trend filters."),
        ("trix_volume_trend", "TRIX Volume Trend", 'technical_trix_15 > 0 AND technical_ppo_histogram > 0 AND technical_volume_ratio_20 >= 1.1 AND technical_sma_50 = "above"', 6, 18, 35, "Triple-smoothed trend momentum with price and volume confirmation."),
        ("ultimate_pullback_trend", "Ultimate-Oscillator Trend Pullback", 'technical_ultimate_oscillator_7_14_28 BETWEEN 40 AND 60 AND technical_sma_200 = "above" AND ltp > technical_ema_50_value AND change_percent > 0', 5, 15, 30, "Multi-window momentum pullback restricted to a positive long-term regime."),
        ("force_index_breakout", "Force-Index Breakout", 'technical_force_index_13 > 0 AND technical_breakout_20 = 1 AND technical_volume_ratio_20 >= 1.2 AND technical_adx_14 >= 20', 7, 20, 40, "Price-volume impulse confirms a prior-range breakout."),
        ("efficiency_trend_defense", "Efficient Trend Defense", 'technical_efficiency_ratio_20 >= 0.35 AND technical_choppiness_14 < 45 AND technical_ema_20_value > technical_ema_50_value AND technical_ema_50_value > technical_ema_200_value AND technical_ppo_histogram > 0', 6, 19, 45, "Trend-quality defenses reduce exposure to noisy or broken trends."),
        ("low_ulcer_momentum", "Low-Ulcer Momentum", 'technical_ulcer_index_14 <= 8 AND CHANGE_PERCENT(field=ltp, scans_back=63) >= 5 AND technical_sma_200 = "above" AND technical_atr_percent <= 5', 6, 18, 45, "Medium-horizon momentum filtered by downside-risk and daily volatility."),
        ("vpt_vwap_confirmation", "VPT + VWAP Confirmation", 'technical_volume_price_trend > AVERAGE(field=technical_volume_price_trend, window=20) AND ltp > technical_vwap_20 AND technical_cmf_20 > 0 AND technical_sma_50 = "above"', 6, 18, 40, "Independent volume-price flow, fair-value, and trend confirmations."),
        ("nonlinear_momentum_regime", "Nonlinear Momentum Regime", 'CHANGE_PERCENT(field=ltp, scans_back=63) BETWEEN 5 AND 25 AND CHANGE_PERCENT(field=ltp, scans_back=126) >= 10 AND technical_historical_volatility_20 <= 45 AND technical_adx_14 >= 20 AND technical_sma_200 = "above"', 8, 24, 60, "Bounded multi-horizon momentum avoids extrapolating the strongest moves without risk controls."),
    )
    for preset_id, name, condition, stop, target, holding, research_basis in adaptive_regime:
        presets.append(_preset(
            preset_id, name, "2026 adaptive multi-factor", condition,
            "Evidence-informed daily multi-factor hypothesis using point-in-time OHLCV indicators; validate on locked data.",
            stop=stop, target=target, holding=holding, research_basis=research_basis,
        ))

    # Structural entry hypotheses. The professional runner searches all
    # approved SELL rules and stop methods per stock, so each entry condition
    # appears once in the catalog and produces one selected champion.
    paired_zone_and_band = (
        ("sr_bounce_resistance_exit", "Support Zone Bounce · Adaptive Protection",
         "technical_sr_support_bounce = 1 AND technical_sma_200 = \"above\"",
         "Causal ATR-clustered multi-touch support bounce; exits on a confirmed resistance-zone rejection.",
         6, 16, 35, "sr_resistance_rejection_exit", "technical_sr_resistance_rejection = 1"),
        ("sr_breakout_participation", "Resistance Breakout Participation",
         "technical_sr_resistance_breakout = 1 AND technical_adx_14 >= 20",
         "Closes above a causal resistance zone with volume participation and trend strength.",
         7, 20, 45, "trend_breakdown_exit", 'ltp < technical_ema_20_value AND technical_macd = "Bearish"'),
        ("bollinger_lower_recovery_middle", "Bollinger Lower-Band Recovery · Adaptive Protection",
         "technical_percent_b BETWEEN 0 AND 0.25 AND change_percent > 0 AND technical_rsi_14 BETWEEN 30 AND 50",
         "Mean-reversion recovery inside the lower Bollinger quartile; exits at the rolling middle band.",
         5, 12, 25, "bollinger_middle_exit", "ltp >= technical_bollinger_middle_20"),
        ("bollinger_trend_pullback", "Bollinger Trend Pullback",
         "technical_percent_b BETWEEN 0.10 AND 0.40 AND technical_supertrend = \"Bullish\" AND technical_cmf_20 > 0",
         "Lower-band pullback restricted to bullish trend and positive money flow.",
         5, 15, 30, "trend_breakdown_exit", 'ltp < technical_ema_20_value AND technical_macd = "Bearish"'),
        ("bollinger_squeeze_paired_exit", "Bollinger Squeeze Breakout · Adaptive Protection",
         "technical_squeeze = \"Released\" AND ltp > technical_bollinger_upper_20 AND technical_volume_ratio_20 >= 1.3",
         "Volatility expansion with participation, paired with loss of the middle band.",
         7, 20, 40, "bollinger_middle_break_exit", "ltp < technical_bollinger_middle_20"),
        ("fibonacci_pullback_resistance", "Fibonacci Pullback · Adaptive Protection",
         "technical_fib_pullback_entry = 1",
         "Past-only 63-session 50–61.8% retracement recovery with a range-resistance exit.",
         6, 18, 40, "fibonacci_resistance_exit", "technical_fib_resistance_exit = 1"),
        ("fibonacci_volume_confirmation", "Fibonacci Pullback + Volume",
         "technical_fib_pullback_entry = 1 AND technical_cmf_20 > 0 AND technical_volume_ratio_20 >= 1.1",
         "Fibonacci retracement recovery confirmed by money flow and participation.",
         6, 20, 45, "fibonacci_resistance_exit", "technical_fib_resistance_exit = 1"),
        ("zone_bollinger_confluence", "Support Zone + Bollinger Confluence",
         "technical_sr_support_bounce = 1 AND technical_percent_b <= 0.35 AND technical_cmf_20 > 0",
         "Independent structural support, volatility-band location, and money-flow confirmation.",
         5, 16, 35, "sr_resistance_rejection_exit", "technical_sr_resistance_rejection = 1"),
        ("zone_momentum_quality", "Support Zone + Momentum Quality",
         "technical_sr_support_bounce = 1 AND technical_ppo_histogram > 0 AND technical_adx_14 >= 18",
         "Structural support bounce confirmed by improving momentum and trend strength.",
         6, 18, 40, "dual_trend_exit", 'technical_supertrend = "Bearish" AND technical_psar = "Bearish"'),
    )
    for preset_id, name, condition, description, stop, target, holding, exit_rule_id, exit_condition in paired_zone_and_band:
        presets.append(_preset(
            preset_id, name, "Adaptive entry + sell/stop search", condition, description,
            stop=stop, target=target, holding=holding,
            exit_rule_id=exit_rule_id, exit_condition=exit_condition,
            research_basis=(
                "Causal daily hypothesis. Select the BUY/SELL pair by locked out-of-sample "
                "profitability and false-breakout behavior, not in-sample win rate."
            ),
        ))

    supplied_nepse15 = (
        (1, "Trend Pullback + ADX + Volume", 6, 10, 20, None, "ATR distances are represented by conservative percentage risk controls in the current daily simulator."),
        (2, "20-Session High Breakout + Volume", 8, 12, 30, 8, "ATR distances are represented by conservative percentage risk controls in the current daily simulator."),
        (3, "MACD Momentum + Trend Filter", 6, 9, 15, None, "ATR distances are represented by conservative percentage risk controls in the current daily simulator."),
        (4, "RSI Oversold Pullback in Uptrend", 5, 10, 12, None, "Two-stage profit scaling is represented by one conservative portfolio exit."),
        (5, "52-Week High Breakout", 8, 16, 40, 10, "ATR distances are represented by conservative percentage risk controls in the current daily simulator."),
        (6, "EMA 10/30 Crossover + ADX", 6, 10, 25, None, "ATR distances are represented by conservative percentage risk controls in the current daily simulator."),
        (7, "Bollinger Band Squeeze Breakout", 6, 12, 20, None, "ATR distances are represented by conservative percentage risk controls in the current daily simulator."),
        (8, "Ichimoku Cloud Breakout", 8, 12, 30, None, "Uses non-displaced, past-only cloud values to avoid look-ahead."),
        (9, "Donchian 20/10 Trend Strategy", 8, 24, 40, 10, "No fixed target is used conceptually; the high target leaves the condition exit in control."),
        (10, "Support Bounce + Bullish Candle", 6, 15, 15, None, "Support is the prior 20-session low with two prior 1.5% tests."),
        (11, "Stochastic Pullback Continuation", 6, 15, 15, None, "Swing-low ATR placement is represented by conservative percentage risk controls."),
        (12, "OBV Accumulation Breakout", 8, 16, 25, None, "The consolidation-height target is represented by a conservative percentage target."),
        (13, "Five-Session Momentum + Pullback", 6, 15, 15, None, "Pullback-low ATR placement is represented by conservative percentage risk controls."),
        (14, "Volatility Contraction Pattern", 7, 21, 30, 7, "Contractions are deterministic non-overlapping five-session ranges."),
        (15, "Relative-Strength Leader Strategy", 8, 24, 40, 10, "Uses absolute 20/60-session strength until versioned NEPSE index history is available."),
    )
    presets.extend(
        _supplied_nepse15_preset(number, name, stop, target, holding, trailing=trailing, limitation=limitation)
        for number, name, stop, target, holding, trailing, limitation in supplied_nepse15
    )

    if len(presets) != 140:
        raise RuntimeError(f"Expected 140 unique-entry backtest presets, built {len(presets)}")
    identities: Dict[str, str] = {}
    for preset in presets:
        prior = identities.setdefault(str(preset["source_hash"]), str(preset["id"]))
        if prior != preset["id"]:
            raise RuntimeError(f"Duplicate executable presets: {prior} and {preset['id']}")
    return presets


def build_preset_query(
    preset: Dict[str, Any], symbol: str, *, backtest_config: Dict[str, Any] | None = None,
) -> str:
    defaults = preset.get("defaults") or {}
    config = {
        "initial_capital": 100000, "charge_model": "nepse_equity",
        "investor_type": "individual", "apply_cgt": True, "dp_charge": 25,
        "fee_pct": .4, "fixed_fee": 0, "slippage_pct": .1,
        "stop_loss_pct": defaults.get("stop_loss_pct", 5),
        "take_profit_pct": defaults.get("take_profit_pct", 10),
        "min_holding_days": defaults.get("min_holding_days", 5),
        "max_holding_days": defaults.get("max_holding_days", 90),
        "position_size_pct": 100, "max_volume_participation_pct": 10,
        "risk_free_rate_pct": 4, "data_source": "auto",
        "trailing_stop_pct": defaults.get("trailing_stop_pct"),
    }
    config.update(backtest_config or {})
    trailing_stop = (
        f'  TRAILING_STOP_PCT {float(config["trailing_stop_pct"]):g}\n'
        if config.get("trailing_stop_pct") is not None else ""
    )
    return f'''STRATEGY_VERSION 1
SIDE BUY
BACKTEST {{
  INITIAL_CAPITAL {float(config["initial_capital"]):g}
  CHARGE_MODEL "{config["charge_model"]}"
  INVESTOR_TYPE "{config["investor_type"]}"
  APPLY_CGT {"TRUE" if config["apply_cgt"] else "FALSE"}
  DP_CHARGE {float(config["dp_charge"]):g}
  FEE_PCT {float(config["fee_pct"]):g}
  FIXED_FEE {float(config["fixed_fee"]):g}
  SLIPPAGE_PCT {float(config["slippage_pct"]):g}
  STOP_LOSS_PCT {float(config["stop_loss_pct"]):g}
  TAKE_PROFIT_PCT {float(config["take_profit_pct"]):g}
{trailing_stop}  MIN_HOLDING_DAYS {int(config["min_holding_days"])}
  MAX_HOLDING_DAYS {int(config["max_holding_days"])}
  POSITION_SIZE_PCT {float(config["position_size_pct"]):g}
  MAX_VOLUME_PARTICIPATION_PCT {float(config["max_volume_participation_pct"]):g}
  RISK_FREE_RATE_PCT {float(config["risk_free_rate_pct"]):g}
  DATA_SOURCE "{config["data_source"]}"
}}
RULE "{preset["name"]}" FOR SYMBOL "{symbol}" {{
  WHEN {preset["condition"]}
  ORDER {preset.get("order_clause") or "PERCENT_OF_AVAILABLE_CASH 100"}
  EXECUTE ON EVERY MATCH
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
  MIN_HOLDING_DAYS 5
  MAX_HOLDING_DAYS 90
  POSITION_SIZE_PCT 100
  MAX_VOLUME_PARTICIPATION_PCT 10
  RISK_FREE_RATE_PCT 4
  DATA_SOURCE "auto"
}}
RULE "Descriptive strategy name" FOR SYMBOL "{clean_symbol}" {{
  WHEN <historical condition>
  ORDER PERCENT_OF_AVAILABLE_CASH 100
  EXECUTE ON EVERY MATCH
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
Adaptive and price-action fields include technical_kama_10,
technical_ultimate_oscillator_7_14_28, technical_trix_15, technical_kst,
technical_kst_signal, technical_kst_diff, technical_mass_index_9_25,
technical_ulcer_index_14, technical_force_index_13, technical_volume_price_trend,
technical_vwap_20, technical_ichimoku_conversion_9, technical_ichimoku_base_26,
technical_ichimoku_span_a_26, technical_ichimoku_span_b_52,
technical_price_zscore_20, technical_efficiency_ratio_20,
technical_candle_body_percent, technical_upper_wick_percent,
technical_lower_wick_percent, technical_close_location_value,
technical_gap_percent, technical_prior_high_20, technical_prior_low_20,
technical_breakout_20, technical_breakdown_20, technical_bullish_engulfing,
technical_hammer, technical_inside_bar, technical_outside_bar,
technical_bullish_marubozu, technical_higher_high_3, and technical_higher_low_3.

Historical functions: PREVIOUS, CHANGE, CHANGE_PERCENT, CONSECUTIVE_DROPS,
CONSECUTIVE_RISES, CROSSES_ABOVE, CROSSES_BELOW, REMAINS_ABOVE, REMAINS_BELOW,
AVERAGE, MIN_VALUE, MAX_VALUE, SUM_VALUE, STDDEV, SLOPE, TREND.
Use uppercase AND/OR, double-quote enum strings and symbols, and realistic risk settings.
Do not use live-only market depth, holdings, REFERENCE, or named USE STRATEGY rules.'''
