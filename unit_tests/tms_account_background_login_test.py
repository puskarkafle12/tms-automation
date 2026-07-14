import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import main


class _UserQuery:
    def __init__(self, user):
        self.user = user

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.user


class _UserDb:
    def __init__(self, user):
        self.user = user
        self.closed = False

    def query(self, _model):
        return _UserQuery(self.user)

    def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_account_login_returns_accepted_and_reuses_running_task(monkeypatch):
    user = SimpleNamespace(client_id="TEST1", broker_no="35")
    db = _UserDb(user)
    login_can_finish = asyncio.Event()
    pending_calls = []

    async def slow_login(_client_id):
        await login_can_finish.wait()

    monkeypatch.setattr(main, "_run_tms_account_login", slow_login)
    monkeypatch.setattr(
        main,
        "_record_tms_login_pending",
        lambda *_args, **kwargs: pending_calls.append(kwargs),
    )
    main.tms_login_tasks.clear()

    first = await main.login_tms_account("TEST1", db)
    first_task = main.tms_login_tasks["TEST1"]
    second = await main.login_tms_account("TEST1", db)

    assert first.status_code == 202
    assert json.loads(first.body)["message"] == "TMS login started"
    assert second.status_code == 202
    assert json.loads(second.body)["message"] == "TMS login is already in progress"
    assert main.tms_login_tasks["TEST1"] is first_task
    assert len(pending_calls) == 1

    login_can_finish.set()
    await first_task
    await asyncio.sleep(0)
    assert "TEST1" not in main.tms_login_tasks


@pytest.mark.asyncio
async def test_background_login_records_unexpected_failure(monkeypatch):
    user = SimpleNamespace(client_id="TEST2", broker_no="35")
    db = _UserDb(user)
    record_failure = MagicMock()

    monkeypatch.setattr(main, "SessionLocal", lambda: db)
    monkeypatch.setattr(main, "invalidate_cached_tms_user", AsyncMock())
    monkeypatch.setattr(main, "get_cached_tms_user", AsyncMock(side_effect=RuntimeError("TMS unavailable")))
    monkeypatch.setattr(main, "_record_tms_login_failure", record_failure)

    await main._run_tms_account_login("TEST2")

    record_failure.assert_called_once_with(
        db,
        client_id="TEST2",
        broker_no="35",
        message="TMS unavailable",
    )
    assert db.closed is True
