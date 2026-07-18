"""Versioned Nepal secondary-market charge calculations for backtesting.

The equity brokerage schedule changes on 2024-05-14.  CGT uses the current
listed-security rates selected by investor type and holding period.  All values
are kept at full precision while simulating and rounded only for presentation.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict


NEPSE_EQUITY_CHARGE_MODEL = "nepse_equity_v2024_05_14"
LEGACY_FLAT_CHARGE_MODEL = "legacy_flat"
BROKERAGE_CHANGE_DATE = date(2024, 5, 14)
SEBON_RATE = 0.00015
DEFAULT_DP_CHARGE = 25.0
MINIMUM_BROKER_COMMISSION = 10.0


def normalize_charge_model(value: str | None) -> str:
    normalized = str(value or NEPSE_EQUITY_CHARGE_MODEL).strip().lower()
    if normalized in {"nepse", "nepse_equity", "official", NEPSE_EQUITY_CHARGE_MODEL}:
        return NEPSE_EQUITY_CHARGE_MODEL
    if normalized in {"flat", "legacy", LEGACY_FLAT_CHARGE_MODEL}:
        return LEGACY_FLAT_CHARGE_MODEL
    raise ValueError("Charge model must be nepse_equity or legacy_flat.")


def equity_brokerage_rate(transaction_amount: float, trade_date: date) -> float:
    amount = max(0.0, float(transaction_amount or 0))
    if trade_date >= BROKERAGE_CHANGE_DATE:
        slabs = ((50_000, .0036), (500_000, .0033), (2_000_000, .0031), (10_000_000, .0027))
        final_rate = .0024
    else:
        slabs = ((50_000, .0040), (500_000, .0037), (2_000_000, .0034), (10_000_000, .0030))
        final_rate = .0027
    for ceiling, rate in slabs:
        if amount <= ceiling:
            return rate
    return final_rate


def broker_commission(transaction_amount: float, trade_date: date) -> float:
    amount = max(0.0, float(transaction_amount or 0))
    if amount <= 0:
        return 0.0
    return max(MINIMUM_BROKER_COMMISSION, amount * equity_brokerage_rate(amount, trade_date))


def sebon_transaction_fee(transaction_amount: float) -> float:
    return max(0.0, float(transaction_amount or 0)) * SEBON_RATE


def capital_gains_tax_rate(investor_type: str, holding_days: int, *, listed: bool = True) -> float:
    kind = str(investor_type or "individual").strip().lower()
    if kind in {"institution", "institutional", "entity"}:
        return .10 if listed else .15
    if kind in {"other", "non_resident", "non-resident"}:
        return .25
    if not listed:
        return .10
    return .05 if int(holding_days or 0) > 365 else .075


def buy_charges(
    transaction_amount: float,
    trade_date: date,
    *,
    charge_model: str = NEPSE_EQUITY_CHARGE_MODEL,
    fee_pct: float = .4,
    fixed_fee: float = 0,
) -> Dict[str, float]:
    amount = max(0.0, float(transaction_amount or 0))
    model = normalize_charge_model(charge_model)
    if model == LEGACY_FLAT_CHARGE_MODEL:
        legacy = amount * max(0.0, float(fee_pct or 0)) / 100 + max(0.0, float(fixed_fee or 0))
        return {"broker_commission": 0.0, "sebon_fee": 0.0, "dp_charge": 0.0,
                "capital_gains_tax": 0.0, "tax_rate": 0.0, "legacy_flat_fee": legacy,
                "total": legacy}
    broker = broker_commission(amount, trade_date)
    sebon = sebon_transaction_fee(amount)
    return {"broker_commission": broker, "sebon_fee": sebon, "dp_charge": 0.0,
            "capital_gains_tax": 0.0, "tax_rate": 0.0, "legacy_flat_fee": 0.0,
            "total": broker + sebon}


def sell_charges(
    transaction_amount: float,
    trade_date: date,
    *,
    entry_total_cost: float,
    holding_days: int,
    investor_type: str = "individual",
    apply_cgt: bool = True,
    dp_charge: float = DEFAULT_DP_CHARGE,
    charge_model: str = NEPSE_EQUITY_CHARGE_MODEL,
    fee_pct: float = .4,
    fixed_fee: float = 0,
) -> Dict[str, float]:
    amount = max(0.0, float(transaction_amount or 0))
    model = normalize_charge_model(charge_model)
    if model == LEGACY_FLAT_CHARGE_MODEL:
        legacy = amount * max(0.0, float(fee_pct or 0)) / 100 + max(0.0, float(fixed_fee or 0))
        profit_before_tax = amount - legacy - float(entry_total_cost or 0)
        return {"broker_commission": 0.0, "sebon_fee": 0.0, "dp_charge": 0.0,
                "capital_gains_tax": 0.0, "tax_rate": 0.0, "legacy_flat_fee": legacy,
                "profit_before_tax": profit_before_tax, "total": legacy}
    broker = broker_commission(amount, trade_date)
    sebon = sebon_transaction_fee(amount)
    dp = max(0.0, float(dp_charge or 0)) if amount > 0 else 0.0
    non_tax_total = broker + sebon + dp
    profit_before_tax = amount - non_tax_total - float(entry_total_cost or 0)
    tax_rate = capital_gains_tax_rate(investor_type, holding_days)
    tax = max(0.0, profit_before_tax) * tax_rate if apply_cgt else 0.0
    return {"broker_commission": broker, "sebon_fee": sebon, "dp_charge": dp,
            "capital_gains_tax": tax, "tax_rate": tax_rate if apply_cgt else 0.0,
            "legacy_flat_fee": 0.0, "profit_before_tax": profit_before_tax,
            "total": non_tax_total + tax}


def maximum_affordable_quantity(
    cash: float,
    price: float,
    trade_date: date,
    *,
    charge_model: str = NEPSE_EQUITY_CHARGE_MODEL,
    fee_pct: float = .4,
    fixed_fee: float = 0,
) -> int:
    available = max(0.0, float(cash or 0))
    unit_price = max(0.0, float(price or 0))
    if available <= 0 or unit_price <= 0:
        return 0
    low, high = 0, int(available // unit_price)
    while low < high:
        middle = (low + high + 1) // 2
        gross = middle * unit_price
        charges = buy_charges(gross, trade_date, charge_model=charge_model,
                              fee_pct=fee_pct, fixed_fee=fixed_fee)["total"]
        if gross + charges <= available + 1e-9:
            low = middle
        else:
            high = middle - 1
    return low


def rounded_breakdown(values: Dict[str, Any]) -> Dict[str, Any]:
    return {key: round(value, 2) if isinstance(value, float) else value for key, value in values.items()}
