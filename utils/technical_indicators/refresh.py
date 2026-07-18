"""Background backfill for per-stock latest technical snapshots."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Any, Dict

from sqlalchemy import text

from utils.technical_indicators import ENGINE_VERSION, calculate_indicator_rows

_LOCK = threading.Lock()
_THREAD: threading.Thread | None = None
_STATE: Dict[str, Any] = {"running": False, "completed": 0, "total": 0, "current_symbol": None, "failed": 0}


def get_indicator_refresh_status() -> Dict[str, Any]:
    from database import SessionLocal
    session = SessionLocal()
    try:
        stored = int(session.execute(text("SELECT COUNT(*) FROM market_technical_indicators WHERE engine_version = :version"), {"version": ENGINE_VERSION}).scalar() or 0)
    finally:
        session.close()
    return {**_STATE, "stored_symbols": stored, "engine_version": ENGINE_VERSION}


def _calculate(symbol: str) -> Dict[str, Any]:
    from utils.backtesting.service import fetch_historical_bars
    bars = fetch_historical_bars(symbol, date(2018, 1, 1), date.today())
    rows = calculate_indicator_rows(bars)
    return {
        "symbol": symbol, "as_of_date": date.fromisoformat(bars[-1].day),
        "indicators": rows[-1], "bars_count": len(bars),
        "history_start": date.fromisoformat(bars[0].day), "history_end": date.fromisoformat(bars[-1].day),
    }


def _run() -> None:
    from database import SessionLocal
    from utils.market_data.repository import save_technical_indicator_snapshot
    session = SessionLocal()
    try:
        symbols = [str(value) for value in session.execute(text("""
            SELECT c.symbol
            FROM market_screener_cache c
            LEFT JOIN market_technical_indicators t
              ON t.symbol = c.symbol AND t.engine_version = :version
            WHERE c.combined_data->>'security_type' = 'ordinary_share'
              AND t.symbol IS NULL
            ORDER BY c.symbol
        """), {"version": ENGINE_VERSION}).scalars().all()]
    finally:
        session.close()
    _STATE.update({"running": True, "completed": 0, "total": len(symbols), "current_symbol": None, "failed": 0})
    try:
        with ThreadPoolExecutor(max_workers=6, thread_name_prefix="indicator-refresh") as executor:
            futures = {executor.submit(_calculate, symbol): symbol for symbol in symbols}
            for future in as_completed(futures):
                symbol = futures[future]
                _STATE["current_symbol"] = symbol
                try:
                    output = future.result()
                    session = SessionLocal()
                    try:
                        save_technical_indicator_snapshot(session, engine_version=ENGINE_VERSION, **output)
                        session.commit()
                    finally:
                        session.close()
                except Exception:
                    _STATE["failed"] += 1
                _STATE["completed"] += 1
    finally:
        _STATE["running"] = False
        _STATE["current_symbol"] = None


def start_indicator_refresh_background() -> bool:
    global _THREAD
    with _LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            return False
        _THREAD = threading.Thread(target=_run, name="technical-indicator-backfill", daemon=True)
        _THREAD.start()
        return True
