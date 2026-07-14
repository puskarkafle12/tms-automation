import asyncio

import pytest

from utils.market_live_state import (
    get_shared_dna_session,
    reset_shared_market_session,
)


class CountingTmsUser:
    def __init__(self):
        self.dna_calls = 0

    async def check_exchange_session(self):
        self.dna_calls += 1
        await asyncio.sleep(0)
        return {"status": "success", "message": "DNA logged in", "data": None}

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
