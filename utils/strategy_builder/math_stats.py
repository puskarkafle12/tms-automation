from __future__ import annotations

import math
from typing import List, Optional


def rolling_stddev(values: List[float]) -> Optional[float]:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return math.sqrt(variance)


def rolling_slope(values: List[float]) -> Optional[float]:
    if len(values) < 2:
        return None
    n = len(values)
    x_mean = (n - 1) / 2.0
    y_mean = sum(values) / n
    numerator = sum((idx - x_mean) * (values[idx] - y_mean) for idx in range(n))
    denominator = sum((idx - x_mean) ** 2 for idx in range(n))
    if denominator == 0:
        return 0.0
    return numerator / denominator


def trend_direction(values: List[float], *, min_move_pct: float = 0.05) -> Optional[str]:
    if len(values) < 2:
        return None
    start = values[0]
    end = values[-1]
    if start in (None, 0):
        return None
    change_pct = ((end - start) / start) * 100.0
    if abs(change_pct) < min_move_pct:
        return "FLAT"
    return "UP" if change_pct > 0 else "DOWN"


def depth_imbalance(buy_qty: float, sell_qty: float) -> Optional[float]:
    total = buy_qty + sell_qty
    if total <= 0:
        return None
    return (buy_qty - sell_qty) / total
