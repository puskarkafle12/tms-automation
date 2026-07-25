"""Shared Nepal IPO aftermarket entry gate.

New listings often open strong and keep rising. In this market they are only
tradable for research once a completed session closes below its open (a red
candle). The next session is then eligible for strategy entries — no 4% move
or volume floor is required.
"""

from __future__ import annotations

IPO_WORKSPACE_TRADABILITY_GATE = (
    "PREVIOUS(field=ltp, offset=1) < PREVIOUS(field=open, offset=1)"
)
IPO_WORKSPACE_GATE_VERSION = "ipo-red-close-v5"
IPO_WORKSPACE_GATE_DESCRIPTION = (
    "a prior completed session that closed below its open (red candle); "
    "the strategy may then fire on the next session"
)

# Older workspace / preset gate strings that must be replaced, not stacked.
LEGACY_IPO_TRADABILITY_GATES = (
    (
        "PREVIOUS(field=change_percent, offset=1) <= -4 "
        "AND PREVIOUS(field=volume, offset=1) > 5000 "
        "AND PREVIOUS(field=ltp, offset=1) < PREVIOUS(field=open, offset=1)"
    ),
    (
        "PREVIOUS(field=change_percent, offset=1) <= -4 "
        "AND PREVIOUS(field=ltp, offset=1) < PREVIOUS(field=open, offset=1)"
    ),
    (
        "PREVIOUS(field=volume, offset=1) > 5000 "
        "AND PREVIOUS(field=ltp, offset=1) < PREVIOUS(field=open, offset=1)"
    ),
)


def strip_ipo_tradability_gates(condition: str) -> str:
    """Remove current and legacy IPO gates so a condition can be re-gated cleanly."""
    text = str(condition or "").strip()
    # Longest / legacy gates first so partial current-gate matches cannot
    # dismantle a fuller historical constraint before it is recognized.
    gates = sorted(
        {IPO_WORKSPACE_TRADABILITY_GATE, *LEGACY_IPO_TRADABILITY_GATES},
        key=len,
        reverse=True,
    )
    for gate in gates:
        for pattern in (
            f" AND {gate}",
            f"{gate} AND ",
            f" AND ({gate})",
            f"({gate}) AND ",
            f"({gate})",
            gate,
        ):
            text = text.replace(pattern, "")
    text = text.replace("()", "").strip()
    while text.startswith("(") and text.endswith(")") and text.count("(") == text.count(")"):
        inner = text[1:-1].strip()
        if not inner or inner.count("(") != inner.count(")"):
            break
        text = inner
    return " ".join(text.split()).strip(" &")
