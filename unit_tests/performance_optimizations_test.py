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

    async def test_available_collateral_calculation(self):
        collateral = self.TmsUser.calculate_available_collateral({
            "collateralAmount": 200000.0,
            "utilizedcollateralAmount": 200460.0,
            "collateralMultiplicationFactor": 1.0,
        })

        self.assertEqual(collateral["collateralAmount"], 200000.0)
        self.assertEqual(collateral["utilizedcollateralAmount"], 200460.0)
        self.assertEqual(collateral["collateralMultiplicationFactor"], 1.0)
        self.assertEqual(collateral["availableCollateral"], -460.0)

    async def test_stock_grabber_cancels_previous_matching_orders_after_new_order(self):
        user = self.TmsUser(
            broker_no="35",
            username="u",
            password="p",
            stock_symbol="ABC",
            resume_previous_ltp=100,
        )
        cancelled_order_ids = []
        order_book_calls = 0

        before_order_book = [
            {"exchangeOrderId": "old-abc", "symbol": "ABC"},
            {"exchangeOrderId": "old-xyz", "symbol": "XYZ"},
        ]
        after_order_book = [
            {"exchangeOrderId": "old-abc", "symbol": "ABC"},
            {"exchangeOrderId": "new-abc", "symbol": "ABC"},
            {"exchangeOrderId": "old-xyz", "symbol": "XYZ"},
        ]

        async def fake_ensure_session():
            return None

        async def fake_get_security_id(symbol):
            return {"id": "1", "symbol": symbol}

        async def fake_price_scanner(security_id, previous_ltp, session_id):
            return {
                "twoPercentHigh": 103,
                "changePercentage": 2,
                "ltp": 101,
            }

        async def fake_order(order_price, order_quantity, order_type, security=None):
            return {"status": 200, "message": "placed"}

        async def fake_get_order_book():
            nonlocal order_book_calls
            order_book_calls += 1
            return before_order_book if order_book_calls == 1 else after_order_book

        async def fake_cancel_order(exchange_order_id):
            cancelled_order_ids.append(exchange_order_id)
            return {"status": 200}

        user._ensure_session = fake_ensure_session
        user.get_security_id = fake_get_security_id
        user.price_scanner = fake_price_scanner
        user.order = fake_order
        user.get_order_book = fake_get_order_book
        user.cancel_order = fake_cancel_order

        result = await user.stock_grabber(
            order_quantity=10,
            session_id="test-session",
            max_order_limit=1,
        )

        self.assertEqual(result["message"], "successfully ordered shares")
        self.assertEqual(cancelled_order_ids, ["old-abc"])
        self.assertTrue(
            any(
                update.get("message") == "Cancelled 1 previous ABC order(s)"
                for update in user.updates
            )
        )


if __name__ == "__main__":
    unittest.main()
