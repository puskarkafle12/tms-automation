import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


class _Query:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _Db:
    def __init__(self, sessions, users):
        self.sessions = sessions
        self.users = users
        self.commits = 0

    def query(self, model):
        from models.logged_in_user import LoggedInUsers
        from models.user import User

        if model is LoggedInUsers:
            return _Query(self.sessions)
        if model is User:
            return _Query(self.users)
        raise AssertionError(f"Unexpected model: {model!r}")

    def commit(self):
        self.commits += 1


class LoggedInClientsReconcileTest(unittest.IsolatedAsyncioTestCase):
    async def test_reconcile_queues_auto_login_when_cached_session_expires(self):
        from main import _reconcile_logged_in_sessions

        session = SimpleNamespace(
            client_id="client1",
            status="logged_in",
            tokens={"XSRF-TOKEN": "stale"},
            broker_no="35",
            message="logged in",
        )
        user = SimpleNamespace(client_id="client1", broker_no="35", auto_login=True)
        db = _Db([session], [user])

        with patch("main.get_cached_tms_user", new_callable=AsyncMock, side_effect=Exception("Token expired")), patch(
            "main._queue_tms_account_login", return_value=True
        ) as queue_login:
            await _reconcile_logged_in_sessions(db)

        queue_login.assert_called_once_with(user, db, automatic=True, force=True)
        self.assertEqual(session.status, "logged_in")
        self.assertEqual(session.tokens, {"XSRF-TOKEN": "stale"})
        self.assertGreaterEqual(db.commits, 1)

    async def test_reconcile_queues_ui_login_even_when_old_toggle_is_disabled(self):
        from main import _reconcile_logged_in_sessions

        session = SimpleNamespace(
            client_id="client1",
            status="logged_in",
            tokens={"XSRF-TOKEN": "stale"},
            broker_no="35",
            message="logged in",
        )
        user = SimpleNamespace(client_id="client1", broker_no="35", auto_login=False)
        db = _Db([session], [user])

        with patch("main.get_cached_tms_user", new_callable=AsyncMock, side_effect=Exception("Token expired")), patch(
            "main._queue_tms_account_login", return_value=True
        ) as queue_login:
            await _reconcile_logged_in_sessions(db)

        queue_login.assert_called_once_with(user, db, automatic=True, force=True)
        self.assertEqual(session.status, "logged_in")
        self.assertEqual(session.tokens, {"XSRF-TOKEN": "stale"})

    async def test_reconcile_keeps_valid_sessions_logged_in(self):
        from main import _reconcile_logged_in_sessions

        session = SimpleNamespace(
            client_id="client1",
            status="logged_in",
            tokens={"XSRF-TOKEN": "good"},
            broker_no="35",
            message="logged in",
        )
        user = SimpleNamespace(client_id="client1", broker_no="35", auto_login=True)
        db = _Db([session], [user])

        with patch("main.get_cached_tms_user", new_callable=AsyncMock, return_value="tms-user"):
            await _reconcile_logged_in_sessions(db)

        self.assertEqual(session.status, "logged_in")
        self.assertEqual(session.tokens, {"XSRF-TOKEN": "good"})
        self.assertGreaterEqual(db.commits, 1)
