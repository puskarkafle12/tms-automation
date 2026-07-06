from types import SimpleNamespace

import pytest

import utils.live_quote_socket as live_quote_socket


@pytest.mark.asyncio
async def test_ensure_stream_refuses_to_start_when_market_closed(monkeypatch) -> None:
    manager = live_quote_socket.LiveQuoteSocketManager()
    monkeypatch.setattr(live_quote_socket, "_market_is_open_now", lambda: False)

    snapshot = await manager.ensure_stream(
        SimpleNamespace(login_response={}, tokens={}, broker_no="1"),
        "NABIL",
        "123",
    )

    assert snapshot["status"] == "closed"
    assert snapshot["market_open"] is False
    assert manager.get_snapshot("NABIL") is None


@pytest.mark.asyncio
async def test_wait_for_next_quote_short_circuits_when_market_closed(monkeypatch) -> None:
    manager = live_quote_socket.LiveQuoteSocketManager()
    monkeypatch.setattr(live_quote_socket, "_market_is_open_now", lambda: False)

    assert await manager.wait_for_next_quote("NABIL", timeout=1.0) is None
