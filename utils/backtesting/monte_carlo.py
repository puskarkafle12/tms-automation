"""Deterministic block bootstrap for selected backtest candidates."""

from __future__ import annotations

import random
from typing import Any, Dict, List, Sequence


def block_bootstrap(returns: Sequence[float], *, samples: int = 1000, block_size: int = 5, seed: int = 1) -> Dict[str, Any]:
    values = [float(value) / 100 for value in returns]
    if not values:
        return {"samples": 0, "outcomes": {}, "bands": []}
    rng = random.Random(seed)
    outcomes: List[float] = []
    paths: List[List[float]] = []
    count = len(values)
    for _ in range(samples):
        sampled: List[float] = []
        while len(sampled) < count:
            start = rng.randrange(count)
            sampled.extend(values[(start + offset) % count] for offset in range(block_size))
        equity = 1.0
        path = []
        for value in sampled[:count]:
            equity *= 1 + value
            path.append((equity - 1) * 100)
        outcomes.append(path[-1])
        paths.append(path)

    def percentile(values_: Sequence[float], pct: float) -> float:
        ordered = sorted(values_)
        position = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * pct)))
        return round(ordered[position], 3)

    bands = [{"trade": index + 1, "p05": percentile([path[index] for path in paths], .05),
              "p50": percentile([path[index] for path in paths], .50),
              "p95": percentile([path[index] for path in paths], .95)} for index in range(count)]
    return {"samples": samples, "block_size": block_size,
            "outcomes": {"p05": percentile(outcomes, .05), "p50": percentile(outcomes, .50),
                         "p95": percentile(outcomes, .95), "probability_profitable_pct": round(sum(value > 0 for value in outcomes) / samples * 100, 2)},
            "bands": bands}
