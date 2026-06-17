from __future__ import annotations

from utils.strategies.helpers import (
    get_buy_pressure,
    is_falling,
    is_fresh_trade,
    is_rising,
    is_volume_increasing,
    range_position,
)
from utils.strategies.types import MarketSnapshot, ScannerMemory, ScriptDetails


def calculate_buy_score(
    snapshot: MarketSnapshot,
    memory: ScannerMemory,
    details: ScriptDetails,
) -> float:
    score = 0.0

    if details.roe is not None and details.roe >= 15:
        score += 15
    if details.yoy_earnings_growth is not None and details.yoy_earnings_growth >= 15:
        score += 15
    if details.pe is not None and details.pe > 0 and details.pe <= 35:
        score += 10
    if details.pbv is not None and details.pbv > 0 and details.pbv <= 6:
        score += 5

    if details.macd_signal == "Bullish":
        score += 15
    if details.rsi_14 is not None and 35 <= details.rsi_14 <= 60:
        score += 10
    if details.mfi_14 is not None and 25 <= details.mfi_14 <= 60:
        score += 5
    if details.stochastic_14 is not None and details.stochastic_14 <= 45:
        score += 5
    if details.percent_b is not None and details.percent_b <= 45:
        score += 5

    if snapshot.open is not None and snapshot.ltp >= snapshot.open:
        score += 10
    if snapshot.prev_close is not None and snapshot.ltp >= snapshot.prev_close:
        score += 10
    if range_position(snapshot) >= 0.55:
        score += 10
    if is_volume_increasing(snapshot, memory):
        score += 10
    if is_rising(memory.last_prices, 3):
        score += 10

    buy_pressure = get_buy_pressure(snapshot)
    if buy_pressure is not None:
        if buy_pressure >= 0.60:
            score += 10
        elif buy_pressure <= 0.40:
            score -= 15

    if details.sma_20_status == "below":
        score -= 15
    if details.sma_50_status == "below":
        score -= 10
    if details.volume_trend == "Down":
        score -= 10
    if details.sharpe_annualized is not None and details.sharpe_annualized < 0:
        score -= 10
    if details.one_year_yield is not None and details.one_year_yield < 0:
        score -= 10
    if snapshot.change_percent is not None and snapshot.change_percent > 6:
        score -= 15
    if not is_fresh_trade(snapshot):
        score -= 30
    if is_falling(memory.last_prices, 3):
        score -= 20

    return score


def score_decision(score: float) -> str:
    if score >= 75:
        return "BUY_ALLOWED"
    if score >= 55:
        return "WATCH_ONLY"
    return "NO_TRADE"
