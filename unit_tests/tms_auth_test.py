import importlib.util
import unittest
from unittest.mock import AsyncMock, patch


@unittest.skipIf(importlib.util.find_spec("aiohttp") is None, "aiohttp is not installed")
class TestTmsAuthFlow(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from utils.tms import TmsUser

        self.TmsUser = TmsUser

    def _sample_session(self):
        return {
            "client_dealer_id": 1669294,
            "request_owner": 34300,
            "password_expiry": "2099-01-01",
            "tokens": {"XSRF-TOKEN": "old-token", "JSESSIONID": "old-session"},
        }

    async def test_try_cached_login_uses_refresh_before_full_login(self):
        user = self.TmsUser(broker_no="35", username="client1", password="enc-pass")
        user.login_response = self._sample_session()
        user.tokens = user.login_response["tokens"]
        user.headers = user.get_header(user.login_response["request_owner"], user.tokens)
        validate_attempts = {"count": 0}

        async def fake_validate():
            validate_attempts["count"] += 1
            if validate_attempts["count"] == 1:
                raise Exception("expired")

        user.rotate_password_if_expired = AsyncMock(return_value={"rotated": False})
        user._load_session_from_store = AsyncMock(return_value=True)
        user._validate_session = fake_validate
        user.refresh_auth_token = AsyncMock(return_value=True)
        user._persist_logged_in_session = AsyncMock()
        user._full_login_and_persist = AsyncMock(return_value={"status": "success", "message": "login"})

        result = await user.try_cached_login()

        self.assertEqual(result["message"], "token refreshed without captcha")
        user.refresh_auth_token.assert_awaited_once()
        user._full_login_and_persist.assert_not_awaited()
        user._persist_logged_in_session.assert_awaited()

    async def test_try_cached_login_falls_back_to_full_login_when_refresh_fails(self):
        user = self.TmsUser(broker_no="35", username="client1", password="enc-pass")
        user.rotate_password_if_expired = AsyncMock(return_value={"rotated": False})
        user._load_session_from_store = AsyncMock(return_value=True)
        user._validate_session = AsyncMock(side_effect=Exception("expired"))
        user.refresh_auth_token = AsyncMock(return_value=False)
        user._full_login_and_persist = AsyncMock(return_value={"status": "success", "message": "login"})

        result = await user.try_cached_login()

        self.assertEqual(result["message"], "login")
        user._full_login_and_persist.assert_awaited_once()

    async def test_refresh_authentication_falls_back_to_full_login(self):
        user = self.TmsUser(broker_no="35", username="client1", password="enc-pass")
        user._load_password_from_db = AsyncMock()
        user._load_session_from_store = AsyncMock(return_value=True)
        user.refresh_auth_token = AsyncMock(return_value=False)
        user._full_login_and_persist = AsyncMock(return_value={"status": "success", "message": "login"})

        await user._refresh_authentication()

        user._full_login_and_persist.assert_awaited_once()

    @patch("utils.tms.save_tokens")
    async def test_persist_logged_in_session_marks_user_logged_in(self, save_tokens_mock):
        user = self.TmsUser(broker_no="35", username="client1", password="enc-pass")
        user.login_response = self._sample_session()
        user.tokens = user.login_response["tokens"]
        user.save_login_info = AsyncMock()

        await user._persist_logged_in_session("token refreshed without captcha")

        save_tokens_mock.assert_called_once()
        self.assertEqual(save_tokens_mock.call_args.args[0], "client1")

    async def test_refresh_auth_token_updates_xsrf_header(self):
        user = self.TmsUser(broker_no="35", username="client1", password="enc-pass")
        user.login_response = self._sample_session()
        user.tokens = dict(user.login_response["tokens"])
        user.headers = user.get_header(user.login_response["request_owner"], user.tokens)

        class FakeResponse:
            status = 200
            cookies = {"XSRF-TOKEN": "new-token", "JSESSIONID": "new-session"}

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def json(self, content_type=None):
                return {"status": "200", "message": "Token Refreshed Successfully", "data": {}}

        class FakeSession:
            closed = False

            def post(self, url, **kwargs):
                return FakeResponse()

        user.session = FakeSession()
        user._persist_logged_in_session = AsyncMock()

        with patch("utils.tms.save_tokens") as save_tokens_mock:
            refreshed = await user.refresh_auth_token()

        self.assertTrue(refreshed)
        self.assertEqual(user.headers["x-xsrf-token"], "new-token")
        self.assertEqual(user.tokens["XSRF-TOKEN"], "new-token")
        save_tokens_mock.assert_called_once()
