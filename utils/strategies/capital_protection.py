"""NEPSE Capital Protection Sell — trailing stop manager with depth-aware confirmation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

from utils.strategies.helpers import is_market_depth_available, parse_last_traded_time
from utils.strategies.types import MarketSnapshot, OrderContext, StrategyDecision

STALE_TRADE_MINUTES = 30
BREAK_EVEN_PEAK_MULTIPLIER = 1.015
CONFIRM_SCANS_BELOW_STOP = 2


@dataclass(frozen=True)
class CapitalProtectionStops:
    hard_stop: float
    trail_stop: float
    break_even: float
    circuit_floor: float
    effective_stop: float
    trailing_pct_used: float
    day_range_pct: Optional[float]
    highest_ltp: float


def _entry_price(ctx: OrderContext) -> float:
    entry = ctx.entry_price()
    if entry is not None and entry > 0:
        return float(entry)
    if ctx.target_price > 0:
        return float(ctx.target_price)
    return 0.0


def _default_trailing_pct(ctx: OrderContext) -> float:
    return float(ctx.trailing_drop_percent or ctx.config.trailing_stop_pct or 3.0)


def _day_range_pct(snapshot: MarketSnapshot) -> Optional[float]:
    if snapshot.high is None or snapshot.low is None or not snapshot.prev_close:
        return None
    prev_close = float(snapshot.prev_close)
    if prev_close <= 0:
        return None
    return ((float(snapshot.high) - float(snapshot.low)) / prev_close) * 100.0


def trailing_pct_for_volatility(base_trailing_pct: float, day_range_pct: Optional[float]) -> float:
    """Wider intraday range → wider trailing stop to reduce whipsaw."""
    base = max(0.0, float(base_trailing_pct))
    if day_range_pct is None:
        return base
    if day_range_pct < 1.5:
        return max(base, 2.5)
    if day_range_pct < 3.0:
        return max(base, 3.0)
    if day_range_pct <= 5.0:
        return max(base, 4.0)
    return max(base, 5.0)


def compute_capital_protection_stops(
    *,
    entry_price: float,
    stop_pct: float,
    trailing_pct: float,
    highest_ltp: float,
    snapshot: MarketSnapshot,
    hard_stop_override: Optional[float] = None,
) -> CapitalProtectionStops:
    day_range = _day_range_pct(snapshot)
    trailing_used = trailing_pct_for_volatility(trailing_pct, day_range)

    hard_stop = float(hard_stop_override) if hard_stop_override and hard_stop_override > 0 else entry_price * (1 - stop_pct / 100.0)
    peak = max(float(highest_ltp), float(snapshot.ltp or 0))
    trail_stop = peak * (1 - trailing_used / 100.0)
    break_even = entry_price if peak >= entry_price * BREAK_EVEN_PEAK_MULTIPLIER else 0.0
    circuit_floor = float(snapshot.prev_close or entry_price) * 0.95
    effective_stop = max(hard_stop, trail_stop, break_even)

    return CapitalProtectionStops(
        hard_stop=hard_stop,
        trail_stop=trail_stop,
        break_even=break_even,
        circuit_floor=circuit_floor,
        effective_stop=effective_stop,
        trailing_pct_used=trailing_used,
        day_range_pct=day_range,
        highest_ltp=peak,
    )


def _depth_metrics(snapshot: MarketSnapshot) -> Tuple[float, float, float, float]:
    bids = snapshot.top_buy_orders or []
    asks = snapshot.top_sell_orders or []
    top_bid_price = max((level.price for level in bids), default=0.0)
    top_bid_qty = next((level.quantity for level in bids if level.price == top_bid_price), 0.0) if top_bid_price else 0.0
    total_bid_qty = sum(level.quantity for level in bids[:5])
    top_ask_price = min((level.price for level in asks), default=0.0)
    return float(top_bid_price), float(top_bid_qty), float(total_bid_qty), float(top_ask_price)


def _is_stale_snapshot(snapshot: MarketSnapshot, *, now: Optional[datetime] = None) -> bool:
    traded_at = parse_last_traded_time(snapshot.last_traded_time)
    if traded_at is None:
        return False
    reference = now or datetime.utcnow()
    return reference - traded_at > timedelta(minutes=STALE_TRADE_MINUTES)


def evaluate_capital_protection_core(
    ctx: OrderContext,
    snapshot: MarketSnapshot,
    *,
    now: Optional[datetime] = None,
) -> StrategyDecision:
    """Run capital-protection steps 1–7 for one scan."""
    entry = _entry_price(ctx)
    if entry <= 0:
        return StrategyDecision("TRACK", "SELL_TRACK_CAPITAL_PROTECTION", "Capital protection monitoring — missing entry price")

    # STEP 1 — stale data guard
    if _is_stale_snapshot(snapshot, now=now):
        return StrategyDecision(
            "SKIP",
            "STALE_DATA_SKIP",
            "Last trade too old — skipping scan, no state change",
            tracking_status="Stale data",
        )

    stop_pct = float(ctx.config.stop_loss_pct)
    trailing_pct = _default_trailing_pct(ctx)
    stored_peak = float(ctx.highest_tracked_price or entry)
    scans_below = int(ctx.below_stop_loss_check_count or 0)
    depth_available = is_market_depth_available(snapshot)

    hard_override = ctx.stop_loss_price if ctx.stop_loss_price and ctx.stop_loss_price > 0 else None
    stops = compute_capital_protection_stops(
        entry_price=entry,
        stop_pct=stop_pct,
        trailing_pct=trailing_pct,
        highest_ltp=stored_peak,
        snapshot=snapshot,
        hard_stop_override=hard_override,
    )

    ltp = float(snapshot.ltp or 0)
    mutate: Dict[str, object] = {
        "highest_tracked_price": stops.highest_ltp,
        "below_stop_loss_check_count": scans_below,
    }
    if stops.break_even > 0:
        mutate["break_even_armed"] = True

    # STEP 4 — new peak
    if ltp > stored_peak:
        new_trail = ltp * (1 - stops.trailing_pct_used / 100.0)
        mutate["highest_tracked_price"] = ltp
        mutate["below_stop_loss_check_count"] = 0
        return StrategyDecision(
            "TRACK",
            "SELL_TRACK_NEW_PEAK",
            f"New peak Rs.{ltp:.2f} — trailing stop raised to Rs.{new_trail:.2f}",
            tracking_status="New peak",
            mutate=mutate,
        )

    # STEP 5 — safe zone
    if ltp > stops.effective_stop:
        mutate["below_stop_loss_check_count"] = 0
        return StrategyDecision(
            "TRACK",
            "SELL_TRACK_CAPITAL_PROTECTION",
            f"LTP Rs.{ltp:.2f} above effective stop Rs.{stops.effective_stop:.2f} — safe",
            tracking_status="Monitoring",
            mutate=mutate,
        )

    # STEP 6 — depth analysis (price at or below effective stop)
    if depth_available:
        top_bid_price, top_bid_qty, total_bid_qty, top_ask_price = _depth_metrics(snapshot)
        bid_defends_stop = top_bid_price >= stops.effective_stop and total_bid_qty >= max(top_bid_qty, 1.0)
        if bid_defends_stop:
            mutate["below_stop_loss_check_count"] = 0
            return StrategyDecision(
                "TRACK",
                "SELL_TRACK_DEPTH_SUPPORT",
                (
                    f"Bid support at Rs.{top_bid_price:.2f} (qty {int(total_bid_qty)}) "
                    f"holding at/above stop Rs.{stops.effective_stop:.2f} — waiting"
                ),
                tracking_status="Depth support",
                mutate=mutate,
            )

        ask_pressure = top_ask_price > 0 and top_bid_price > 0 and top_ask_price <= top_bid_price
        if top_bid_price >= ltp and total_bid_qty > 0 and not ask_pressure:
            return StrategyDecision(
                "TRACK",
                "SELL_TRACK_DEPTH_HOLD",
                f"Mild bid support at Rs.{top_bid_price:.2f} — deferring stop confirmation",
                tracking_status="Depth hold",
                mutate=mutate,
            )

    # STEP 7 — confirmed breach (2 scans at/below effective stop)
    scans_below += 1
    mutate["below_stop_loss_check_count"] = scans_below
    if scans_below < CONFIRM_SCANS_BELOW_STOP:
        return StrategyDecision(
            "TRACK",
            "SELL_TRACK_STOP_LOSS",
            f"LTP Rs.{ltp:.2f} at/below effective stop Rs.{stops.effective_stop:.2f} — confirming ({scans_below}/{CONFIRM_SCANS_BELOW_STOP})",
            tracking_status="Stop-loss triggered",
            mutate=mutate,
        )

    mutate["below_stop_loss_check_count"] = 0
    return StrategyDecision(
        "EXECUTE",
        "SELL_TRIGGERED_CAPITAL_PROTECTION",
        f"SELL: LTP Rs.{ltp:.2f} <= effective stop Rs.{stops.effective_stop:.2f} after {CONFIRM_SCANS_BELOW_STOP} scans",
        price=ltp,
        source="LTP",
        mutate=mutate,
    )
