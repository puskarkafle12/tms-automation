from utils.live_quote_socket import _looks_like_auth_error


def test_looks_like_auth_error_detects_auth_failures() -> None:
    assert _looks_like_auth_error("401 Unauthorized")
    assert _looks_like_auth_error("Authentication expired. Please log in again.")
    assert _looks_like_auth_error("Token expired")


def test_looks_like_auth_error_ignores_non_auth_errors() -> None:
    assert not _looks_like_auth_error("Timeout on reading data from socket")
    assert not _looks_like_auth_error("Connection reset by peer")
