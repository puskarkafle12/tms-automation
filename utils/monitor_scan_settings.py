from __future__ import annotations

import random
import time
from typing import Any, Dict, Optional, Set

import config.tms_config as tms_config
from utils.strategies.aliases import canonical_strategy_name
from utils.strategy_builder.constants import RULE_BASED_STRATEGIES
from utils.strategy_builder.plan_expression_walk import walk_plan_expressions
from utils.strategy_builder.schedule_preflight import _field_data_source
from utils.strategy_builder.strategy_models import StrategyPlanAST
from utils.strategies.strategy_query_catalog import get_catalog_entry

MIN_SCAN_INTERVAL_SECONDS = 3
MAX_SCAN_INTERVAL_SECONDS = 86400
MIN_MAX_DATA_AGE_SECONDS = 5
MAX_MAX_DATA_AGE_SECONDS = 3600

NEPSE_ALPHA_DATA_SOURCES = {"nepse_alpha", "derived_statistical"}


def resolve_scan_interval_seconds(strategy_config: Optional[Dict[str, Any]] = None) -> int:
    default_interval = int(getattr(tms_config, "monitor_interval", 5) or 5)
    raw = (strategy_config or {}).get("scan_interval_seconds")
    if raw is None:
        return max(MIN_SCAN_INTERVAL_SECONDS, default_interval)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return max(MIN_SCAN_INTERVAL_SECONDS, default_interval)
    return max(MIN_SCAN_INTERVAL_SECONDS, min(MAX_SCAN_INTERVAL_SECONDS, value))


def resolve_max_data_age_seconds(strategy_config: Optional[Dict[str, Any]] = None) -> Optional[int]:
    raw = (strategy_config or {}).get("max_data_age_seconds")
    if raw in (None, "", 0, "0"):
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return max(MIN_MAX_DATA_AGE_SECONDS, min(MAX_MAX_DATA_AGE_SECONDS, value))


def normalize_monitor_settings(strategy_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    config = dict(strategy_config or {})
    config["scan_interval_seconds"] = resolve_scan_interval_seconds(config)
    max_age = resolve_max_data_age_seconds(config)
    if max_age is not None:
        config["max_data_age_seconds"] = max_age
    else:
        config.pop("max_data_age_seconds", None)
    mode = str(config.get("execution_mode") or "live").lower()
    if mode not in {"live", "paper", "shadow", "validate_only"}:
        mode = "live"
    config["execution_mode"] = mode
    return config


def _plan_from_config(strategy_config: Optional[Dict[str, Any]]) -> Optional[StrategyPlanAST]:
    compiled = (strategy_config or {}).get("compiled_plan")
    if not compiled:
        return None
    if isinstance(compiled, StrategyPlanAST):
        return compiled
    try:
        return StrategyPlanAST.model_validate(compiled)
    except Exception:
        return None


def _plan_requires_nepse_alpha(plan: StrategyPlanAST, side: str) -> bool:
    fields, _ = walk_plan_expressions(plan)
    for field_name in fields:
        if _field_data_source(field_name) in NEPSE_ALPHA_DATA_SOURCES:
            return True
    for rule in plan.rules:
        if not rule.use_strategy:
            continue
        entry = get_catalog_entry(rule.use_strategy, side)
        if entry and entry.requires_nepse_alpha:
            return True
    return False


def _classic_strategy_requires_nepse_alpha(canonical: str, strategy_config: Optional[Dict[str, Any]], side: str) -> bool:
    if canonical == "Time-Based Buy":
        wrapped = str((strategy_config or {}).get("wrapped_strategy_type") or "").strip()
        if not wrapped:
            nested = (strategy_config or {}).get("config") or {}
            if isinstance(nested, dict):
                wrapped = str(nested.get("wrapped_strategy_type") or "").strip()
        if wrapped:
            entry = get_catalog_entry(wrapped, "buy")
            if entry and entry.requires_nepse_alpha:
                return True
            return canonical_strategy_name(wrapped, "buy") in {
                "Quality Pullback Recovery Buy",
                "Mean Reversion Bounce Buy",
            }
        entry = get_catalog_entry("Quality Pullback Recovery Buy", "buy")
        return bool(entry and entry.requires_nepse_alpha)

    entry = get_catalog_entry(canonical, side)
    return bool(entry and entry.requires_nepse_alpha)


def order_requires_nepse_alpha(db_order) -> bool:
    side = str(getattr(db_order, "order_type", None) or "buy").lower()
    strategy_type = str(getattr(db_order, "strategy_type", None) or "")
    canonical = canonical_strategy_name(strategy_type, side)
    strategy_config = getattr(db_order, "strategy_config", None) or {}

    if canonical in RULE_BASED_STRATEGIES:
        plan = _plan_from_config(strategy_config)
        if plan is None:
            return False
        plan_side = str(plan.side or side).lower()
        return _plan_requires_nepse_alpha(plan, plan_side)

    return _classic_strategy_requires_nepse_alpha(canonical, strategy_config, side)


def resolve_scan_phase_offset_seconds(
    order_id: int,
    interval_seconds: int,
    strategy_config: Optional[Dict[str, Any]] = None,
    *,
    stagger_enabled: bool = True,
) -> int:
    interval = max(1, int(interval_seconds or 1))
    if not stagger_enabled:
        return 0
    raw = (strategy_config or {}).get("scan_phase_offset_seconds")
    if raw is not None:
        try:
            return int(raw) % interval
        except (TypeError, ValueError):
            pass
    return int(order_id) % interval


def ensure_scan_phase_offset_in_config(
    strategy_config: Optional[Dict[str, Any]],
    order_id: int,
    interval_seconds: int,
    *,
    stagger_enabled: bool = True,
) -> tuple[Dict[str, Any], int]:
    config = dict(strategy_config or {})
    offset = resolve_scan_phase_offset_seconds(
        order_id,
        interval_seconds,
        config,
        stagger_enabled=stagger_enabled,
    )
    if stagger_enabled and "scan_phase_offset_seconds" not in config:
        config["scan_phase_offset_seconds"] = offset
    return config, offset


def initial_tms_scan_due_at(
    now: float,
    order_id: int,
    interval_seconds: int,
    strategy_config: Optional[Dict[str, Any]] = None,
    *,
    stagger_enabled: bool = True,
) -> float:
    interval = max(1, int(interval_seconds or 1))
    if stagger_enabled:
        return now + random.uniform(0, interval)
    offset = resolve_scan_phase_offset_seconds(
        order_id,
        interval,
        strategy_config,
        stagger_enabled=stagger_enabled,
    )
    return now + offset


def _next_randomized_window_due_at(now: float, interval_seconds: int) -> float:
    interval = max(1, int(interval_seconds or 1))
    current_window_start = int(now // interval) * interval
    due_at = current_window_start + interval + random.uniform(0, interval)
    if due_at <= now:
        due_at += interval
    return due_at


def advance_tms_scan_due_at(
    now: float,
    interval_seconds: int,
    *,
    stagger_enabled: bool = True,
) -> float:
    if stagger_enabled:
        return _next_randomized_window_due_at(now, interval_seconds)
    return now + max(1, int(interval_seconds or 1))


def is_tms_scan_due(next_scan_at: Optional[float], now: Optional[float] = None) -> bool:
    if next_scan_at is None:
        return True
    return (now if now is not None else time.time()) >= float(next_scan_at)


def is_nepse_alpha_scan_due(next_scan_at: Optional[float], now: Optional[float] = None) -> bool:
    return is_tms_scan_due(next_scan_at, now)


def advance_nepse_alpha_scan_due_at(
    now: float,
    interval_seconds: int,
    *,
    stagger_enabled: bool = True,
) -> float:
    interval = max(60, int(interval_seconds or 60))
    if stagger_enabled:
        return _next_randomized_window_due_at(now, interval)
    return now + interval


def filter_due_order_ids(
    order_ids: Set[int],
    next_scan_at: Dict[int, float],
    *,
    now: Optional[float] = None,
) -> Set[int]:
    current = now if now is not None else time.time()
    return {order_id for order_id in order_ids if is_tms_scan_due(next_scan_at.get(order_id), current)}
