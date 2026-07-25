from utils.backtesting.v2_jobs import _scan_key
from utils.backtesting.v2_query import _strategy_planning_range


def _preset():
    return [{"id": "volume_breakout", "source_hash": "preset-v1"}]


def test_all_market_scan_identity_ignores_display_and_universe_growth():
    first = {
        "name": "Morning scan", "run_type": "market_scan", "history_mode": "all_available",
        "start_date": "2018-01-01", "end_date": "2026-07-17", "ordinary_shares_only": True,
    }
    later = {**first, "name": "Renamed scan", "end_date": "2026-07-18"}
    assert _scan_key(first, ["API", "NABIL"], _preset()) == _scan_key(
        later, ["API", "NABIL", "NEWLISTING"], _preset()
    )


def test_explicit_symbol_scan_identity_keeps_requested_scope():
    nabil = {"symbols": ["NABIL"], "ordinary_shares_only": True}
    api = {"symbols": ["API"], "ordinary_shares_only": True}
    assert _scan_key(nabil, ["NABIL"], _preset()) != _scan_key(api, ["API"], _preset())


def test_listing_age_and_liquidity_filters_have_distinct_workspace_identity():
    full_market = {"ordinary_shares_only": True}
    recent_ipos = {**full_market, "max_listing_age_days": 365}
    liquid_recent_ipos = {**recent_ipos, "min_volume": 10000}
    assert _scan_key(full_market, ["NABIL"], _preset()) != _scan_key(
        recent_ipos, ["NABIL"], _preset()
    )
    assert _scan_key(recent_ipos, ["NABIL"], _preset()) != _scan_key(
        liquid_recent_ipos, ["NABIL"], _preset()
    )


def test_strategy_planning_ranges_use_saved_risk_and_not_daily_high_low():
    ranges = _strategy_planning_range({
        "current_signal_status": "buy", "ltp": 100,
        "current_evidence": {"latest_values": {"technical_atr_percent": 4}},
        "assumptions": {"stop_loss_pct": 5, "take_profit_pct": 10},
    })
    assert ranges["buy_zone_low"] == 99
    assert ranges["buy_zone_high"] == 101
    assert ranges["protective_stop"] == 95
    assert ranges["sell_zone_low"] == 109.45
    assert ranges["sell_zone_high"] == 110.55


def test_historical_only_rows_do_not_receive_actionable_price_zones():
    ranges = _strategy_planning_range({"current_signal_status": "no_signal", "ltp": 100})
    assert ranges["buy_zone_low"] is None
    assert ranges["sell_zone_high"] is None
