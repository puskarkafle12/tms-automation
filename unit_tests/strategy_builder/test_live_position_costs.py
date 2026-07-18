from datetime import date, datetime, timedelta, timezone

from utils.strategy_builder.derived_fields import compute_position_performance_fields


def test_live_profit_percent_is_net_of_nepse_charges_and_uses_calendar_tax_age():
    entry_date = date.today() - timedelta(days=400)
    metrics = compute_position_performance_fields(
        {"ltp": 550},
        {
            "entry_price": 500,
            "entry_at": datetime.combine(entry_date, datetime.min.time(), tzinfo=timezone.utc).isoformat(),
            "apply_nepse_charges": True,
            "charge_model": "nepse_equity_v2024_05_14",
            "investor_type": "individual",
            "apply_cgt": True,
            "dp_charge": 25,
            # Trading-session age is not the calendar-day CGT holding period.
            "holding_days": 5,
        },
        qty=100,
    )
    assert metrics["gross_profit_percent"] == 10.0
    assert metrics["profit_percent"] < metrics["gross_profit_percent"]
    assert metrics["estimated_buy_charges"] > 0
    assert metrics["estimated_total_sell_charges"] > 25
    assert metrics["charge_holding_days"] >= 400
