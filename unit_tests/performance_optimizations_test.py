import asyncio
import importlib.util
import time
import unittest


@unittest.skipIf(importlib.util.find_spec("aiohttp") is None, "aiohttp is not installed")
class TestTmsPerformanceOptimizations(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from utils.tms import TmsUser

        self.TmsUser = TmsUser
        self.TmsUser.clear_security_cache()

    async def asyncTearDown(self):
        self.TmsUser.clear_security_cache()

    async def test_tms_user_session_is_lazy_and_reused(self):
        user = self.TmsUser(broker_no="35", username="u", password="p", request_per_sec=1)

        self.assertIsNone(user.session)
        await user._ensure_session()
        first_session = user.session
        await user._ensure_session()

        self.assertIs(first_session, user.session)
        await user.close()

    async def test_security_lookup_uses_broker_cache(self):
        self.TmsUser._security_cache["35"] = (
            time.monotonic(),
            [{"symbol": "ABC", "id": 101}, {"symbol": "XYZ", "id": 202}],
        )
        user = self.TmsUser(broker_no="35", username="u", password="p")

        security = await user.get_security_id("xyz")

        self.assertEqual(security["id"], 202)
        self.assertIsNone(user.session)

    async def test_quote_fetch_default_has_no_retry_backoff_sleep(self):
        user = self.TmsUser(broker_no="35", username="u", password="p")
        sleeps = []

        async def fake_sleep(delay):
            sleeps.append(delay)

        original_sleep = asyncio.sleep
        asyncio.sleep = fake_sleep
        try:
            result = await user.get_stock_details_async("1", max_retries=0)
        finally:
            asyncio.sleep = original_sleep
            await user.close()

        self.assertIsNone(result)
        self.assertEqual(sleeps, [])

    async def test_authenticated_request_refreshes_token_once_on_401(self):
        user = self.TmsUser(broker_no="35", username="u", password="p")
        user.headers = {"x-xsrf-token": "old"}
        user.tokens = {"JSESSIONID": "old"}
        refreshes = []

        class FakeResponse:
            def __init__(self, status, payload):
                self.status = status
                self._payload = payload
                self.request_info = None
                self.history = ()
                self.reason = "Unauthorized" if status == 401 else "OK"
                self.headers = {}

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def read(self):
                return b""

            async def json(self, content_type=None):
                return self._payload

            def raise_for_status(self):
                raise AssertionError("raise_for_status should not be called")

        class FakeSession:
            closed = False

            def __init__(self):
                self.calls = []

            def request(self, method, url, **kwargs):
                self.calls.append((method, url, kwargs))
                if len(self.calls) == 1:
                    return FakeResponse(401, {"message": "Unauthorized"})
                return FakeResponse(200, {"ok": True})

        async def fake_refresh(reason="access token expired"):
            refreshes.append(reason)
            user.headers = {"x-xsrf-token": "new"}
            user.tokens = {"JSESSIONID": "new"}

        fake_session = FakeSession()
        user.session = fake_session
        user._refresh_authentication = fake_refresh

        status, payload = await user._authenticated_request(
            "GET",
            "https://tms35.nepsetms.com.np/tmsapi/example",
            expected_statuses={200},
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload, {"ok": True})
        self.assertEqual(refreshes, ["access token expired"])
        self.assertEqual(len(fake_session.calls), 2)
        self.assertEqual(fake_session.calls[0][2]["headers"], {"x-xsrf-token": "old"})
        self.assertEqual(fake_session.calls[1][2]["headers"], {"x-xsrf-token": "new"})


if __name__ == "__main__":
    unittest.main()
