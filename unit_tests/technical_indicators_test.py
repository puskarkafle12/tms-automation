from dataclasses import dataclass

from utils.technical_indicators import ENGINE_VERSION, INDICATOR_FIELDS, calculate_indicator_rows


@dataclass
class _Bar:
    open: float
    high: float
    low: float
    close: float
    volume: float


def _bars(closes):
    return [_Bar(value - .2, value + .5, value - .5, value, 1000 + index * 25) for index, value in enumerate(closes)]


def test_wilder_rsi_matches_reference_series_and_is_point_in_time():
    # Wilder's commonly published worksheet series; first 14-period RSI is 70.464135.
    closes = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84,
              46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03, 46.41]
    rows = calculate_indicator_rows(_bars(closes))
    assert rows[13]["technical_rsi_14"] is None
    assert abs(rows[14]["technical_rsi_14"] - 70.464135) < 0.00001
    assert calculate_indicator_rows(_bars(closes[:15]))[-1] == rows[14]


def test_complete_indicator_contract_and_scores_are_bounded():
    closes = [100 + index * .4 + ((index % 7) - 3) for index in range(260)]
    row = calculate_indicator_rows(_bars(closes))[-1]
    assert set(row) == set(INDICATOR_FIELDS)
    assert ENGINE_VERSION == "ohlcv-ta-v6-ipo-score-ta-0.11.0"
    assert 0 <= row["technical_buy_score"] <= 100
    assert 0 <= row["technical_sell_score"] <= 100
    assert -100 <= row["technical_signal_score"] <= 100
    assert row["technical_sma_200_value"] is not None
    assert row["technical_adx_14"] is not None
    assert row["technical_supertrend"] in {"Bullish", "Bearish"}
    assert row["technical_hma_20"] is not None
    assert row["technical_aroon_oscillator_14"] is not None
    assert row["technical_vortex_positive_14"] is not None
    assert row["technical_ppo_histogram"] is not None
    assert row["technical_choppiness_14"] is not None
    assert row["technical_keltner_upper_20"] is not None
    assert row["technical_psar"] in {"Bullish", "Bearish"}
    assert row["technical_squeeze"] in {"On", "Released", "Neutral"}
    assert row["technical_kama_10"] is not None
    assert row["technical_ultimate_oscillator_7_14_28"] is not None
    assert row["technical_kst_diff"] is not None
    assert row["technical_ulcer_index_14"] is not None
    assert row["technical_vwap_20"] is not None
    assert row["technical_ichimoku_span_b_52"] is not None
    assert row["technical_efficiency_ratio_20"] is not None
    assert row["technical_close_location_value"] is not None
    assert row["technical_prior_high_20"] is not None
    assert row["technical_fib_retracement_618"] is not None
    assert row["technical_sr_support_confidence"] is not None


def test_support_resistance_and_fibonacci_fields_are_point_in_time():
    closes = [100 + ((index % 18) - 9) * 1.2 + index * .08 for index in range(120)]
    full = calculate_indicator_rows(_bars(closes))
    prefix = calculate_indicator_rows(_bars(closes[:90]))
    fields = [key for key in INDICATOR_FIELDS if key.startswith(("technical_sr_", "technical_fib_"))]
    assert fields
    assert {key: prefix[-1][key] for key in fields} == {key: full[89][key] for key in fields}
