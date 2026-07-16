"""Multi-scan simulator for rule-based strategy evaluation."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from utils.strategies.handlers import evaluate_rule_based_strategy
from utils.strategies.types import MarketSnapshot, OrderContext, ScannerMemory, ScriptDetails, StrategyConfig, StrategyDecision
from utils.strategy_builder.strategy_parser import parse_strategy_query


def default_snapshot(**kwargs) -> MarketSnapshot:
    defaults = dict(
        symbol="CZBIL",
        ltp=200.0,
        open=200.0,
        high=202.0,
        low=195.0,
        volume=82902.0,
        prev_close=200.0,
        change=-3.0,
        change_percent=-1.5,
        last_traded_time=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    )
    defaults.update(kwargs)
    return MarketSnapshot(**defaults)


def default_context(**kwargs) -> OrderContext:
    defaults = dict(
        strategy_type="Technical Buy",
        canonical_strategy="Technical Buy",
        side="buy",
        symbol="CZBIL",
        qty=100,
        remaining_qty=100,
        target_price=0.0,
        config=StrategyConfig(),
    )
    defaults.update(kwargs)
    return OrderContext(**defaults)


def default_details(**kwargs) -> ScriptDetails:
    defaults = dict(
        available=True,
        roe=21.0,
        yoy_earnings_growth=52.0,
        pe=27.0,
        pbv=3.0,
        macd_signal="Bullish",
        rsi_14=46.0,
        mfi_14=41.0,
        stochastic_14=25.0,
        percent_b=32.0,
        three_month_price_trend="Mean reverting",
        beta_3_month=1.1,
        sharpe_annualized=0.5,
    )
    defaults.update(kwargs)
    return ScriptDetails(**defaults)


def simulate_scans(
    query: str,
    *,
    price_series: List[float],
    execution_mode: str = "live",
    strategy_type: str = "Technical Buy",
    canonical_strategy: Optional[str] = None,
    side: str = "buy",
    symbol: str = "CZBIL",
    qty: int = 100,
    snapshot_builder: Optional[Callable[[float, int], MarketSnapshot]] = None,
    details: Optional[ScriptDetails] = None,
    details_builder: Optional[Callable[[float, int], ScriptDetails]] = None,
    holding_qty: int = 0,
    target_state: Optional[Dict[str, Any]] = None,
    portfolio_state: Optional[Dict[str, Any]] = None,
    extra_config: Optional[Dict[str, Any]] = None,
    compiled_plan_overrides: Optional[Dict[str, Any]] = None,
) -> List[StrategyDecision]:
    """Run evaluate_rule_based_strategy once per LTP, carrying target_state forward."""
    compiled = parse_strategy_query(query).model_dump()
    if compiled_plan_overrides:
        compiled.update(compiled_plan_overrides)
    extra: Dict[str, Any] = {
        "compiled_plan": compiled,
        "execution_mode": execution_mode,
        "target_state": dict(target_state or {}),
    }
    if portfolio_state is not None:
        extra["portfolio_state"] = dict(portfolio_state)
    if extra_config:
        extra.update(extra_config)

    decisions: List[StrategyDecision] = []
    last_prices: List[float] = []
    previous_ltp: Optional[float] = None

    for scan_idx, ltp in enumerate(price_series):
        if snapshot_builder:
            snapshot = snapshot_builder(ltp, scan_idx)
        else:
            snapshot = default_snapshot(ltp=ltp, symbol=symbol)
        last_prices.append(ltp)
        memory = ScannerMemory(
            last_prices=list(last_prices[:-1]),
            previous_ltp=previous_ltp,
            holding_qty=holding_qty or None,
        )
        ctx = default_context(
            strategy_type=strategy_type,
            canonical_strategy=canonical_strategy or strategy_type,
            side=side,
            symbol=symbol,
            qty=qty,
            remaining_qty=qty,
            config=StrategyConfig(extra=dict(extra)),
        )
        decision = evaluate_rule_based_strategy(
            ctx,
            snapshot,
            memory,
            (details_builder(ltp, scan_idx) if details_builder else (details or default_details())),
        )
        if decision.mutate:
            extra.update(decision.mutate)
        decisions.append(decision)
        previous_ltp = ltp

    return decisions


def first_execute_index(decisions: List[StrategyDecision]) -> Optional[int]:
    for idx, decision in enumerate(decisions):
        if decision.action == "EXECUTE":
            return idx
    return None
