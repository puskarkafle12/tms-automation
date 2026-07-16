from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from exceptions.login_exceptions import LoginFailedException
from main import _get_schedule_validation_tms_user


class ScheduledOrderValidationLoginTest(unittest.IsolatedAsyncioTestCase):
    async def test_allows_full_login_when_cached_session_expired(self):
        user = SimpleNamespace(client_id="client1")
        tms_user = object()

        with patch("main.get_cached_tms_user", new_callable=AsyncMock) as get_user:
            get_user.return_value = tms_user
            result = await _get_schedule_validation_tms_user(user)

        self.assertIs(result, tms_user)
        get_user.assert_awaited_once_with(user, allow_full_login=True)

    async def test_returns_clean_unauthorized_error_when_full_login_fails(self):
        user = SimpleNamespace(client_id="client1")

        with patch("main.get_cached_tms_user", new_callable=AsyncMock) as get_user:
            get_user.side_effect = LoginFailedException("captcha login failed")
            with self.assertRaises(HTTPException) as raised:
                await _get_schedule_validation_tms_user(user)

        self.assertEqual(raised.exception.status_code, 401)
        self.assertIn("captcha login failed", str(raised.exception.detail))


if __name__ == "__main__":
    unittest.main()
