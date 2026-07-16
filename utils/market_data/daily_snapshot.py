"""Daily all-sector ShareSansar company snapshot job."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from utils.market_data.repository import daily_snapshot_has_source, has_daily_snapshot, log_refresh, save_daily_snapshot
from utils.market_status import get_nepal_now

logger = logging.getLogger(__name__)


def _merge_latest_market_activity(
    company_rows: List[Dict[str, Any]],
    market_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Add volume and current trading fields without replacing company fundamentals."""
    from utils.market_data.merolagani_fields import extract_symbol, flatten_merolagani_row

    live_by_symbol = {
        extract_symbol(row): flatten_merolagani_row(row)
        for row in market_rows
        if extract_symbol(row)
    }
    for company_row in company_rows:
        live = live_by_symbol.get(extract_symbol(company_row)) or {}
        for target, source in (
            ("ltp", "ml_ltp"),
            ("percent_change", "ml_percent_change"),
            ("qty", "ml_quantity"),
            ("open", "ml_open"),
            ("high", "ml_high"),
            ("low", "ml_low"),
        ):
            value = live.get(source)
            if value is not None:
                company_row[target] = value
        if live:
            company_row["market_activity_source"] = "latest_market_table"
    return company_rows


def _rows_from_dataframe(df) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for _, row in df.iterrows():
        payload = row.to_dict()
        cleaned = {}
        for key, value in payload.items():
            if key == "link":
                cleaned[key] = value
                continue
            if value is None or (isinstance(value, float) and value != value):
                continue
            cleaned[key] = value
        rows.append(cleaned)
    return rows


def run_daily_market_snapshot(db: Session, *, snapshot_date: date | None = None, force: bool = False) -> Dict[str, Any]:
    """Fetch all ShareSansar sectors and persist one normalized daily snapshot."""
    from services.stock_data_scrapper.sharesansar import fetch_all_company_details

    target_date = snapshot_date or get_nepal_now().date()
    has_snapshot = has_daily_snapshot(db, target_date)
    has_sharesansar_snapshot = has_snapshot and daily_snapshot_has_source(
        db,
        target_date,
        "sharesansar_company_list",
        min_version=2,
    )
    if not force and has_sharesansar_snapshot:
        return {"status": "skipped", "snapshot_date": target_date.isoformat(), "reason": "already_exists"}

    started_at = datetime.utcnow()
    try:
        rows = fetch_all_company_details()
        try:
            from services.stock_data_scrapper.scrapper import get_latest_market_rows

            rows = _merge_latest_market_activity(rows, get_latest_market_rows())
        except Exception as exc:
            logger.warning("Latest market activity merge skipped: %s", exc)
        symbol_count = save_daily_snapshot(db, target_date, rows)
        db.commit()
        log_refresh(
            db,
            refresh_type="daily_snapshot",
            status="ok",
            symbol_count=symbol_count,
            message=f"Saved daily snapshot for {target_date.isoformat()}",
            started_at=started_at,
        )
        db.commit()
        logger.info("Daily ShareSansar snapshot saved for %s (%s symbols)", target_date, symbol_count)
        return {
            "status": "ok",
            "snapshot_date": target_date.isoformat(),
            "symbol_count": symbol_count,
            "source": "sharesansar_company_list",
        }
    except Exception as exc:
        db.rollback()
        log_refresh(
            db,
            refresh_type="daily_snapshot",
            status="error",
            message=str(exc),
            started_at=started_at,
        )
        db.commit()
        logger.exception("Daily ShareSansar snapshot failed")
        return {"status": "error", "snapshot_date": target_date.isoformat(), "message": str(exc)}


def run_daily_merolagani_snapshot(db: Session, *, snapshot_date: date | None = None, force: bool = False) -> Dict[str, Any]:
    """Backward-compatible name for callers of the previous daily snapshot job."""
    return run_daily_market_snapshot(db, snapshot_date=snapshot_date, force=force)
