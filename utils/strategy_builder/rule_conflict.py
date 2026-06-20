from __future__ import annotations

from typing import Any, Dict, List, Optional


def resolve_rule_conflicts(
    intents: List[Dict[str, Any]],
    *,
    policy: str = "HIGHEST_PRIORITY_ONLY",
) -> List[Dict[str, Any]]:
    if not intents:
        return []
    if policy == "SELL_OVERRIDES_BUY":
        sells = [item for item in intents if str(item.get("side", "")).upper() == "SELL"]
        if sells:
            return [max(sells, key=lambda row: int(row.get("priority") or 0))]
    if policy == "FIRST_MATCH_ONLY":
        return [intents[0]]
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for item in intents:
        symbol = str(item.get("symbol") or "").upper()
        grouped.setdefault(symbol, []).append(item)
    resolved: List[Dict[str, Any]] = []
    for symbol, rows in grouped.items():
        buys = [row for row in rows if str(row.get("side", "")).upper() == "BUY"]
        sells = [row for row in rows if str(row.get("side", "")).upper() == "SELL"]
        if buys and sells:
            continue
        winner = max(rows, key=lambda row: int(row.get("priority") or 0))
        resolved.append(winner)
    return resolved
