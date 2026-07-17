import asyncio

import pytest

from utils.market_live_state import (
    get_shared_dna_session,
    reset_shared_market_session,
)


class CountingTmsUser:
    def __init__(self, *, active=True):
        self.dna_calls = 0
        self.active = active

    async def check_exchange_session(self):
        self.dna_calls += 1
        await asyncio.sleep(0)
        return {
            "status": "success" if self.active else "failed",
            "message": "DNA logged in" if self.active else "DNA logged off",
            "data": None,
        }

@pytest.mark.asyncio
async def test_concurrent_accounts_share_one_dna_poll():
    reset_shared_market_session()
    user = CountingTmsUser()

    results = await asyncio.gather(
        get_shared_dna_session([user]),
        get_shared_dna_session([user]),
        get_shared_dna_session([user]),
    )

    assert user.dna_calls == 1
    assert all(result["session_active"] is True for result in results)


@pytest.mark.asyncio
async def test_stale_first_account_does_not_block_live_second_account():
    reset_shared_market_session()
    stale_user = CountingTmsUser(active=False)
    live_user = CountingTmsUser(active=True)

    result = await get_shared_dna_session([stale_user, live_user])

    assert result["session_active"] is True
    assert stale_user.dna_calls == 1
    assert live_user.dna_calls == 1
