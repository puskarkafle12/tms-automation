from utils.backtesting.ipo_gate import (
    IPO_WORKSPACE_GATE_VERSION,
    IPO_WORKSPACE_TRADABILITY_GATE,
    strip_ipo_tradability_gates,
)


def test_ipo_gate_is_prior_red_candle_only():
    assert IPO_WORKSPACE_GATE_VERSION == "ipo-red-close-v5"
    assert IPO_WORKSPACE_TRADABILITY_GATE == (
        "PREVIOUS(field=ltp, offset=1) < PREVIOUS(field=open, offset=1)"
    )
    assert "change_percent" not in IPO_WORKSPACE_TRADABILITY_GATE
    assert "volume" not in IPO_WORKSPACE_TRADABILITY_GATE


def test_strip_removes_legacy_and_current_ipo_gates():
    legacy = (
        "(technical_rsi_14 < 40) AND PREVIOUS(field=change_percent, offset=1) <= -4 "
        "AND PREVIOUS(field=volume, offset=1) > 5000 "
        "AND PREVIOUS(field=ltp, offset=1) < PREVIOUS(field=open, offset=1)"
    )
    cleaned = strip_ipo_tradability_gates(legacy)
    assert cleaned == "technical_rsi_14 < 40"
    assert strip_ipo_tradability_gates(
        f"({cleaned}) AND {IPO_WORKSPACE_TRADABILITY_GATE}"
    ) == "technical_rsi_14 < 40"
