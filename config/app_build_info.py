from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

_MODULE_LOADED_AT = datetime.now(timezone.utc)
_DEPLOYED_AT_CACHE: Optional[datetime] = None
_REPO_ROOT = Path(__file__).resolve().parents[1]


def _parse_timestamp(raw: Optional[str]) -> Optional[datetime]:
    if not raw or raw.strip().lower() in {"unknown", "none", ""}:
        return None
    text = raw.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _read_deployed_at_file() -> Optional[datetime]:
    path = _REPO_ROOT / ".deployed_at"
    if not path.exists():
        return None
    try:
        return _parse_timestamp(path.read_text(encoding="utf-8").strip())
    except OSError:
        return None


def get_deployed_at() -> datetime:
    global _DEPLOYED_AT_CACHE
    if _DEPLOYED_AT_CACHE is not None:
        return _DEPLOYED_AT_CACHE

    for key in ("APP_DEPLOYED_AT", "APP_BUILD_DATE", "BUILD_DATE"):
        parsed = _parse_timestamp(os.getenv(key))
        if parsed is not None:
            _DEPLOYED_AT_CACHE = parsed
            return parsed

    from_file = _read_deployed_at_file()
    if from_file is not None:
        _DEPLOYED_AT_CACHE = from_file
        return from_file

    _DEPLOYED_AT_CACHE = _MODULE_LOADED_AT
    return _DEPLOYED_AT_CACHE


def get_app_build_info() -> Dict[str, Any]:
    deployed_at = get_deployed_at()
    git_commit = (os.getenv("APP_GIT_COMMIT") or "").strip() or None
    source_version = (os.getenv("APP_SOURCE_VERSION") or "").strip() or None
    if git_commit in {"", "unknown"}:
        git_commit = None
    if source_version in {"", "unknown"}:
        source_version = None
    return {
        "deployed_at": deployed_at.isoformat(),
        "git_commit": git_commit,
        "source_version": source_version,
    }
