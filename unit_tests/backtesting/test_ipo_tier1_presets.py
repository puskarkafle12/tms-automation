from utils.backtesting.ipo_gate import IPO_WORKSPACE_TRADABILITY_GATE
from utils.backtesting.presets import get_backtest_presets
from utils.technical_indicators import ENGINE_VERSION, calculate_indicator_rows


TIER1_IDS = {
    "ipo_tier1_subscription_sector_flip",
    "ipo_tier1_controlled_momentum_recovery",
    "ipo_tier1_first_base_vwap_breakout",
    "ipo_tier1_recovery_score_strong",
}


def test_tier1_ipo_presets_keep_shared_red_candle_buy_gate():
    presets = {item["id"]: item for item in get_backtest_presets()}
    assert TIER1_IDS <= set(presets)
    for preset_id in TIER1_IDS:
        preset = presets[preset_id]
        assert preset["family"] == "new_ipo_aftermarket"
        assert preset["tier"] == "ipo_tier1_research"
        assert preset["recommended_listing_age_days"] in {90, 180, 365, 730}
        assert IPO_WORKSPACE_TRADABILITY_GATE in preset["condition"]
        assert "PREVIOUS(field=ltp, offset=1) < PREVIOUS(field=open, offset=1)" in preset["condition"]


def test_ipo_recovery_score_is_causal_and_bounded():
    assert "ipo-score" in ENGINE_VERSION
    rows = []
    price = 100.0
    for index in range(80):
        open_price = price
        close = price * (1.01 if index % 3 else 0.99)
        high = max(open_price, close) * 1.01
        low = min(open_price, close) * 0.99
        rows.append({
            "open": open_price, "high": high, "low": low, "ltp": close,
            "volume": 5_000 + index * 100,
        })
        price = close
    indicators = calculate_indicator_rows(rows)
    scores = [float(row["technical_ipo_recovery_score"] or 0) for row in indicators]
    assert max(scores) <= 10
    assert min(scores) >= 0
    assert any(score > 0 for score in scores[-20:])
