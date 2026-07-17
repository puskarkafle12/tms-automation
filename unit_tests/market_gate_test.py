import pytest

from utils import market_gate
from utils.market_live_state import reset_shared_market_session


@pytest.fixture(autouse=True)
def reset_market_state():
    reset_shared_market_session()


class FakeTmsUser:
    def __init__(self, payload, current_session=None):
        self.payload = payload
        self.current_session = current_session
        self.current_session_calls = 0

    async def check_exchange_session(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload

    async def get_current_market_session(self):
        self.current_session_calls += 1
        if self.current_session is None:
            raise RuntimeError("Current session unavailable")
        return self.current_session


@pytest.mark.asyncio
async def test_dna_success_allows_scanning_without_current_session(monkeypatch):
    monkeypatch.setattr(market_gate, "is_market_polling_window", lambda: True)
    user = FakeTmsUser({
        "status": "success",
        "message": "Logged In Successfully",
        "data": {"dnaStatus": "LOGGED_IN"},
    }, {"currentSessions": [], "activeStatus": False})

    gate = await market_gate.resolve_market_gate({"client": user})

    assert gate["can_scan"] is True
    assert gate["can_execute"] is True
    assert gate["phase"] == "active"
    assert user.current_session_calls == 0


@pytest.mark.asyncio
async def test_only_exact_success_status_is_treated_as_live(monkeypatch):
    monkeypatch.setattr(market_gate, "is_market_polling_window", lambda: True)
    user = FakeTmsUser({
        "status": "ok",
        "message": "Logged In Successfully",
        "data": {"dnaStatus": "LOGGED_IN"},
    })

    gate = await market_gate.resolve_market_gate({"client": user})

    assert gate["can_scan"] is False
    assert gate["can_execute"] is False
    assert gate["phase"] == "waiting_exchange"


@pytest.mark.asyncio
async def test_dna_success_allows_scanning_and_execution(monkeypatch):
    monkeypatch.setattr(market_gate, "is_market_polling_window", lambda: True)
    user = FakeTmsUser({
        "status": "success",
        "message": "Logged In Successfully",
        "data": {"dnaStatus": "LOGGED_IN"},
    }, {"currentSessions": [{"sessionName": "Continuous"}], "activeStatus": True})

    gate = await market_gate.resolve_market_gate({"client": user})

    assert gate["can_scan"] is True
    assert gate["can_execute"] is True
    assert gate["phase"] == "active"


@pytest.mark.asyncio
async def test_dna_logged_off_blocks_scanning_and_execution(monkeypatch):
    monkeypatch.setattr(market_gate, "is_market_polling_window", lambda: True)
    user = FakeTmsUser({
        "status": "failed",
        "message": "DNA logged off",
        "data": None,
    }, {"currentSessions": [{"sessionName": "Continuous"}], "activeStatus": True})

    gate = await market_gate.resolve_market_gate({"client": user})

    assert gate["can_scan"] is False
    assert gate["can_execute"] is False
    assert gate["phase"] == "waiting_exchange"
    assert "DNA logged off" in gate["message"]


@pytest.mark.asyncio
async def test_one_stale_account_does_not_block_another_live_account(monkeypatch):
    monkeypatch.setattr(market_gate, "is_market_polling_window", lambda: True)
    stale_user = FakeTmsUser({
        "status": "failed",
        "message": "DNA logged off",
        "data": None,
    })
    live_user = FakeTmsUser({
        "status": "success",
        "message": "Logged In Successfully",
        "data": {"dnaStatus": "LOGGED_IN"},
    })

    gate = await market_gate.resolve_market_gate({
        "stale-client": stale_user,
        "live-client": live_user,
    })

    assert gate["can_scan"] is True
    assert gate["can_execute"] is True
    assert gate["phase"] == "active"


@pytest.mark.asyncio
async def test_dna_check_failure_blocks_scanning(monkeypatch):
    monkeypatch.setattr(market_gate, "is_market_polling_window", lambda: True)
    user = FakeTmsUser(
        RuntimeError("DNA endpoint unavailable"),
        {"currentSessions": [{"sessionName": "Continuous"}], "activeStatus": True},
    )

    gate = await market_gate.resolve_market_gate({"client": user})

    assert gate["can_scan"] is False
    assert gate["can_execute"] is False
    assert gate["phase"] == "waiting_exchange"
