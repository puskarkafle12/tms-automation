"""Deterministic, cache-friendly multi-signal strategy discovery candidates."""

from __future__ import annotations

import hashlib
import json
import math
import random
from itertools import combinations
from typing import Any, Dict, List, Sequence

from utils.backtesting.presets import get_backtest_presets


STOP_GRID = (4, 5, 6, 7, 8)
TARGET_GRID = (10, 12, 15, 18, 21, 24)
HOLD_GRID = (10, 20, 30, 45, 60, 90)
MIN_HOLD_GRID = (0, 2, 5)
RISK_CONFIGURATIONS = len(STOP_GRID) * len(TARGET_GRID) * len(HOLD_GRID) * len(MIN_HOLD_GRID)
EXIT_RULES = (
    ("rsi_strength_exit", "technical_rsi_14 >= 68"),
    ("macd_bearish_exit", 'technical_macd = "Bearish"'),
    ("ema20_break_exit", "ltp < technical_ema_20_value"),
    ("supertrend_bearish_exit", 'technical_supertrend = "Bearish"'),
    ("ppo_fade_exit", "technical_ppo_histogram < 0"),
    ("psar_bearish_exit", 'technical_psar = "Bearish"'),
    ("money_flow_exit", "technical_cmf_20 < 0"),
    ("trend_strength_exit", "technical_plus_di_14 < technical_minus_di_14"),
    ("momentum_rollover_exit", "technical_rsi_14 >= 65 AND technical_ppo_histogram < 0"),
    ("trend_breakdown_exit", 'ltp < technical_ema_20_value AND technical_macd = "Bearish"'),
    ("flow_breakdown_exit", "technical_cmf_20 < 0 AND technical_plus_di_14 < technical_minus_di_14"),
    ("dual_trend_exit", 'technical_supertrend = "Bearish" AND technical_psar = "Bearish"'),
)


def discovery_space_size(base_count: int) -> int:
    signal_sets = math.comb(base_count, 2) + (math.comb(base_count, 3) if base_count >= 3 else 0)
    return signal_sets * RISK_CONFIGURATIONS * len(EXIT_RULES)


def _candidate(parts: Sequence[Dict[str, Any]], stop: int, target: int, holding: int, minimum: int, exit_rule: tuple[str, str]) -> Dict[str, Any]:
    component_ids = sorted(str(item["id"]) for item in parts)
    condition = " AND ".join(f'({item["condition"]})' for item in parts)
    identity = {
        "components": component_ids, "condition": condition, "stop": stop,
        "target": target, "holding": holding, "minimum": minimum, "exit_rule": exit_rule,
        "generator": "deterministic-multisignal-v3-every-match",
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    source_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return {
        "id": f"discovery_{source_hash[:24]}",
        "name": f"Discovery · {' + '.join(item['name'] for item in parts)} · {stop}/{target}/{holding}",
        "category": "Adaptive combination discovery", "family": "multi_signal_discovery",
        "condition": condition, "description": "Deterministic conjunction of independently defined daily signals with a searched risk configuration.",
        "research_basis": "Candidate only; require locked out-of-sample reliability, walk-forward stability, and multiple-testing correction.",
        "version": "discovery-v3", "source_hash": source_hash, "component_ids": component_ids,
        "exit_rule_id": exit_rule[0], "exit_condition": exit_rule[1],
        "defaults": {
            "stop_loss_pct": stop, "take_profit_pct": target,
            "min_holding_days": minimum, "max_holding_days": holding,
        },
    }


def generate_discovery_presets(
    *, budget: int, seed: int = 20260718, base_ids: Sequence[str] | None = None,
    min_holding_days: int = 5, max_holding_days: int = 90,
) -> List[Dict[str, Any]]:
    """Sample unique candidates reproducibly without materializing the full search space."""
    catalog = {item["id"]: item for item in get_backtest_presets()}
    requested = list(dict.fromkeys(str(item) for item in (base_ids or catalog)))
    base = [catalog[item] for item in requested if item in catalog]
    if len(base) < 2:
        raise ValueError("Adaptive discovery requires at least two base strategies.")
    minimum_options = tuple(value for value in MIN_HOLD_GRID if value >= int(min_holding_days)) or (int(min_holding_days),)
    holding_options = tuple(value for value in HOLD_GRID if int(min_holding_days) <= value <= int(max_holding_days))
    if not holding_options:
        holding_options = (int(max_holding_days),)
    limit = max(1, min(int(budget), discovery_space_size(len(base))))
    rng = random.Random(int(seed))
    selected: Dict[str, Dict[str, Any]] = {}
    attempts = 0
    while len(selected) < limit and attempts < limit * 30:
        attempts += 1
        width = 3 if len(base) >= 3 and rng.random() < .6 else 2
        parts = rng.sample(base, width)
        candidate = _candidate(
            parts, rng.choice(STOP_GRID), rng.choice(TARGET_GRID),
            rng.choice(holding_options), rng.choice(minimum_options), rng.choice(EXIT_RULES),
        )
        selected[candidate["source_hash"]] = candidate
    if len(selected) < limit:
        for width in (2, 3):
            if width > len(base):
                continue
            for parts in combinations(base, width):
                for stop in STOP_GRID:
                    for target in TARGET_GRID:
                        if target <= stop:
                            continue
                        for holding in holding_options:
                            for minimum in minimum_options:
                                for exit_rule in EXIT_RULES:
                                    candidate = _candidate(parts, stop, target, holding, minimum, exit_rule)
                                    selected.setdefault(candidate["source_hash"], candidate)
                                    if len(selected) >= limit:
                                        break
                                if len(selected) >= limit: break
                            if len(selected) >= limit: break
                        if len(selected) >= limit: break
                    if len(selected) >= limit: break
                if len(selected) >= limit: break
            if len(selected) >= limit: break
    return sorted(selected.values(), key=lambda item: item["source_hash"])


def compile_discovery_exit_signals(preset: Dict[str, Any], rows: Sequence[Dict[str, Any]]) -> List[bool]:
    rule = str(preset.get("exit_rule_id") or "")
    signals: List[bool] = []
    for row in rows:
        def number(key: str) -> float:
            try:
                return float(row.get(key))
            except (TypeError, ValueError):
                return float("nan")

        text_value = lambda key: str(row.get(key) or "").lower()
        matched = {
            "rsi_strength_exit": number("technical_rsi_14") >= 68,
            "macd_bearish_exit": text_value("technical_macd") == "bearish",
            "ema20_break_exit": number("ltp") < number("technical_ema_20_value"),
            "supertrend_bearish_exit": text_value("technical_supertrend") == "bearish",
            "ppo_fade_exit": number("technical_ppo_histogram") < 0,
            "psar_bearish_exit": text_value("technical_psar") == "bearish",
            "money_flow_exit": number("technical_cmf_20") < 0,
            "trend_strength_exit": number("technical_plus_di_14") < number("technical_minus_di_14"),
            "momentum_rollover_exit": number("technical_rsi_14") >= 65 and number("technical_ppo_histogram") < 0,
            "trend_breakdown_exit": number("ltp") < number("technical_ema_20_value") and text_value("technical_macd") == "bearish",
            "flow_breakdown_exit": number("technical_cmf_20") < 0 and number("technical_plus_di_14") < number("technical_minus_di_14"),
            "dual_trend_exit": text_value("technical_supertrend") == "bearish" and text_value("technical_psar") == "bearish",
        }.get(rule, False)
        signals.append(bool(matched))
    return signals


def build_discovery_sell_query(preset: Dict[str, Any], symbol: str) -> str | None:
    condition = str(preset.get("exit_condition") or "").strip()
    if not condition:
        return None
    return f'''STRATEGY_VERSION 1
SIDE SELL
RULE "{preset.get("name", "Discovery")} · Exit" FOR SYMBOL "{symbol.strip().upper()}" {{
  WHEN {condition}
  ORDER PERCENT_OF_HOLDING 100
  EXECUTE ON EVERY MATCH
}}'''
