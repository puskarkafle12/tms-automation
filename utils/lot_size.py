from typing import Any, Mapping, Optional


DEFAULT_BOARD_LOT_SIZE = 10


def _positive_number(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def get_board_lot_size(scrip: Optional[Mapping[str, Any]]) -> int:
    metadata = scrip or {}
    nested = metadata.get("security") if isinstance(metadata.get("security"), Mapping) else {}
    configured = (
        _positive_number(metadata.get("lotSize"))
        or _positive_number(metadata.get("boardLot"))
        or _positive_number(metadata.get("boardLotSize"))
        or _positive_number(nested.get("lotSize"))
        or _positive_number(nested.get("boardLot"))
        or _positive_number(nested.get("boardLotSize"))
    )
    if configured:
        return max(1, int(configured))

    face_value = _positive_number(metadata.get("faceValue")) or _positive_number(nested.get("faceValue"))
    if face_value == 100:
        return 10
    if face_value == 10:
        return 100
    if face_value == 1000:
        return 1
    return DEFAULT_BOARD_LOT_SIZE


def is_odd_lot_qty(qty: int, lot_size: int) -> bool:
    return qty > 0 and qty < lot_size


def is_regular_lot_qty(qty: int, lot_size: int) -> bool:
    return qty > 0 and qty % max(1, lot_size) == 0


def round_down_to_board_lot(qty: int, lot_size: int) -> int:
    size = max(1, lot_size)
    return max(0, qty) // size * size


def would_leave_odd_remainder(holding_qty: int, sell_qty: int, lot_size: int) -> bool:
    remaining = holding_qty - sell_qty
    return remaining > 0 and remaining < lot_size


def normalize_sell_qty(desired_qty: int, holding_qty: int, lot_size: int) -> dict:
    size = max(1, lot_size)
    requested = max(0, int(desired_qty or 0))
    holding = max(0, int(holding_qty or 0))

    if requested >= holding:
        return {
            "qty": holding,
            "remaining": 0,
            "is_sell_all": True,
            "warning": None
            if is_regular_lot_qty(holding, size)
            else "Sell All may include odd-lot quantity because your holding is not a board-lot multiple.",
        }

    rounded_qty = round_down_to_board_lot(requested, size)
    initial_remaining = holding - rounded_qty
    if 0 < initial_remaining < size:
        rounded_qty -= size
    if rounded_qty <= 0:
        return {
            "qty": 0,
            "remaining": holding,
            "is_sell_all": False,
            "error": "Partial sell would leave odd-lot shares. Use Sell All or adjust quantity.",
        }

    warning = None
    if rounded_qty != requested:
        requested_remaining = holding - requested
        if 0 < requested_remaining < size:
            warning = (
                f"Selling {requested} would leave {requested_remaining} kitta odd lot. "
                f"Suggested safe quantity: {rounded_qty}."
            )
        else:
            warning = f"Suggested board-lot safe quantity: {rounded_qty}."

    return {
        "qty": rounded_qty,
        "remaining": holding - rounded_qty,
        "is_sell_all": False,
        "warning": warning,
    }
