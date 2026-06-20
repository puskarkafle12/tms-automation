from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class OrderBookLevel:
    price: float
    quantity: float


@dataclass
class MarketSnapshot:
    symbol: str
    ltp: float
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    volume: Optional[float] = None
    prev_close: Optional[float] = None
    change: Optional[float] = None
    change_percent: Optional[float] = None
    last_traded_time: Optional[str] = None
    top_buy_orders: List[OrderBookLevel] = field(default_factory=list)
    top_sell_orders: List[OrderBookLevel] = field(default_factory=list)


@dataclass
class ScannerMemory:
    last_prices: List[float] = field(default_factory=list)
    last_volumes: List[float] = field(default_factory=list)
    previous_ltp: Optional[float] = None
    previous_volume: Optional[float] = None
    highest_after_buy: Optional[float] = None
    entry_price: Optional[float] = None
    entry_time: Optional[str] = None
    holding_qty: Optional[int] = None


@dataclass
class ScriptDetails:
    alpha_annualized: Optional[float] = None
    beta_3_month: Optional[float] = None
    sharpe_annualized: Optional[float] = None
    daily_var_95: Optional[float] = None
    volatility_50d: Optional[float] = None
    one_year_yield: Optional[float] = None
    fifty_two_week_high: Optional[float] = None
    fifty_two_week_low: Optional[float] = None
    all_time_high: Optional[float] = None
    all_time_low: Optional[float] = None
    pe: Optional[float] = None
    pbv: Optional[float] = None
    roe: Optional[float] = None
    ps: Optional[float] = None
    peg: Optional[float] = None
    roa: Optional[float] = None
    dividend_yield: Optional[float] = None
    payout_ratio: Optional[float] = None
    qoq_earnings_growth: Optional[float] = None
    yoy_earnings_growth: Optional[float] = None
    distance_from_graham_number: Optional[float] = None
    debt_to_equity: Optional[float] = None
    rsi_14: Optional[float] = None
    mfi_14: Optional[float] = None
    price_relative_strength: Optional[float] = None
    percent_b: Optional[float] = None
    stochastic_14: Optional[float] = None
    macd_signal: Optional[str] = None
    sma_10_status: Optional[str] = None
    sma_20_status: Optional[str] = None
    sma_50_status: Optional[str] = None
    sma_200_status: Optional[str] = None
    volume_trend: Optional[str] = None
    three_month_price_trend: Optional[str] = None
    reference_ltp: Optional[float] = None
    available: bool = False
    fetch_error: Optional[str] = None


@dataclass
class AccountState:
    available_balance: Optional[float] = None
    holding_qty: Optional[int] = None
    active_orders_same_symbol_side: int = 0
    trades_today: int = 0
    daily_loss_pct: float = 0.0
    consecutive_losses: int = 0
    order_failures: int = 0


@dataclass
class StrategyConfig:
    min_buy_score: float = 65.0
    require_fresh_trade: bool = False
    require_volume_increase: bool = False
    allow_market_depth_filter: bool = True
    wrapped_strategy_type: Optional[str] = None
    expiry_action: Optional[str] = None
    stop_loss_pct: float = 3.0
    break_even_trigger_pct: float = 3.0
    target1_pct: float = 4.0
    target1_sell_pct: float = 30.0
    target2_pct: float = 8.0
    target2_sell_pct: float = 30.0
    trailing_stop_pct: float = 3.0
    max_capital_per_stock_pct: float = 10.0
    order_timeout_minutes: int = 3
    allow_split_emergency_exit: bool = False
    sold_target1: bool = False
    sold_target2: bool = False
    break_even_armed: bool = False
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OrderContext:
    strategy_type: str
    canonical_strategy: str
    side: str
    symbol: str
    qty: int
    remaining_qty: int
    target_price: float
    stop_loss_price: Optional[float] = None
    stop_limit_price: Optional[float] = None
    book_profit_price: Optional[float] = None
    profit_target_price: Optional[float] = None
    trailing_drop_percent: float = 3.0
    stable_band_percent: float = 0.2
    minimum_wait_minutes: int = 5
    activation_price: Optional[float] = None
    protected_price: Optional[float] = None
    average_buy_price: Optional[float] = None
    partial_legs: List[Dict[str, Any]] = field(default_factory=list)
    executed_legs: List[str] = field(default_factory=list)
    target_reached: bool = False
    target_reached_at: Optional[datetime] = None
    highest_tracked_price: Optional[float] = None
    expiry_time: Optional[datetime] = None
    expiry_action: Optional[str] = None
    max_allowed_slippage_percent: float = 1.0
    emergency_execution: bool = False
    below_stop_loss_check_count: int = 0
    last_checked_ltp: Optional[float] = None
    config: StrategyConfig = field(default_factory=StrategyConfig)
    legacy_alias: Optional[str] = None

    def entry_price(self) -> Optional[float]:
        if self.average_buy_price:
            return float(self.average_buy_price)
        return None


@dataclass
class StrategyDecision:
    action: str
    reason_code: str
    reason: str
    score: Optional[float] = None
    price: Optional[float] = None
    qty: Optional[int] = None
    order_mode: Optional[str] = None
    order_value: Optional[float] = None
    source: Optional[str] = None
    leg_id: Optional[str] = None
    tracking_status: Optional[str] = None
    expired: bool = False
    cancelled_reason: Optional[str] = None
    failed_reason: Optional[str] = None
    mutate: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RiskDecision:
    allowed: bool
    reason_code: str
    reason: str
