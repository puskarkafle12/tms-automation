"""Persistent, versioned daily market-data and indicator cache."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Sequence

from sqlalchemy import text


SOURCE = "merolagani_adjusted"


def _session():
    from database import SessionLocal
    return SessionLocal()


def _bar_hash(symbol: str, day: str, values: Sequence[float]) -> str:
    payload = f"{symbol}|{day}|" + "|".join(f"{float(value):.8f}" for value in values)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def quality_flags(open_price: float, high: float, low: float, close: float, volume: float) -> List[str]:
    flags: List[str] = []
    if min(open_price, high, low, close) <= 0:
        flags.append("NON_POSITIVE_PRICE")
    if high < max(open_price, low, close) or low > min(open_price, high, close):
        flags.append("INVALID_OHLC_RANGE")
    if volume <= 0:
        flags.append("ZERO_VOLUME")
    return flags


def cached_history(
    symbol: str, start_date: date, end_date: date, *, source: str = SOURCE,
) -> Optional[List[Dict[str, Any]]]:
    """Return cached rows only when a completed fetch covers the requested range."""
    session = _session()
    try:
        state = session.execute(
            text(
                """SELECT requested_start, requested_end, status
                   FROM market_history_cache_state
                   WHERE symbol = :symbol AND source = :source AND adjusted = TRUE"""
            ),
            {"symbol": symbol, "source": source},
        ).mappings().first()
        if not state or state["status"] != "ready":
            return None
        if state["requested_start"] and state["requested_start"] > start_date:
            return None
        if state["requested_end"] and state["requested_end"] < end_date:
            return None
        return [dict(row) for row in session.execute(
            text(
                """SELECT session_date, source_timestamp, open_price, high_price,
                          low_price, close_price, volume, quality_flags
                   FROM market_ohlcv_daily
                   WHERE symbol = :symbol AND source = :source AND adjusted = TRUE
                     AND session_date BETWEEN :start_date AND :end_date
                   ORDER BY session_date"""
            ),
            {"symbol": symbol, "source": source, "start_date": start_date, "end_date": end_date},
        ).mappings().all()]
    finally:
        session.close()


def available_history(symbol: str, start_date: date, end_date: date, *, source: str = SOURCE) -> List[Dict[str, Any]]:
    """Return the cached portion of a range so refreshes fetch only its missing tail."""
    session = _session()
    try:
        return [dict(row) for row in session.execute(text(
            """SELECT session_date, source_timestamp, open_price, high_price,
                      low_price, close_price, volume, quality_flags
               FROM market_ohlcv_daily
               WHERE symbol=:symbol AND source=:source AND adjusted=TRUE
                 AND session_date BETWEEN :start_date AND :end_date
               ORDER BY session_date"""
        ), {"symbol": symbol, "source": source, "start_date": start_date, "end_date": end_date}).mappings().all()]
    finally:
        session.close()


def store_history(
    symbol: str, bars: Sequence[Any], requested_start: date, requested_end: date,
    *, source: str = SOURCE,
) -> None:
    session = _session()
    try:
        rows = []
        hashes: List[str] = []
        for bar in bars:
            day = str(bar.day)
            values = (bar.open, bar.high, bar.low, bar.close, bar.volume)
            content_hash = _bar_hash(symbol, day, values)
            hashes.append(content_hash)
            rows.append({
                "symbol": symbol, "session_date": day, "source": source,
                "open_price": float(bar.open), "high_price": float(bar.high),
                "low_price": float(bar.low), "close_price": float(bar.close),
                "volume": float(bar.volume), "source_timestamp": int(bar.timestamp),
                "quality_flags": json.dumps(quality_flags(*values)), "content_hash": content_hash,
            })
        if rows:
            session.execute(
                text(
                    """INSERT INTO market_ohlcv_daily
                       (symbol, session_date, source, adjusted, open_price, high_price,
                        low_price, close_price, volume, source_timestamp, quality_flags, content_hash)
                       VALUES (:symbol, :session_date, :source, TRUE, :open_price, :high_price,
                               :low_price, :close_price, :volume, :source_timestamp,
                               CAST(:quality_flags AS JSONB), :content_hash)
                       ON CONFLICT (symbol, session_date, source, adjusted) DO UPDATE SET
                         open_price = EXCLUDED.open_price, high_price = EXCLUDED.high_price,
                         low_price = EXCLUDED.low_price, close_price = EXCLUDED.close_price,
                         volume = EXCLUDED.volume, source_timestamp = EXCLUDED.source_timestamp,
                         quality_flags = EXCLUDED.quality_flags, content_hash = EXCLUDED.content_hash,
                         fetched_at = NOW()"""
                ),
                rows,
            )
        data_hash = hashlib.sha256("".join(hashes).encode("utf-8")).hexdigest()
        session.execute(
            text(
                """INSERT INTO market_history_cache_state
                   (symbol, source, adjusted, requested_start, requested_end, history_start,
                    history_end, bars_count, status, error, data_hash, fetched_at)
                   VALUES (:symbol, :source, TRUE, :requested_start, :requested_end,
                           :history_start, :history_end, :bars_count, 'ready', NULL, :data_hash, NOW())
                   ON CONFLICT (symbol, source, adjusted) DO UPDATE SET
                     requested_start = LEAST(market_history_cache_state.requested_start, EXCLUDED.requested_start),
                     requested_end = GREATEST(market_history_cache_state.requested_end, EXCLUDED.requested_end),
                     history_start = EXCLUDED.history_start, history_end = EXCLUDED.history_end,
                     bars_count = EXCLUDED.bars_count, status = 'ready', error = NULL,
                     data_hash = EXCLUDED.data_hash, fetched_at = NOW()"""
            ),
            {
                "symbol": symbol, "source": source, "requested_start": requested_start,
                "requested_end": requested_end,
                "history_start": bars[0].day if bars else None,
                "history_end": bars[-1].day if bars else None,
                "bars_count": len(bars), "data_hash": data_hash,
            },
        )
        session.commit()
    finally:
        session.close()


def store_cache_failure(symbol: str, requested_start: date, requested_end: date, error: str) -> None:
    session = _session()
    try:
        session.execute(
            text(
                """INSERT INTO market_history_cache_state
                   (symbol, source, adjusted, requested_start, requested_end, status, error)
                   VALUES (:symbol, :source, TRUE, :start_date, :end_date, 'failed', :error)
                   ON CONFLICT (symbol, source, adjusted) DO UPDATE SET
                     status = 'failed', error = EXCLUDED.error, fetched_at = NOW()"""
            ),
            {"symbol": symbol, "source": SOURCE, "start_date": requested_start, "end_date": requested_end, "error": error[:2000]},
        )
        session.commit()
    finally:
        session.close()


def store_indicator_history(symbol: str, bars: Sequence[Any], rows: Sequence[Dict[str, Any]], engine_version: str) -> None:
    """Persist the point-in-time indicator rows in bounded batches."""
    if not bars or len(bars) != len(rows):
        return
    session = _session()
    try:
        payloads = []
        for bar, indicators in zip(bars, rows):
            payloads.append({
                "symbol": symbol, "session_date": bar.day, "engine_version": engine_version,
                "rsi": indicators.get("technical_rsi_14"),
                "macd": indicators.get("technical_macd_histogram"),
                "adx": indicators.get("technical_adx_14"),
                "atr": indicators.get("technical_atr_percent"),
                "mfi": indicators.get("technical_mfi_14"),
                "volume_ratio": indicators.get("technical_volume_ratio_20"),
                "signal": indicators.get("technical_signal"),
                "signal_score": indicators.get("technical_signal_score"),
                "indicators": json.dumps({key: value for key, value in indicators.items() if key.startswith("technical_")}),
            })
        statement = text(
            """INSERT INTO market_indicator_daily
               (symbol, session_date, engine_version, rsi_14, macd_histogram, adx_14,
                atr_percent, mfi_14, volume_ratio_20, signal, signal_score, indicators)
               VALUES (:symbol, :session_date, :engine_version, :rsi, :macd, :adx,
                       :atr, :mfi, :volume_ratio, :signal, :signal_score, CAST(:indicators AS JSONB))
               ON CONFLICT (symbol, session_date, engine_version) DO UPDATE SET
                 rsi_14 = EXCLUDED.rsi_14, macd_histogram = EXCLUDED.macd_histogram,
                 adx_14 = EXCLUDED.adx_14, atr_percent = EXCLUDED.atr_percent,
                 mfi_14 = EXCLUDED.mfi_14, volume_ratio_20 = EXCLUDED.volume_ratio_20,
                 signal = EXCLUDED.signal, signal_score = EXCLUDED.signal_score,
                 indicators = EXCLUDED.indicators, calculated_at = NOW()"""
        )
        for index in range(0, len(payloads), 500):
            session.execute(statement, payloads[index:index + 500])
        session.commit()
    finally:
        session.close()


def cache_summary() -> Dict[str, Any]:
    session = _session()
    try:
        row = session.execute(text(
            """SELECT COUNT(DISTINCT symbol) symbols, COUNT(*) bars,
                      MIN(session_date) history_start, MAX(session_date) history_end,
                      COUNT(*) FILTER (WHERE quality_flags <> '[]'::jsonb) flagged_bars
               FROM market_ohlcv_daily WHERE adjusted = TRUE"""
        )).mappings().one()
        return {
            "symbols": int(row["symbols"] or 0), "bars": int(row["bars"] or 0),
            "history_start": row["history_start"].isoformat() if row["history_start"] else None,
            "history_end": row["history_end"].isoformat() if row["history_end"] else None,
            "flagged_bars": int(row["flagged_bars"] or 0),
        }
    finally:
        session.close()
