"""Dedicated executor for market-data blocking work."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any, Callable

_MARKET_DATA_EXECUTOR = ThreadPoolExecutor(
    max_workers=2,
    thread_name_prefix="market-data",
)
_EXCLUSIVE_MARKET_JOB_LOCK = asyncio.Lock()
_exclusive_market_job_active = False


class MarketDataJobBusy(RuntimeError):
    """Raised when a caller chooses not to queue behind active market work."""


async def run_market_blocking(
    func: Callable[..., Any],
    *args: Any,
    exclusive: bool = False,
    skip_if_busy: bool = False,
    **kwargs: Any,
) -> Any:
    """Run blocking market-data code away from the app's default thread pool."""
    loop = asyncio.get_running_loop()
    call = partial(func, *args, **kwargs)
    if exclusive:
        global _exclusive_market_job_active
        while True:
            async with _EXCLUSIVE_MARKET_JOB_LOCK:
                if not _exclusive_market_job_active:
                    _exclusive_market_job_active = True
                    break
                if skip_if_busy:
                    raise MarketDataJobBusy("market data job is already running")
            await asyncio.sleep(0.1)
        try:
            return await loop.run_in_executor(_MARKET_DATA_EXECUTOR, call)
        finally:
            async with _EXCLUSIVE_MARKET_JOB_LOCK:
                _exclusive_market_job_active = False
    return await loop.run_in_executor(_MARKET_DATA_EXECUTOR, call)
