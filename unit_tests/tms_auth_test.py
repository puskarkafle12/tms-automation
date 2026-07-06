import importlib.util
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


@unittest.skipIf(importlib.util.find_spec("aiohttp") is None, "aiohttp is not installed")
class TestTmsAuthFlow(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from utils.tms import TmsUser

        self.TmsUser = TmsUser
        self.TmsUser._full_login_lock = None

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

    async def test_try_cached_login_can_skip_full_captcha_login(self):
        from exceptions.login_exceptions import LoginFailedException

        user = self.TmsUser(broker_no="35", username="client1", password="enc-pass")
        user.rotate_password_if_expired = AsyncMock(return_value={"rotated": False})
        user._load_session_from_store = AsyncMock(return_value=True)
        user._validate_session = AsyncMock(side_effect=Exception("expired"))
        user.refresh_auth_token = AsyncMock(return_value=False)
        user._full_login_and_persist = AsyncMock(return_value={"status": "success", "message": "login"})

        with self.assertRaises(LoginFailedException):
            await user.try_cached_login(allow_full_login=False)

        user._full_login_and_persist.assert_not_awaited()

    async def test_refresh_authentication_falls_back_to_full_login(self):
        user = self.TmsUser(broker_no="35", username="client1", password="enc-pass")
        user._load_password_from_db = AsyncMock()
        user._load_session_from_store = AsyncMock(return_value=True)
        user.refresh_auth_token = AsyncMock(return_value=False)
        user._full_login_and_persist = AsyncMock(return_value={"status": "success", "message": "login"})

        await user._refresh_authentication()

        user._full_login_and_persist.assert_awaited_once()

    @patch("utils.tms.logout_user")
    async def test_refresh_authentication_can_skip_full_captcha_login(self, logout_user_mock):
        from exceptions.login_exceptions import LoginFailedException

        user = self.TmsUser(broker_no="35", username="client1", password="enc-pass")
        user._allow_full_login_on_refresh = False
        user._load_password_from_db = AsyncMock()
        user._load_session_from_store = AsyncMock(return_value=True)
        user.refresh_auth_token = AsyncMock(return_value=False)
        user._full_login_and_persist = AsyncMock(return_value={"status": "success", "message": "login"})

        with self.assertRaises(LoginFailedException):
            await user._refresh_authentication()

        user._full_login_and_persist.assert_not_awaited()
        logout_user_mock.assert_called_once()

    async def test_full_login_is_serialized(self):
        user1 = self.TmsUser(broker_no="35", username="client1", password="enc-pass")
        user2 = self.TmsUser(broker_no="35", username="client2", password="enc-pass")
        active_logins = 0
        max_active_logins = 0
        sample_session = self._sample_session()

        async def fake_login(self):
            nonlocal active_logins, max_active_logins
            active_logins += 1
            max_active_logins = max(max_active_logins, active_logins)
            await asyncio.sleep(0.01)
            active_logins -= 1
            return dict(sample_session)

        for user in (user1, user2):
            user._load_password_from_db = AsyncMock()
            user.login = fake_login.__get__(user, self.TmsUser)
            user.rotate_password_if_expired = AsyncMock(return_value={"rotated": False})
            user._validate_session = AsyncMock()
            user._persist_logged_in_session = AsyncMock()

        await asyncio.gather(user1._full_login_and_persist(), user2._full_login_and_persist())

        self.assertEqual(max_active_logins, 1)

    async def test_tms_loader_allows_full_login_for_background_recovery(self):
        from utils import tms_user_loader

        class FakeQuery:
            def filter(self, *args, **kwargs):
                return self

            def all(self):
                row = MagicMock()
                row.client_id = "client1"
                return [row]

        class FakeDb:
            def query(self, model):
                return FakeQuery()

            def close(self):
                pass

        with patch("utils.tms_user_loader.get_db_session", return_value=FakeDb()), patch(
            "utils.tms_user_loader.get_tms_user_for_client",
            new_callable=AsyncMock,
        ) as get_user:
            get_user.return_value = "tms-user"

            result = await tms_user_loader.load_tms_users_instances(["client1"], {})

        self.assertEqual(result["client1"], "tms-user")
        self.assertTrue(get_user.await_args.kwargs["allow_full_login"])

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
