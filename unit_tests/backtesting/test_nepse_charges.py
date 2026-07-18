from datetime import date

import pytest

from utils.backtesting.nepse_charges import (
    broker_commission,
    buy_charges,
    capital_gains_tax_rate,
    equity_brokerage_rate,
    maximum_affordable_quantity,
    sell_charges,
)


@pytest.mark.parametrize(("amount", "rate"), [
    (50_000, .0036), (50_001, .0033), (500_000, .0033), (500_001, .0031),
    (2_000_000, .0031), (2_000_001, .0027), (10_000_000, .0027), (10_000_001, .0024),
])
def test_current_equity_brokerage_slabs(amount, rate):
    assert equity_brokerage_rate(amount, date(2025, 1, 1)) == rate


def test_historical_brokerage_schedule_and_minimum_fee():
    assert equity_brokerage_rate(100_000, date(2024, 5, 13)) == .0037
    assert equity_brokerage_rate(100_000, date(2024, 5, 14)) == .0033
    assert broker_commission(1_000, date(2025, 1, 1)) == 10


def test_buy_side_contains_brokerage_and_sebon_but_no_dp_or_tax():
    charges = buy_charges(100_000, date(2025, 1, 1))
    assert charges["broker_commission"] == pytest.approx(330)
    assert charges["sebon_fee"] == pytest.approx(15)
    assert charges["dp_charge"] == 0
    assert charges["capital_gains_tax"] == 0
    assert charges["total"] == pytest.approx(345)


def test_profitable_short_term_sell_applies_dp_and_cgt_after_costs():
    sell = sell_charges(
        125_000, date(2025, 6, 1), entry_total_cost=100_345,
        holding_days=120, investor_type="individual",
    )
    assert sell["broker_commission"] == pytest.approx(412.5)
    assert sell["sebon_fee"] == pytest.approx(18.75)
    assert sell["dp_charge"] == 25
    assert sell["profit_before_tax"] == pytest.approx(24_198.75)
    assert sell["capital_gains_tax"] == pytest.approx(1_814.90625)
    assert sell["total"] == pytest.approx(2_271.15625)


def test_loss_has_no_cgt_and_holding_period_rates_are_explicit():
    sell = sell_charges(90_000, date(2025, 6, 1), entry_total_cost=100_345, holding_days=20)
    assert sell["capital_gains_tax"] == 0
    assert capital_gains_tax_rate("individual", 365) == .075
    assert capital_gains_tax_rate("individual", 366) == .05
    assert capital_gains_tax_rate("institution", 10) == .10


def test_affordable_quantity_includes_buy_charges():
    quantity = maximum_affordable_quantity(100_000, 1_000, date(2025, 1, 1))
    assert quantity == 99
    gross = quantity * 1_000
    assert gross + buy_charges(gross, date(2025, 1, 1))["total"] <= 100_000
