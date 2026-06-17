"""Nepse Alpha market signals fetcher and HTML parser (internal only)."""

from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup
from curl_cffi import requests as cf_requests

BASE_URL = "https://nepsealpha.com"
BROWSER_IMPERSONATE = "chrome120"
DEFAULT_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-US,en;q=0.9",
    "x-requested-with": "XMLHttpRequest",
}

_fsk_cache: Dict[str, Any] = {"key": None, "expires_at": 0.0, "meta": None}


class NepseAlphaError(RuntimeError):
    """Raised when Nepse Alpha data cannot be fetched or parsed."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _slugify_label(label: str) -> str:
    cleaned = _clean_text(label).lower()
    cleaned = cleaned.replace("%b", "percent_b")
    cleaned = re.sub(r"[^a-z0-9]+", "_", cleaned)
    return cleaned.strip("_")


def _http_get(url: str, *, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None, timeout: float = 30) -> cf_requests.Response:
    """GET via browser TLS impersonation (no session cookies required)."""
    try:
        response = cf_requests.get(
            url,
            params=params,
            headers=headers,
            impersonate=BROWSER_IMPERSONATE,
            timeout=timeout,
        )
        response.raise_for_status()
        return response
    except cf_requests.RequestsError as exc:
        raise NepseAlphaError(f"Nepse Alpha request failed for {url}: {exc}") from exc


def _parse_sector_cell(cell) -> Dict[str, Optional[str]]:
    sub = cell.find("sub")
    symbol = _clean_text(sub.get_text()) if sub else None
    if sub:
        sub.extract()
    value = _clean_text(cell.get_text())
    return {"value": value or None, "symbol": symbol}


def _parse_colspan_signal(cell) -> Optional[str]:
    title = _clean_text(cell.get("title"))
    if title:
        return title
    text = _clean_text(cell.get_text())
    if text:
        return text
    icon = cell.find("i")
    if icon is not None:
        return _clean_text(icon.get("title")) or _clean_text(icon.get("class"))
    return None


def _parse_statistical_performance(table) -> Dict[str, str]:
    headers = [_clean_text(th.get_text()) for th in table.select("thead th")]
    values = [_clean_text(td.get_text()) for td in table.select("tbody td")]
    if not headers or not values:
        return {}
    width = min(len(headers), len(values))
    return {
        _slugify_label(headers[index]): values[index]
        for index in range(width)
    }


def _parse_indicator_rows(table) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for row in table.select("tbody tr"):
        cells = row.find_all("td")
        if not cells:
            continue

        indicator = _clean_text(cells[0].get_text())
        if not indicator:
            continue

        if len(cells) == 1 or int(cells[1].get("colspan") or 0) >= 2:
            rows.append(
                {
                    "indicator": indicator,
                    "signal": _parse_colspan_signal(cells[1]),
                }
            )
            continue

        if len(cells) >= 4:
            rows.append(
                {
                    "indicator": indicator,
                    "symbol_value": _clean_text(cells[1].get_text()) or None,
                    "sector_high": _parse_sector_cell(cells[2]),
                    "sector_low": _parse_sector_cell(cells[3]),
                }
            )
    return rows


def _section_key(title: str) -> Optional[str]:
    normalized = _clean_text(title).lower()
    if "stastical performance" in normalized or "statistical performance" in normalized:
        return "statistical_performance"
    if "fundamental signals" in normalized:
        return "fundamental_signals"
    if "technical signals" in normalized:
        return "technical_signals"
    return None


def parse_nepse_alpha_signals_html(html: str, symbol: str) -> Dict[str, Any]:
    """Parse Nepse Alpha signals HTML into structured JSON."""
    soup = BeautifulSoup(html or "", "html.parser")
    payload: Dict[str, Any] = {
        "symbol": symbol.strip().upper(),
        "source": "nepsealpha",
        "fetched_at": _utc_now_iso(),
        "statistical_performance": {},
        "fundamental_signals": [],
        "technical_signals": [],
    }

    for box in soup.select(".box"):
        title = _clean_text(box.select_one(".box-title").get_text()) if box.select_one(".box-title") else ""
        section = _section_key(title)
        table = box.select_one("table")
        if not section or table is None:
            continue

        if section == "statistical_performance":
            payload["statistical_performance"] = _parse_statistical_performance(table)
        else:
            payload[section] = _parse_indicator_rows(table)

    if not payload["statistical_performance"] and not payload["fundamental_signals"] and not payload["technical_signals"]:
        raise NepseAlphaError("Nepse Alpha HTML did not contain recognizable signal tables")

    return payload


def fetch_force_url_key(*, fs: Optional[int] = None, force_refresh: bool = False) -> Dict[str, Any]:
    """Fetch Nepse Alpha force-url key used as `fsk` query param."""
    global _fsk_cache

    now = time.time()
    if not force_refresh and _fsk_cache.get("key") and now < float(_fsk_cache.get("expires_at") or 0):
        cached_meta = dict(_fsk_cache.get("meta") or {})
        cached_meta["cached"] = True
        return cached_meta

    fs_value = fs if fs is not None else int(time.time() * 1000) % 1_000_000
    response = _http_get(
        f"{BASE_URL}/force-url-key",
        params={"fs": fs_value},
        headers={"accept": "*/*"},
        timeout=20,
    )
    try:
        payload = response.json()
    except ValueError as exc:
        raise NepseAlphaError("Nepse Alpha force-url key response was not valid JSON") from exc

    key = payload.get("key")
    if not key:
        raise NepseAlphaError("Nepse Alpha force-url key response did not include `key`")

    rl = int(payload.get("rl") or 3600)
    ttl_seconds = min(max(rl, 60), 6 * 3600)
    _fsk_cache = {
        "key": key,
        "expires_at": now + ttl_seconds,
        "meta": payload,
    }
    payload["cached"] = False
    return payload


def fetch_signals_raw(symbol: str, fsk: str) -> Dict[str, Any]:
    """Fetch raw Nepse Alpha signals payload for a symbol."""
    normalized_symbol = symbol.strip().upper()
    if not normalized_symbol:
        raise NepseAlphaError("Symbol is required")

    response = _http_get(
        f"{BASE_URL}/ajax/signals/{normalized_symbol}",
        params={"fsk": fsk},
        headers={
            **DEFAULT_HEADERS,
            "referer": f"{BASE_URL}/search?q={normalized_symbol}&tab=financials-menu",
        },
        timeout=30,
    )
    try:
        return response.json()
    except ValueError as exc:
        raise NepseAlphaError("Nepse Alpha signals response was not valid JSON") from exc


def get_nepse_alpha_signals(
    symbol: str,
    *,
    fs: Optional[int] = None,
    force_refresh_key: bool = False,
) -> Dict[str, Any]:
    """Fetch and parse Nepse Alpha signals for a symbol."""
    normalized_symbol = symbol.strip().upper()
    key_payload = fetch_force_url_key(fs=fs, force_refresh=force_refresh_key)
    raw = fetch_signals_raw(normalized_symbol, str(key_payload["key"]))
    html = raw.get("html")
    if not html:
        raise NepseAlphaError(f"Nepse Alpha returned no HTML for {normalized_symbol}")

    parsed = parse_nepse_alpha_signals_html(html, normalized_symbol)
    parsed["meta"] = {
        "fsk": key_payload.get("key"),
        "fsk_time": key_payload.get("time"),
        "fsk_cached": bool(key_payload.get("cached")),
        "source_url": f"{BASE_URL}/ajax/signals/{normalized_symbol}",
    }
    return parsed


async def get_nepse_alpha_signals_async(
    symbol: str,
    *,
    fs: Optional[int] = None,
    force_refresh_key: bool = False,
) -> Dict[str, Any]:
    """Async wrapper for `get_nepse_alpha_signals`."""
    return await asyncio.to_thread(
        get_nepse_alpha_signals,
        symbol,
        fs=fs,
        force_refresh_key=force_refresh_key,
    )
