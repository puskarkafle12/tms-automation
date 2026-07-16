import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from models.logged_in_user import LoggedInUsers
from models.user import User
from utils import tms_user_loader as loader


class _Query:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *args):
        return self

    def all(self):
        return list(self.rows)


class _Db:
    def __init__(self, sessions, users):
        self.sessions = sessions
        self.users = users
        self.closed = False

    def query(self, model):
        if model is LoggedInUsers:
            return _Query(self.sessions)
        if model is User:
            return _Query(self.users)
        raise AssertionError(f"Unexpected model {model!r}")

    def close(self):
        self.closed = True


class TmsUserLoaderAutoLoginTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        loader._auto_login_failures.clear()

    async def test_logged_out_auto_login_user_is_fully_recovered(self):
        db = _Db(
            [SimpleNamespace(client_id="client1", status="logged_out")],
            [SimpleNamespace(client_id="client1", auto_login=True)],
        )
        recovered = object()
        resolver = AsyncMock(return_value=recovered)

        with patch.object(loader, "get_db_session", return_value=db), patch.object(
            loader, "get_tms_user_for_client", resolver
        ):
            instances = await loader.load_tms_users_instances({"client1"}, {})

        self.assertIs(instances["client1"], recovered)
        resolver.assert_awaited_once_with("client1", db, allow_full_login=True)
        self.assertTrue(db.closed)

    async def test_active_order_recovers_even_when_old_auto_login_toggle_is_off(self):
        db = _Db(
            [SimpleNamespace(client_id="client1", status="logged_out")],
            [SimpleNamespace(client_id="client1", auto_login=False)],
        )
        recovered = object()
        resolver = AsyncMock(return_value=recovered)

        with patch.object(loader, "get_db_session", return_value=db), patch.object(
            loader, "get_tms_user_for_client", resolver
        ):
            instances = await loader.load_tms_users_instances({"client1"}, {})

        self.assertIs(instances["client1"], recovered)
        resolver.assert_awaited_once_with("client1", db, allow_full_login=True)

    def test_failed_automatic_login_is_throttled(self):
        self.assertTrue(loader.auto_login_retry_allowed("client1"))
        loader.record_auto_login_failure("client1")
        self.assertFalse(loader.auto_login_retry_allowed("client1"))
        loader.record_auto_login_success("client1")
        self.assertTrue(loader.auto_login_retry_allowed("client1"))


if __name__ == "__main__":
    unittest.main()
