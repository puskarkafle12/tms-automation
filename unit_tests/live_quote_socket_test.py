import asyncio
from types import SimpleNamespace

import pytest

from utils.live_quote_socket import LiveQuoteSocketManager, is_live_socket_snapshot, _looks_like_auth_error


def test_is_live_socket_snapshot_requires_live_status_and_quote() -> None:
    assert is_live_socket_snapshot({
        "status": "live",
        "fresh": True,
        "quote": {"ltp": 1},
    })
    assert not is_live_socket_snapshot({
        "status": "failed",
        "fresh": True,
        "quote": {"ltp": 1},
    })
    assert not is_live_socket_snapshot({
        "status": "live",
        "fresh": False,
        "quote": {"ltp": 1},
    })


class DummyTask:
    def __init__(self, done: bool = True) -> None:
        self._done = done
        self.cancelled = False

    def done(self) -> bool:
        return self._done

    def cancel(self) -> None:
        self.cancelled = True

    def __await__(self):
        async def _completed():
            return None

        return _completed().__await__()


@pytest.mark.asyncio
async def test_ensure_stream_restarts_failed_socket_task(monkeypatch) -> None:
    manager = LiveQuoteSocketManager()
    old_task = DummyTask(done=True)
    manager._streams["NABIL"] = {
        "symbol": "NABIL",
        "security_id": "123",
        "status": "failed",
        "message_count": 1,
        "error_count": 1,
        "last_error": "timeout",
        "auth_failed": False,
        "started_at": "2026-07-05T00:00:00+00:00",
        "last_requested_at": "2026-07-05T00:00:00+00:00",
        "last_received_at": "2026-07-05T00:00:00+00:00",
        "last_received_monotonic": 0.0,
        "quote_signature": "sig",
        "quote": {"ltp": 100},
        "market_open": True,
        "quote_event": asyncio.Event(),
        "task": old_task,
    }

    created_tasks = []

    def fake_create_task(coro):
        coro.close()
        task = DummyTask(done=False)
        created_tasks.append(task)
        return task

    monkeypatch.setattr("utils.live_quote_socket._market_is_open_now", lambda: True)
    monkeypatch.setattr(asyncio, "create_task", fake_create_task)

    snapshot = await manager.ensure_stream(
        SimpleNamespace(login_response={"request_owner": "a", "client_dealer_id": "b"}, tokens={}, broker_no="1"),
        "NABIL",
        "123",
    )

    assert old_task.cancelled is True
    assert len(created_tasks) == 1
    assert snapshot["status"] == "connecting"
def test_looks_like_auth_error_detects_auth_failures() -> None:
    assert _looks_like_auth_error("401 Unauthorized")
    assert _looks_like_auth_error("Authentication expired. Please log in again.")
    assert _looks_like_auth_error("Token expired")


def test_looks_like_auth_error_ignores_non_auth_errors() -> None:
    assert not _looks_like_auth_error("Timeout on reading data from socket")
    assert not _looks_like_auth_error("Connection reset by peer")
