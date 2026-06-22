import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import unittest

from utils.market_data.executor import MarketDataJobBusy, run_market_blocking


class MarketDataExecutorTest(unittest.IsolatedAsyncioTestCase):
    async def test_market_executor_does_not_use_default_thread_pool(self):
        loop = asyncio.get_running_loop()
        default_pool = ThreadPoolExecutor(max_workers=1)
        loop.set_default_executor(default_pool)
        blocker_release = Event()

        blocker = asyncio.create_task(asyncio.to_thread(blocker_release.wait))
        await asyncio.sleep(0.05)

        try:
            result = await asyncio.wait_for(run_market_blocking(lambda: "ok"), timeout=1)
            self.assertEqual(result, "ok")
        finally:
            blocker_release.set()
            await blocker
            default_pool.shutdown(wait=True)

    async def test_exclusive_market_job_can_skip_instead_of_queueing(self):
        release = Event()

        running = asyncio.create_task(
            run_market_blocking(lambda: release.wait(), exclusive=True)
        )
        await asyncio.sleep(0.05)

        try:
            with self.assertRaises(MarketDataJobBusy):
                await run_market_blocking(
                    lambda: "should-not-run",
                    exclusive=True,
                    skip_if_busy=True,
                )
        finally:
            release.set()
            await running


if __name__ == "__main__":
    unittest.main()
