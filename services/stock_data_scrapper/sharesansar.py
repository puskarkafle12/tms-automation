"""All-sector ShareSansar company-list client for cached market analysis."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from html import unescape
from typing import Any, Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = "https://www.sharesansar.com/company-list"
PAGE_SIZE = 50
REQUEST_TIMEOUT_SECONDS = 20
MAX_PAGES_PER_SECTOR = 50

COMPANY_LIST_COLUMNS = (
    "DT_Row_Index",
    "symbol",
    "companyname",
    "shares",
    "prom_share",
    "public_share",
    "paidup",
    "paidupcap",
    "marketcap",
    "listing_date",
    "ltp",
    "date",
)

logger = logging.getLogger(__name__)

NON_ORDINARY_SECTORS = frozenset(
    {
        "corporate debentures",
        "government bonds",
        "mutual fund",
        "preference share",
        "promoter share",
    }
)


def _build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
    session.mount("https://", adapter)
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
            ),
            "Referer": BASE_URL,
        }
    )
    return session


def _plain_text(value: Any) -> str:
    return unescape(BeautifulSoup(str(value or ""), "html.parser").get_text(" ", strip=True))


def _numeric(value: Any) -> Optional[float]:
    raw = _plain_text(value).replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", raw)
    if not match:
        return None
    try:
        return float(match.group(0))
    except (TypeError, ValueError):
        return None


def _percent(value: Any) -> Optional[float]:
    match = re.search(r"(-?\d+(?:\.\d+)?)\s*%", _plain_text(value))
    return float(match.group(1)) if match else None


def _anchor_href(value: Any) -> Optional[str]:
    anchor = BeautifulSoup(str(value or ""), "html.parser").find("a")
    href = str(anchor.get("href") or "").strip() if anchor else ""
    return href or None


def _date_value(value: Any) -> Optional[date]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def is_ordinary_share_sector(sector: str) -> bool:
    return str(sector or "").strip().lower() not in NON_ORDINARY_SECTORS


def discover_company_sectors(session: requests.Session) -> List[Tuple[str, str]]:
    response = session.get(BASE_URL, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    select = soup.select_one("select#sector, select[name='sector']")
    if select is None:
        raise RuntimeError("ShareSansar company-list sector selector was not found")

    sectors: List[Tuple[str, str]] = []
    for option in select.select("option"):
        sector_id = str(option.get("value") or "").strip()
        sector_name = option.get_text(" ", strip=True)
        if sector_id and sector_name:
            sectors.append((sector_id, sector_name))
    if not sectors:
        raise RuntimeError("ShareSansar company-list returned no sectors")
    return sectors


def normalize_company_row(raw: Dict[str, Any], *, sector_id: str, sector: str) -> Dict[str, Any]:
    symbol = _plain_text(raw.get("symbol")).upper()
    listing_date = _date_value(raw.get("listing_date"))
    market_data_date = _date_value(raw.get("date"))
    listing_age_days = None
    if listing_date:
        listing_age_days = max(0, ((market_data_date or date.today()) - listing_date).days)
    ordinary_share = is_ordinary_share_sector(sector)
    return {
        "symbol": symbol,
        "company_name": _plain_text(raw.get("companyname")),
        "company_url": _anchor_href(raw.get("symbol")) or _anchor_href(raw.get("companyname")),
        "sector_id": str(sector_id),
        "sector": sector,
        "shares_outstanding": _numeric(raw.get("shares")),
        "promoter_shares": _numeric(raw.get("prom_share")),
        "public_shares": _numeric(raw.get("public_share")),
        "promoter_share_percent": _percent(raw.get("prom_share_per")) or _percent(raw.get("prom_share")),
        "public_share_percent": _percent(raw.get("public_share_per")) or _percent(raw.get("public_share")),
        "paid_up_value": _numeric(raw.get("paidup")),
        "paid_up_capital": _numeric(raw.get("paidupcap")),
        "market_cap": _numeric(raw.get("marketcap")),
        "listing_date": listing_date.isoformat() if listing_date else None,
        "listing_age_days": listing_age_days,
        "is_ordinary_share": ordinary_share,
        "security_type": "ordinary_share" if ordinary_share else "non_ordinary_security",
        "ltp": _numeric(raw.get("ltp")),
        "market_data_date": market_data_date.isoformat() if market_data_date else None,
        "market_data_source": "sharesansar_company_list",
        "market_snapshot_version": 2,
    }


def _request_params(*, sector_id: str, start: int, draw: int) -> Dict[str, Any]:
    params: Dict[str, Any] = {
        "draw": draw,
        "start": start,
        "length": PAGE_SIZE,
        "sector": sector_id,
        "search[value]": "",
        "search[regex]": "false",
    }
    for index, column in enumerate(COMPANY_LIST_COLUMNS):
        params[f"columns[{index}][data]"] = column
    return params


def fetch_all_company_details(session: Optional[requests.Session] = None) -> List[Dict[str, Any]]:
    """Discover every sector and return every paginated company-list record."""
    owned_session = session is None
    active_session = session or _build_session()
    try:
        sectors = discover_company_sectors(active_session)
        by_symbol: Dict[str, Dict[str, Any]] = {}
        draw = 1
        for sector_id, sector_name in sectors:
            start = 0
            for _page in range(MAX_PAGES_PER_SECTOR):
                response = active_session.get(
                    BASE_URL,
                    params=_request_params(sector_id=sector_id, start=start, draw=draw),
                    headers={
                        "Accept": "application/json, text/javascript, */*; q=0.01",
                        "X-Requested-With": "XMLHttpRequest",
                    },
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                payload = response.json()
                draw += 1
                page_rows = payload.get("data") or []
                total = int(payload.get("recordsFiltered") or payload.get("recordsTotal") or 0)
                for raw in page_rows:
                    row = normalize_company_row(raw, sector_id=sector_id, sector=sector_name)
                    if row["symbol"]:
                        by_symbol[row["symbol"]] = row
                start += len(page_rows)
                if not page_rows or start >= total:
                    break
            else:
                raise RuntimeError(f"ShareSansar pagination limit exceeded for sector {sector_name}")

        rows = sorted(by_symbol.values(), key=lambda item: item["symbol"])
        logger.info("ShareSansar company-list loaded %s symbols across %s sectors", len(rows), len(sectors))
        return rows
    finally:
        if owned_session:
            active_session.close()


__all__ = [
    "BASE_URL",
    "PAGE_SIZE",
    "discover_company_sectors",
    "fetch_all_company_details",
    "is_ordinary_share_sector",
    "normalize_company_row",
]
