from __future__ import annotations

from typing import Any, Dict, List, Optional


class UniverseContext:
    def __init__(self, rows: Optional[List[Dict[str, Any]]] = None):
        self.rows = list(rows or [])
        self.valid_count = sum(1 for row in self.rows if row.get("valid"))

    def percentile(self, field: str, value: Optional[float]) -> Optional[float]:
        if value is None:
            return None
        values = sorted(float(row[field]) for row in self.rows if row.get("valid") and row.get(field) is not None)
        if not values:
            return None
        below = sum(1 for item in values if item <= value)
        return (below / len(values)) * 100.0

    def rank(self, field: str, value: Optional[float], *, descending: bool = True) -> Optional[int]:
        if value is None:
            return None
        values = sorted(
            (float(row[field]) for row in self.rows if row.get("valid") and row.get(field) is not None),
            reverse=descending,
        )
        if not value in values and not values:
            return None
        try:
            return values.index(value) + 1
        except ValueError:
            return len([item for item in values if item >= value]) + 1 if descending else len([item for item in values if item <= value]) + 1

    def metadata(self) -> Dict[str, Any]:
        return {
            "universe_size": len(self.rows),
            "valid_data_count": self.valid_count,
        }
