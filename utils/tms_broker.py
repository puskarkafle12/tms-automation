"""TMS broker host helpers (no TmsUser import — safe for tms.py and resolvers)."""

from __future__ import annotations

import re
from typing import Optional


def normalize_broker_no(value: Optional[str]) -> str:
    """Return TMS broker segment for tms{broker}.nepsetms.com.np (usually 2–3 digits)."""
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("Broker number is missing for this TMS account.")
    digits = re.sub(r"\D+", "", raw)
    if digits:
        if len(digits) > 4:
            raise ValueError(
                f"Broker number {raw!r} looks like a client ID, not a TMS broker host. "
                "Use the numeric broker id from your TMS login URL (e.g. 58, 57, 35)."
            )
        return digits
    return raw


def tms_host_for_broker(broker_no: str) -> str:
    broker = normalize_broker_no(broker_no)
    return f"tms{broker}.nepsetms.com.np"
