import pytest

from utils.tms import TmsUser


@pytest.mark.asyncio
async def test_stock_grabber_stops_when_volume_exceeds_threshold(monkeypatch) -> None:
    user = TmsUser(
        username="client-1",
        password="secret",
        broker_no="1",
        stock_symbol="KAHL",
        resume_previous_ltp=100.0,
    )

    async def fake_ensure_session() -> None:
        return None

    async def fake_get_security_id(symbol: str):
        return {"id": "123", "symbol": symbol}

    async def fake_price_scanner(*args, **kwargs):
        return {
            "twoPercentHigh": 120,
            "changePercentage": 1.2,
            "ltp": 100,
            "volume": 6000,
            "security": {"symbol": "KAHL"},
        }

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("order() should not be called when volume threshold is exceeded")

    monkeypatch.setattr(user, "_ensure_session", fake_ensure_session)
    monkeypatch.setattr(user, "get_security_id", fake_get_security_id)
    monkeypatch.setattr(user, "price_scanner", fake_price_scanner)
    monkeypatch.setattr(user, "order", fail_if_called)

    result = await user.stock_grabber(
        order_quantity=10,
        session_id="session-1",
        max_order_limit=1,
        stop_buy_after_percent=15,
        stop_buy_after_volume=5000,
    )

    assert result["stop_reason"] == "stop_buy_after_volume"
    assert result["totalOrders"] == []
    assert user.stop_buy_after_volume == 5000
