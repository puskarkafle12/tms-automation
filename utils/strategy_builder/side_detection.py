from __future__ import annotations

import re
from typing import Optional


BUY_PATTERNS = (
    re.compile(r"\b(buy|purchase|acquire|go long|enter long|long entry)\b", re.IGNORECASE),
)
SELL_PATTERNS = (
    re.compile(r"\b(sell|exit|dispose|take profit|stop out|go short|short entry)\b", re.IGNORECASE),
)


def detect_instruction_side(message: str) -> Optional[str]:
    text = (message or "").strip()
    if not text:
        return None
    buy_hit = any(pattern.search(text) for pattern in BUY_PATTERNS)
    sell_hit = any(pattern.search(text) for pattern in SELL_PATTERNS)
    if buy_hit and sell_hit:
        return None
    if buy_hit:
        return "BUY"
    if sell_hit:
        return "SELL"
    return None


def validate_instruction_side(message: str, portal_side: str) -> Optional[str]:
    detected = detect_instruction_side(message)
    if not detected:
        return None
    expected = (portal_side or "").strip().upper()
    if expected in {"BUY", "SELL"} and detected != expected:
        return (
            f"The instruction describes a {detected} strategy, but the form is in {expected} mode. "
            f"Switch to {detected.title()} or rewrite the instruction."
        )
    return None
