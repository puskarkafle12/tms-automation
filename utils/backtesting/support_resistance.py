"""Causal ATR-normalized support and resistance zone detection.

Pivots become available only after ``pivot_span`` completed bars. Nearby
confirmed pivots are clustered into price zones, weighted by recency and
relative volume, and never use a future observation at the evaluation date.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Sequence


def _number(row: Dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        value = float(row.get(key))
        return value if math.isfinite(value) else default
    except (TypeError, ValueError):
        return default


def _cluster(
    candidates: Sequence[Dict[str, float]], *, current_index: int, epsilon: float,
) -> List[Dict[str, Any]]:
    groups: List[List[Dict[str, float]]] = []
    for candidate in sorted(candidates, key=lambda item: item["price"]):
        if not groups:
            groups.append([candidate])
            continue
        group = groups[-1]
        center = sum(item["price"] * item["weight"] for item in group) / sum(item["weight"] for item in group)
        if abs(candidate["price"] - center) <= epsilon:
            group.append(candidate)
        else:
            groups.append([candidate])
    zones: List[Dict[str, Any]] = []
    for group in groups:
        weight = sum(item["weight"] for item in group)
        center = sum(item["price"] * item["weight"] for item in group) / weight
        latest_index = int(max(item["pivot_index"] for item in group))
        touches = len(group)
        recency = math.exp(-max(0, current_index - latest_index) / 126.0)
        volume_quality = min(1.0, sum(item["volume_weight"] for item in group) / max(1, touches) / 1.5)
        confidence = 100.0 * (
            0.45 * min(1.0, touches / 4.0)
            + 0.25 * min(1.0, weight / 4.0)
            + 0.20 * recency
            + 0.10 * volume_quality
        )
        # Clustering may accept pivots within 0.6 ATR, but the rendered zone is
        # deliberately much narrower than that search radius.
        half_width = max(epsilon * 0.30, center * 0.0015)
        zones.append({
            "center": round(center, 6),
            "lower": round(center - half_width, 6),
            "upper": round(center + half_width, 6),
            "confidence": round(min(100.0, confidence), 2),
            "touches": touches,
            "first_touch_index": int(min(item["pivot_index"] for item in group)),
            "last_touch_index": latest_index,
        })
    return zones


def calculate_zone_history(
    rows: Sequence[Dict[str, Any]], *, lookback: int = 252, pivot_span: int = 3,
    cluster_atr: float = 0.60,
) -> List[Dict[str, Any]]:
    """Return the nearest causal support/resistance zone for every row."""
    count = len(rows)
    if not count:
        return []
    lows = [_number(row, "low") for row in rows]
    highs = [_number(row, "high") for row in rows]
    closes = [_number(row, "close", _number(row, "ltp")) for row in rows]
    volumes = [_number(row, "volume") for row in rows]
    atrs = [_number(row, "technical_atr_14") for row in rows]
    pivots: List[Dict[str, float]] = []
    output: List[Dict[str, Any]] = []

    for index in range(count):
        confirmed_index = index - pivot_span
        if confirmed_index >= pivot_span:
            start = confirmed_index - pivot_span
            end = confirmed_index + pivot_span + 1
            average_volume = sum(volumes[max(0, confirmed_index - 19):confirmed_index + 1]) / min(20, confirmed_index + 1)
            volume_weight = max(0.5, min(3.0, volumes[confirmed_index] / average_volume)) if average_volume > 0 else 1.0
            if lows[confirmed_index] > 0 and lows[confirmed_index] <= min(lows[start:end]):
                pivots.append({
                    "kind": 0.0, "price": lows[confirmed_index], "pivot_index": float(confirmed_index),
                    "available_index": float(index), "volume_weight": volume_weight,
                })
            if highs[confirmed_index] > 0 and highs[confirmed_index] >= max(highs[start:end]):
                pivots.append({
                    "kind": 1.0, "price": highs[confirmed_index], "pivot_index": float(confirmed_index),
                    "available_index": float(index), "volume_weight": volume_weight,
                })

        current_price = closes[index]
        atr = atrs[index]
        if atr <= 0 and current_price > 0:
            recent_ranges = [
                highs[item] - lows[item] for item in range(max(0, index - 13), index + 1)
                if highs[item] >= lows[item] > 0
            ]
            atr = sum(recent_ranges) / len(recent_ranges) if recent_ranges else current_price * 0.02
        epsilon = max(atr * cluster_atr, current_price * 0.004)
        # Bound work to the configured rolling horizon. This keeps historical
        # chart recomputation O(rows × lookback), not O(rows²).
        pivots = [
            pivot for pivot in pivots
            if int(pivot["pivot_index"]) >= index - lookback
        ]
        active = []
        for pivot in pivots:
            pivot_index = int(pivot["pivot_index"])
            age_weight = math.exp(-max(0, index - pivot_index) / 126.0)
            active.append({**pivot, "weight": pivot["volume_weight"] * age_weight})
        support_zones = _cluster(
            [item for item in active if item["kind"] == 0.0],
            current_index=index, epsilon=epsilon,
        )
        resistance_zones = _cluster(
            [item for item in active if item["kind"] == 1.0],
            current_index=index, epsilon=epsilon,
        )
        support = max(
            (zone for zone in support_zones if zone["lower"] <= current_price + epsilon),
            key=lambda zone: (zone["center"] <= current_price + epsilon, zone["center"], zone["confidence"]),
            default=None,
        )
        resistance = min(
            (zone for zone in resistance_zones if zone["upper"] >= current_price - epsilon),
            key=lambda zone: (zone["center"] < current_price - epsilon, abs(zone["center"] - current_price), -zone["confidence"]),
            default=None,
        )
        output.append({
            "support": support,
            "resistance": resistance,
            "atr": round(atr, 6),
            "all_support": sorted(support_zones, key=lambda zone: abs(zone["center"] - current_price))[:3],
            "all_resistance": sorted(resistance_zones, key=lambda zone: abs(zone["center"] - current_price))[:3],
        })
    return output


def current_zones(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return up to three current zones on each side for chart rendering."""
    history = calculate_zone_history(rows)
    if not history:
        return []
    latest = history[-1]
    zones: List[Dict[str, Any]] = []
    for kind, key in (("support", "all_support"), ("resistance", "all_resistance")):
        for zone in latest[key]:
            zones.append({
                "kind": kind,
                "lower": zone["lower"],
                "upper": zone["upper"],
                "center": zone["center"],
                "confidence": zone["confidence"],
                "touches": zone["touches"],
                "label": f"{kind.title()} · {zone['confidence']:.0f}% · {zone['touches']} touches",
            })
    return zones


def chart_zone_history(
    rows: Sequence[Dict[str, Any]], *, minimum_touches: int = 2,
    minimum_confidence: float = 42.0, maximum_age_sessions: int = 120,
) -> List[Dict[str, Any]]:
    """Return time-local prominent zones for interactive historical charts.

    Each snapshot uses only information available on that session. At most
    one support and one resistance zone are returned, and each rendered
    segment is capped so it does not span an unrelated market regime.
    """
    history = calculate_zone_history(rows)
    snapshots: List[Dict[str, Any]] = []
    for index, item in enumerate(history):
        snapshot_zones = []
        for kind, key in (("support", "all_support"), ("resistance", "all_resistance")):
            eligible = [
                zone for zone in item[key]
                if int(zone["touches"]) >= minimum_touches
                and float(zone["confidence"]) >= minimum_confidence
            ]
            if not eligible:
                continue
            prominent = sorted(
                eligible,
                key=lambda candidate: (
                    float(candidate["confidence"]),
                    int(candidate["touches"]),
                    int(candidate["last_touch_index"]),
                ),
                reverse=True,
            )[:1]
            for zone in prominent:
                start_index = max(
                    int(zone["first_touch_index"]),
                    index - max(1, int(maximum_age_sessions)),
                )
                snapshot_zones.append({
                    "kind": kind,
                    "lower": zone["lower"],
                    "upper": zone["upper"],
                    "center": zone["center"],
                    "confidence": zone["confidence"],
                    "touches": zone["touches"],
                    "start_date": str(rows[start_index].get("date") or "")[:10],
                    "end_date": str(rows[index].get("date") or "")[:10],
                    "label": f"{kind.title()} · {zone['confidence']:.0f}% · {zone['touches']} touches",
                })
        snapshots.append({
            "date": str(rows[index].get("date") or "")[:10],
            "zones": snapshot_zones,
        })
    return snapshots
