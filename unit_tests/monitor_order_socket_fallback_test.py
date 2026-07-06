from utils.monitor_order import (
    _monitor_socket_failure_state,
    _monitor_socket_polling_only,
    _record_monitor_socket_failure,
    _record_monitor_socket_success,
)


def test_monitor_socket_failure_enters_polling_cooldown() -> None:
    key = ("client-1", "NABIL")
    _monitor_socket_failure_state.clear()

    assert not _monitor_socket_polling_only(key)

    _record_monitor_socket_failure(key)
    _record_monitor_socket_failure(key)
    assert not _monitor_socket_polling_only(key)

    _record_monitor_socket_failure(key)
    assert _monitor_socket_polling_only(key)

    _monitor_socket_failure_state.clear()


def test_monitor_socket_success_clears_cooldown() -> None:
    key = ("client-2", "NICA")
    _monitor_socket_failure_state.clear()

    _record_monitor_socket_failure(key)
    _record_monitor_socket_failure(key)
    _record_monitor_socket_failure(key)
    assert _monitor_socket_polling_only(key)

    _record_monitor_socket_success(key)
    assert not _monitor_socket_polling_only(key)

    _monitor_socket_failure_state.clear()
