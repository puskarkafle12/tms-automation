from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import config.tms_config as tms_config

SETTINGS_FILE = Path(__file__).resolve().parent / "portal_settings.json"
PORTAL_SETTINGS_ROW_ID = 1

MIN_SCAN_INTERVAL_SECONDS = 3
MAX_SCAN_INTERVAL_SECONDS = 86400
MIN_MAX_DATA_AGE_SECONDS = 5
MAX_MAX_DATA_AGE_SECONDS = 3600
MIN_MONITOR_TICK_SECONDS = 1
MAX_MONITOR_TICK_SECONDS = 3600
MIN_NEPSE_ALPHA_INTERVAL_SECONDS = 60
MAX_NEPSE_ALPHA_INTERVAL_SECONDS = 3600
MIN_MAX_PRICE_FETCH_CONCURRENCY = 1
MAX_MAX_PRICE_FETCH_CONCURRENCY = 20
EXECUTION_MODES = {"live", "paper", "shadow", "validate_only"}

DEFAULTS: Dict[str, Any] = {
    "monitor_interval_seconds": 5,
    "default_max_data_age_seconds": None,
    "default_execution_mode": "live",
    "enable_scan_staggering": True,
    "nepse_alpha_interval_seconds": 1800,
    "monitor_tick_seconds": 3,
    "max_price_fetch_concurrency": 5,
}

_runtime_settings: Dict[str, Any] = {}


def _clamp_scan_interval(value: Any, fallback: int = 5) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = fallback
    return max(MIN_SCAN_INTERVAL_SECONDS, min(MAX_SCAN_INTERVAL_SECONDS, parsed))


def _clamp_max_data_age(value: Any) -> Optional[int]:
    if value in (None, "", 0, "0"):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return max(MIN_MAX_DATA_AGE_SECONDS, min(MAX_MAX_DATA_AGE_SECONDS, parsed))


def _clamp_monitor_tick(value: Any, fallback: int = 5) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = fallback
    return max(MIN_MONITOR_TICK_SECONDS, min(MAX_MONITOR_TICK_SECONDS, parsed))


def _clamp_nepse_alpha_interval(value: Any, fallback: int = 1800) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = fallback
    return max(MIN_NEPSE_ALPHA_INTERVAL_SECONDS, min(MAX_NEPSE_ALPHA_INTERVAL_SECONDS, parsed))


def _clamp_max_price_fetch_concurrency(value: Any, fallback: int = 5) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = fallback
    return max(MIN_MAX_PRICE_FETCH_CONCURRENCY, min(MAX_MAX_PRICE_FETCH_CONCURRENCY, parsed))


def _normalize_execution_mode(value: Any) -> str:
    mode = str(value or "live").lower()
    return mode if mode in EXECUTION_MODES else "live"


def _normalize_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    if value in (None, ""):
        return default
    return bool(value)


def normalize_portal_settings(raw: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload = dict(DEFAULTS)
    if raw:
        payload.update(raw)
    normalized = {
        "monitor_interval_seconds": _clamp_scan_interval(
            payload.get("monitor_interval_seconds"),
            DEFAULTS["monitor_interval_seconds"],
        ),
        "default_max_data_age_seconds": _clamp_max_data_age(payload.get("default_max_data_age_seconds")),
        "default_execution_mode": _normalize_execution_mode(payload.get("default_execution_mode")),
        "enable_scan_staggering": _normalize_bool(
            payload.get("enable_scan_staggering"),
            default=bool(DEFAULTS["enable_scan_staggering"]),
        ),
        "nepse_alpha_interval_seconds": _clamp_nepse_alpha_interval(
            payload.get("nepse_alpha_interval_seconds"),
            DEFAULTS["nepse_alpha_interval_seconds"],
        ),
        "monitor_tick_seconds": _clamp_monitor_tick(
            payload.get("monitor_tick_seconds"),
            DEFAULTS["monitor_tick_seconds"],
        ),
        "max_price_fetch_concurrency": _clamp_max_price_fetch_concurrency(
            payload.get("max_price_fetch_concurrency"),
            DEFAULTS["max_price_fetch_concurrency"],
        ),
    }
    return normalized


def apply_portal_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    global _runtime_settings
    normalized = normalize_portal_settings(settings)
    _runtime_settings = dict(normalized)
    tms_config.monitor_interval = normalized["monitor_interval_seconds"]
    tms_config.monitor_tick_seconds = normalized["monitor_tick_seconds"]
    tms_config.nepse_alpha_interval_seconds = normalized["nepse_alpha_interval_seconds"]
    tms_config.enable_scan_staggering = normalized["enable_scan_staggering"]
    tms_config.max_price_fetch_concurrency = normalized["max_price_fetch_concurrency"]
    return normalized


def _read_database_settings() -> Optional[Dict[str, Any]]:
    try:
        from sqlalchemy import text

        from database import SessionLocal
    except Exception:
        return None

    db = SessionLocal()
    try:
        row = db.execute(
            text("SELECT settings_json FROM portal_settings WHERE id = :id"),
            {"id": PORTAL_SETTINGS_ROW_ID},
        ).first()
        if not row or not row[0]:
            return None
        payload = json.loads(row[0])
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None
    finally:
        db.close()


def _write_database_settings(settings: Dict[str, Any]) -> bool:
    try:
        from sqlalchemy import text

        from database import SessionLocal
    except Exception:
        return False

    db = SessionLocal()
    try:
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS portal_settings (
                    id INTEGER PRIMARY KEY,
                    settings_json TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        db.execute(
            text(
                """
                INSERT INTO portal_settings (id, settings_json, updated_at)
                VALUES (:id, :settings_json, CURRENT_TIMESTAMP)
                ON CONFLICT (id) DO UPDATE SET
                    settings_json = EXCLUDED.settings_json,
                    updated_at = CURRENT_TIMESTAMP
                """
            ),
            {
                "id": PORTAL_SETTINGS_ROW_ID,
                "settings_json": json.dumps(settings),
            },
        )
        db.commit()
        return True
    except Exception:
        db.rollback()
        return False
    finally:
        db.close()


def _read_file_settings() -> Optional[Dict[str, Any]]:
    if not SETTINGS_FILE.exists():
        return None
    try:
        raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _write_file_settings(settings: Dict[str, Any]) -> None:
    try:
        SETTINGS_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    except OSError:
        pass


def load_portal_settings() -> Dict[str, Any]:
    raw = _read_database_settings()
    if raw is None:
        raw = _read_file_settings()
        if raw is not None:
            normalized = normalize_portal_settings(raw)
            _write_database_settings(normalized)
            return apply_portal_settings(normalized)
    return apply_portal_settings(raw or DEFAULTS)


def save_portal_settings(raw: Dict[str, Any]) -> Dict[str, Any]:
    current = get_portal_settings() if _runtime_settings else load_portal_settings()
    normalized = apply_portal_settings({**current, **raw})
    _write_database_settings(normalized)
    _write_file_settings(normalized)
    return normalized


def get_portal_settings() -> Dict[str, Any]:
    if not _runtime_settings:
        return load_portal_settings()
    return normalize_portal_settings(_runtime_settings)
