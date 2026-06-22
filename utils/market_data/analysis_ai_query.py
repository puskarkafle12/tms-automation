"""AI screener using combined DB cache (no live fetch)."""

from __future__ import annotations

from typing import Awaitable, Callable, Dict, Optional

from sqlalchemy.orm import Session

from utils.external_data_sources.nepse_alpha.ai_query import ScreenerAiError, execute_ai_screener_with_retries
from utils.market_data.combined_screener import run_combined_screener_from_db
from utils.market_data.dynamic_catalog import build_dynamic_ai_system_prompts


async def execute_combined_ai_screener(
    message: str,
    screener_runner: Callable[[dict], Awaitable[dict]],
    db: Optional[Session] = None,
) -> Dict:
    if db is None:
        raise ScreenerAiError("Database session is required for combined AI screener.")

    from database import ensure_read_session

    ensure_read_session(db)
    system_prompt, compact_system_prompt = build_dynamic_ai_system_prompts(db)
    return await execute_ai_screener_with_retries(
        message,
        screener_runner,
        db=db,
        system_prompt=system_prompt,
        compact_system_prompt=compact_system_prompt,
    )


__all__ = ["execute_combined_ai_screener", "ScreenerAiError"]
