"""AI screener using combined Merolagani + Nepse Alpha field catalog."""

from __future__ import annotations

from typing import Awaitable, Callable, Dict

from utils.external_data_sources.nepse_alpha import ai_query
from utils.external_data_sources.nepse_alpha.ai_query import ScreenerAiError, execute_ai_screener_with_retries
from utils.market_data.combined_screener import (
    get_combined_field_catalog,
    get_combined_query_spec,
    parse_combined_screener_query,
)


async def execute_combined_ai_screener(
    message: str,
    screener_runner: Callable[[dict], Awaitable[dict]],
) -> Dict:
    import utils.external_data_sources.nepse_alpha.query_parser as query_parser

    old_catalog = ai_query.get_field_catalog
    old_spec = ai_query.get_screener_query_spec
    old_parse = query_parser.parse_screener_query
    try:
        ai_query.get_field_catalog = get_combined_field_catalog
        ai_query.get_screener_query_spec = get_combined_query_spec
        query_parser.parse_screener_query = parse_combined_screener_query
        return await execute_ai_screener_with_retries(message, screener_runner)
    finally:
        ai_query.get_field_catalog = old_catalog
        ai_query.get_screener_query_spec = old_spec
        query_parser.parse_screener_query = old_parse


__all__ = ["execute_combined_ai_screener", "ScreenerAiError"]
