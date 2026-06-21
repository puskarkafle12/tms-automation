"""Resolve symbol universes for database-backed market analysis."""

from __future__ import annotations

from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from utils.stock_screener_symbols import (
    ScreenerUniverse,
    _normalize_explicit_symbols,
    _resolve_client_holdings_symbols,
    _resolve_combined_holdings_symbols,
    screener_universe_label,
)


def load_cached_symbol_universe(db: Session) -> List[str]:
    rows = db.execute(text("SELECT symbol FROM market_screener_cache ORDER BY symbol ASC")).scalars().all()
    symbols = sorted({str(item).strip().upper() for item in rows if str(item).strip()})
    if not symbols:
        raise HTTPException(
            status_code=503,
            detail="Market analysis cache is empty. Wait for the next market-hours refresh or check server logs.",
        )
    return symbols


async def resolve_analysis_symbols(
    *,
    universe: ScreenerUniverse = "nepse",
    client_id: Optional[str] = None,
    client_ids: Optional[List[str]] = None,
    symbols: Optional[List[str]] = None,
    db: Session,
) -> List[str]:
    explicit = _normalize_explicit_symbols(symbols)
    if explicit:
        return explicit

    if universe == "nepse":
        return load_cached_symbol_universe(db)

    holdings_symbols = (
        await _resolve_combined_holdings_symbols(db, client_ids)
        if universe == "combined_holdings"
        else await _resolve_client_holdings_symbols(db, client_id or "")
    )
    cached = set(load_cached_symbol_universe(db))
    filtered = sorted(symbol for symbol in holdings_symbols if symbol in cached)
    if not filtered:
        raise HTTPException(
            status_code=400,
            detail="No cached market data found for the selected holdings symbols.",
        )
    return filtered


__all__ = ["resolve_analysis_symbols", "load_cached_symbol_universe", "screener_universe_label"]
