from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Observation:
    value: Any
    source_timestamp: Optional[str] = None
    received_at: Optional[str] = None


@dataclass
class TargetHistory:
    observations: Dict[str, List[Observation]] = field(default_factory=dict)
    previous_values: Dict[str, Any] = field(default_factory=dict)
    previous_enum_values: Dict[str, Any] = field(default_factory=dict)
    rule_was_true: bool = False
    confirmation_streak: int = 0
    function_streaks: Dict[str, int] = field(default_factory=dict)
    condition_window: Dict[str, List[bool]] = field(default_factory=dict)
    position: Dict[str, Any] = field(default_factory=dict)
    executed: bool = False


def is_valid_observation(
    previous: Optional[Observation],
    current: Observation,
    *,
    policy: str = "count_only_value_change",
) -> bool:
    if previous is None:
        return True
    if policy == "count_every_scan":
        return True
    if policy == "count_only_new_trade":
        return current.source_timestamp != previous.source_timestamp
    if policy == "count_only_new_source_timestamp":
        return current.source_timestamp != previous.source_timestamp
    if policy == "count_only_value_change":
        return current.value != previous.value
    return current.value != previous.value


def append_observation(
    history: TargetHistory,
    field_name: str,
    value: Any,
    *,
    source_timestamp: Optional[str] = None,
    received_at: Optional[str] = None,
    policy: str = "count_only_value_change",
    max_window: int = 500,
) -> None:
    current = Observation(value=value, source_timestamp=source_timestamp, received_at=received_at)
    rows = history.observations.setdefault(field_name, [])
    if rows and not is_valid_observation(rows[-1], current, policy=policy):
        return
    rows.append(current)
    if len(rows) > max_window:
        history.observations[field_name] = rows[-max_window:]


def consecutive_moves(
    field_name: str,
    history: TargetHistory,
    *,
    direction: str,
    count: int,
    min_each_change_pct: float = 0.0,
    min_total_change_pct: float = 0.0,
) -> bool:
    rows = history.observations.get(field_name) or []
    needed = count + 1
    if len(rows) < needed:
        return False
    window = rows[-needed:]
    for idx in range(1, len(window)):
        prev_val = window[idx - 1].value
        curr_val = window[idx].value
        if prev_val is None or curr_val is None:
            return False
        if direction == "drop" and not (curr_val < prev_val):
            return False
        if direction == "rise" and not (curr_val > prev_val):
            return False
        if min_each_change_pct > 0 and prev_val:
            change_pct = abs((curr_val - prev_val) / prev_val) * 100.0
            if change_pct < min_each_change_pct:
                return False
    if min_total_change_pct > 0:
        first_val = window[0].value
        last_val = window[-1].value
        if first_val in (None, 0) or last_val is None:
            return False
        total_change = abs((last_val - first_val) / first_val) * 100.0
        if total_change < min_total_change_pct:
            return False
    return True


def changed_from_to(field_name: str, history: TargetHistory, from_value: Any, to_value: Any) -> bool:
    current = history.previous_values.get(field_name)
    previous = history.previous_enum_values.get(field_name)
    return previous == from_value and current == to_value


def previous_value(field_name: str, history: TargetHistory, scans_back: int = 1) -> Any:
    rows = history.observations.get(field_name) or []
    if len(rows) <= scans_back:
        return None
    return rows[-(scans_back + 1)].value


def changed_to(field_name: str, history: TargetHistory, expected: Any) -> bool:
    current = history.previous_values.get(field_name)
    previous = history.previous_enum_values.get(field_name)
    return previous != expected and current == expected


def change_percent(field_name: str, history: TargetHistory, scans_back: int) -> Optional[float]:
    rows = history.observations.get(field_name) or []
    if len(rows) <= scans_back:
        return None
    current = rows[-1].value
    previous = rows[-(scans_back + 1)].value
    if current is None or previous in (None, 0):
        return None
    return ((current - previous) / previous) * 100.0


def remains_above(field_name: str, history: TargetHistory, threshold: float, scans: int) -> bool:
    rows = history.observations.get(field_name) or []
    if len(rows) < scans:
        return False
    window = rows[-scans:]
    return all(row.value is not None and row.value > threshold for row in window)


def remains_below(field_name: str, history: TargetHistory, threshold: float, scans: int) -> bool:
    rows = history.observations.get(field_name) or []
    if len(rows) < scans:
        return False
    window = rows[-scans:]
    return all(row.value is not None and row.value < threshold for row in window)


def matches_in_last(values: List[bool], required: int, window: int) -> bool:
    if window <= 0 or required <= 0:
        return False
    recent = values[-window:]
    if len(recent) < window:
        return False
    return sum(1 for item in recent if item) >= required


def serialize_target_history(history: TargetHistory) -> Dict[str, Any]:
    observations: Dict[str, List[Dict[str, Any]]] = {}
    for field_name, rows in (history.observations or {}).items():
        observations[field_name] = [
            {
                "value": row.value,
                "source_timestamp": row.source_timestamp,
                "received_at": row.received_at,
            }
            for row in rows
        ]
    return {
        "observations": observations,
        "previous_values": dict(history.previous_values or {}),
        "previous_enum_values": dict(history.previous_enum_values or {}),
        "rule_was_true": bool(history.rule_was_true),
        "confirmation_streak": int(history.confirmation_streak or 0),
        "function_streaks": dict(history.function_streaks or {}),
        "condition_window": {
            key: list(values or [])
            for key, values in (history.condition_window or {}).items()
        },
        "position": dict(history.position or {}),
        "executed": bool(history.executed),
    }


def deserialize_target_history(payload: Optional[Dict[str, Any]]) -> TargetHistory:
    history = TargetHistory()
    if not payload:
        return history
    for field_name, rows in (payload.get("observations") or {}).items():
        history.observations[field_name] = [
            Observation(
                value=row.get("value"),
                source_timestamp=row.get("source_timestamp"),
                received_at=row.get("received_at"),
            )
            for row in rows or []
        ]
    history.previous_values = dict(payload.get("previous_values") or {})
    history.previous_enum_values = dict(payload.get("previous_enum_values") or {})
    history.rule_was_true = bool(payload.get("rule_was_true"))
    history.confirmation_streak = int(payload.get("confirmation_streak") or 0)
    history.function_streaks = dict(payload.get("function_streaks") or {})
    history.condition_window = {
        key: list(values or [])
        for key, values in (payload.get("condition_window") or {}).items()
    }
    history.position = dict(payload.get("position") or {})
    history.executed = bool(payload.get("executed"))
    return history
