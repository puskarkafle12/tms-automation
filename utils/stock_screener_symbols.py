"""Resolve symbol universes for the stock screener."""

from __future__ import annotations

from typing import Dict, Iterable, List, Literal, Optional, Sequence

from fastapi import HTTPException
from sqlalchemy.orm import Session

from exceptions.login_exceptions import LoginFailedException
from models.logged_in_user import LoggedInUsers
from utils.strategy_builder.holdings_preflight import build_holdings_map
from utils.tms_client_resolver import get_tms_user_for_client

ScreenerUniverse = Literal["nepse", "combined_holdings", "client_holdings"]


def symbols_from_holdings(holdings: Dict[str, int]) -> List[str]:
    """Return sorted symbols with a positive holding quantity."""
    return sorted(symbol for symbol, qty in holdings.items() if qty > 0)


def union_holdings_maps(maps: Iterable[Dict[str, int]]) -> List[str]:
    """Union DP holdings across maps, summing quantities per symbol."""
    combined: Dict[str, int] = {}
    for holdings in maps:
        for symbol, qty in holdings.items():
            combined[symbol] = combined.get(symbol, 0) + int(qty)
    return symbols_from_holdings(combined)


def _normalize_explicit_symbols(symbols: Optional[Sequence[str]]) -> List[str]:
    return sorted(
        {
            str(symbol).strip().upper()
            for symbol in (symbols or [])
            if symbol and str(symbol).strip()
        }
    )


def _logged_in_client_ids(db: Session, client_ids: Optional[Sequence[str]] = None) -> List[str]:
    query = db.query(LoggedInUsers).filter(LoggedInUsers.status == "logged_in")
    if client_ids:
        normalized = [str(client_id).strip() for client_id in client_ids if str(client_id).strip()]
        if normalized:
            query = query.filter(LoggedInUsers.client_id.in_(normalized))
    rows = query.all()
    return [row.client_id for row in rows if row.client_id]


async def _resolve_nepse_symbols(db: Session, client_ids: Optional[Sequence[str]] = None) -> List[str]:
    ids = _logged_in_client_ids(db, client_ids)
    if not ids:
        raise HTTPException(
            status_code=400,
            detail="At least one logged-in TMS account is required to load the NEPSE symbol universe.",
        )

    last_error: Optional[str] = None
    for client_id in ids:
        tms_user = None
        try:
            tms_user = await get_tms_user_for_client(client_id, db)
            securities = await tms_user.get_securities()
            symbols = sorted(
                {
                    str(item.get("symbol") or "").strip().upper()
                    for item in securities
                    if str(item.get("symbol") or "").strip()
                }
            )
            if symbols:
                return symbols
        except LoginFailedException as exc:
            last_error = str(exc)
        except ValueError as exc:
            last_error = str(exc)
        except Exception as exc:
            last_error = str(exc)
        finally:
            if tms_user is not None:
                await tms_user.close()

    detail = "Could not load NEPSE symbols from any logged-in TMS account."
    if last_error:
        detail = f"{detail} Last error: {last_error}"
    raise HTTPException(status_code=400, detail=detail)


async def _resolve_combined_holdings_symbols(
    db: Session,
    client_ids: Optional[Sequence[str]] = None,
) -> List[str]:
    ids = _logged_in_client_ids(db, client_ids)
    if not ids:
        raise HTTPException(
            status_code=400,
            detail="At least one logged-in TMS account is required to load combined DP holdings.",
        )

    holdings_maps: List[Dict[str, int]] = []
    errors: List[str] = []
    for client_id in ids:
        tms_user = None
        try:
            tms_user = await get_tms_user_for_client(client_id, db)
            holdings_maps.append(await build_holdings_map(tms_user))
        except LoginFailedException as exc:
            errors.append(f"{client_id}: {exc}")
        except ValueError as exc:
            errors.append(f"{client_id}: {exc}")
        except Exception as exc:
            errors.append(f"{client_id}: {exc}")
        finally:
            if tms_user is not None:
                await tms_user.close()

    symbols = union_holdings_maps(holdings_maps)
    if symbols:
        return symbols

    detail = "No DP holdings with quantity > 0 found across selected users."
    if errors:
        detail = f"{detail} Errors: {'; '.join(errors)}"
    raise HTTPException(status_code=400, detail=detail)


async def _resolve_client_holdings_symbols(db: Session, client_id: str) -> List[str]:
    normalized = str(client_id or "").strip()
    if not normalized:
        raise HTTPException(
            status_code=400,
            detail="client_id is required when universe is client_holdings.",
        )

    tms_user = None
    try:
        tms_user = await get_tms_user_for_client(normalized, db)
        holdings = await build_holdings_map(tms_user)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LoginFailedException as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    finally:
        if tms_user is not None:
            await tms_user.close()

    symbols = symbols_from_holdings(holdings)
    if not symbols:
        raise HTTPException(
            status_code=400,
            detail=f"No DP holdings with quantity > 0 found for client {normalized}.",
        )
    return symbols


async def resolve_screener_symbols(
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
        return await _resolve_nepse_symbols(db, client_ids)
    if universe == "combined_holdings":
        return await _resolve_combined_holdings_symbols(db, client_ids)
    if universe == "client_holdings":
        return await _resolve_client_holdings_symbols(db, client_id or "")

    raise HTTPException(status_code=400, detail=f"Unsupported universe: {universe}")


def screener_universe_label(
    universe: ScreenerUniverse,
    *,
    client_id: Optional[str] = None,
    symbol_count: int = 0,
) -> str:
    if universe == "nepse":
        return f"NEPSE ({symbol_count} symbols)"
    if universe == "combined_holdings":
        return f"Combined holdings ({symbol_count} symbols)"
    if universe == "client_holdings":
        client = (client_id or "").strip() or "client"
        return f"{client} holdings ({symbol_count} symbols)"
    return f"Universe ({symbol_count} symbols)"
