from copy import deepcopy

from utils.backtesting.accelerated import compile_preset_exit_signals, compile_preset_signals
from utils.backtesting.presets import get_backtest_presets


def _rows(count=40):
    return [{
        "ltp": 100 + index, "change_percent": 1, "volume": 1000,
        "technical_rsi_14": 20 if index == 20 else 55,
        "position_in_52_week_range_percent": 50,
        "technical_macd": "Bullish", "technical_sma_20": "above",
        "technical_sma_50": "above", "technical_sma_10": "above", "technical_sma_200": "above",
        "technical_adx_14": 25, "technical_plus_di_14": 30, "technical_minus_di_14": 15,
        "technical_volume_ratio_20": 1.3, "technical_hma_20": 99 + index,
        "technical_ppo_12_26_9": 1, "technical_ppo_histogram": .5,
        "technical_aroon_up_14": 80, "technical_aroon_oscillator_14": 60,
        "technical_vortex_positive_14": 1.2, "technical_vortex_negative_14": .8,
        "technical_squeeze_momentum": 1, "technical_cmf_20": .2,
        "technical_keltner_middle_20": 101 + index,
        "technical_keltner_upper_20": 99 + index,
        "technical_choppiness_14": 30, "technical_atr_percent": 3,
        "technical_supertrend": "Bullish", "technical_psar": "Bullish",
        "technical_squeeze": "Released",
    } for index in range(count)]


def test_compiled_level_signals_fire_only_on_transition():
    signals = compile_preset_signals("rsi_momentum_50", _rows())
    assert signals[0] is True
    assert sum(signals) == 2  # recovers from the one deliberately oversold session


def test_changing_future_data_does_not_change_earlier_signals():
    original = _rows()
    changed = deepcopy(original)
    for row in changed[30:]:
        row.update({"ltp": 1_000_000, "volume": 9_999_999, "technical_rsi_14": 1})
    before = compile_preset_signals("volume_surge_3", original)
    after = compile_preset_signals("volume_surge_3", changed)
    assert before[:30] == after[:30]


def test_every_catalog_preset_has_an_accelerated_compiler():
    rows = _rows(80)
    for preset in get_backtest_presets():
        signals = compile_preset_signals(preset["id"], rows)
        assert len(signals) == len(rows)


def test_paired_exit_compilers_use_the_selected_sell_rule():
    rows = _rows(3)
    rows[1].update({
        "ltp": 120,
        "technical_bollinger_middle_20": 110,
        "technical_bollinger_upper_20": 125,
        "technical_fib_resistance_exit": 1,
        "technical_sr_resistance_rejection": 0,
    })
    bollinger = compile_preset_exit_signals("bollinger_lower_recovery_middle", rows)
    fibonacci = compile_preset_exit_signals("fibonacci_pullback_resistance", rows)
    assert bollinger == [False, True, False]
    assert fibonacci == [False, True, False]
