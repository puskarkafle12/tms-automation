from __future__ import annotations

from models.frontend_user import FrontendUser
from utils.auth import (
    DEFAULT_USER_PERMISSIONS,
    FEATURES,
    can_manage,
    hash_password,
    normalized_permissions,
    resolved_permissions,
    verify_password,
)


def user(user_id: int, role: str, *, manager_id: int | None = None, permissions=None) -> FrontendUser:
    return FrontendUser(
        id=user_id,
        username=f"user{user_id}",
        password="unused",
        role=role,
        managed_by_user_id=manager_id,
        permissions=list(permissions or []),
        is_active=True,
    )


def test_password_hash_is_salted_and_verifiable() -> None:
    first = hash_password("a secure password")
    second = hash_password("a secure password")
    assert first != second
    assert verify_password("a secure password", first)
    assert not verify_password("wrong password", first)


def test_new_users_have_every_trading_feature_except_grabber_and_admin() -> None:
    assert "stock_grabber" not in DEFAULT_USER_PERMISSIONS
    assert "admin_users" not in DEFAULT_USER_PERMISSIONS
    assert set(DEFAULT_USER_PERMISSIONS) == set(FEATURES) - {"stock_grabber", "admin_users"}


def test_root_and_delegated_superuser_permissions_are_distinct() -> None:
    root = user(1, "superuser")
    delegated = user(2, "superuser", manager_id=3)
    assert set(resolved_permissions(root)) == set(FEATURES)
    assert set(resolved_permissions(delegated)) == set(FEATURES) - {"admin_users"}


def test_admin_can_manage_only_assigned_user_or_delegated_superuser() -> None:
    admin = user(10, "admin")
    assert can_manage(admin, user(11, "user", manager_id=10))
    assert can_manage(admin, user(12, "superuser", manager_id=10))
    assert not can_manage(admin, user(13, "user", manager_id=99))
    assert not can_manage(admin, user(14, "admin", manager_id=10))


def test_permission_normalization_rejects_unknown_features() -> None:
    assert normalized_permissions(["portfolio", "made_up"], "user") == ["portfolio"]
    assert set(normalized_permissions([], "superuser")) == set(FEATURES)
