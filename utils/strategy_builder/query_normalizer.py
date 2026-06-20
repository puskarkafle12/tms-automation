from __future__ import annotations

import re

# Entire input wrapped in a single Markdown code fence (optional language label on line 1).
_OUTER_MARKDOWN_FENCE = re.compile(
    r"^```([^\n`]*)\r?\n([\s\S]*?)\r?\n```\s*$",
)


class StrategyQueryNormalizationError(ValueError):
    """Raised when strategy query text cannot be normalized safely."""


def normalize_strategy_query_text(query_text: str) -> str:
    """
    Normalize strategy query input before parsing.

    1. Trim leading/trailing whitespace.
    2. Remove a single outer Markdown ``` fence (optional language label).
    3. Trim again.
    4. Reject any remaining backticks inside the strategy body.
    """
    text = (query_text or "").strip()
    if not text:
        return text

    fence_match = _OUTER_MARKDOWN_FENCE.match(text)
    if fence_match:
        text = fence_match.group(2).strip()
    elif text.startswith("```"):
        raise StrategyQueryNormalizationError(
            "Strategy query opening Markdown fence is missing a closing ```."
        )

    if "`" in text:
        raise StrategyQueryNormalizationError(
            "Strategy query must not contain backticks (`). "
            "Remove Markdown formatting from inside the strategy text."
        )

    return text.strip()
