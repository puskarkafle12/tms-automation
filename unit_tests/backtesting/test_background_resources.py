from utils.backtesting.batch import background_worker_limit


def test_background_scans_adapt_to_spare_cores(monkeypatch):
    monkeypatch.delenv("BACKTEST_MAX_WORKERS", raising=False)
    monkeypatch.setenv("BACKTEST_RESERVED_CPUS", "1")
    monkeypatch.setattr("utils.backtesting.batch.os.cpu_count", lambda: 4)
    # 4 CPUs - 1 reserved = 3 spare, capped at 3.
    assert background_worker_limit(8) == 3


def test_background_scans_keep_one_worker_on_small_hosts(monkeypatch):
    monkeypatch.delenv("BACKTEST_MAX_WORKERS", raising=False)
    monkeypatch.setenv("BACKTEST_RESERVED_CPUS", "1")
    monkeypatch.setattr("utils.backtesting.batch.os.cpu_count", lambda: 2)
    assert background_worker_limit(8) == 1


def test_background_worker_limit_honors_server_cap(monkeypatch):
    monkeypatch.setenv("BACKTEST_MAX_WORKERS", "2")
    monkeypatch.setenv("BACKTEST_RESERVED_CPUS", "1")
    monkeypatch.setattr("utils.backtesting.batch.os.cpu_count", lambda: 8)
    assert background_worker_limit(12) == 2


def test_background_scans_use_two_workers_when_capacity_is_available(monkeypatch):
    monkeypatch.setenv("BACKTEST_MAX_WORKERS", "2")
    monkeypatch.setenv("BACKTEST_RESERVED_CPUS", "1")
    monkeypatch.setattr("utils.backtesting.batch.os.cpu_count", lambda: 4)
    assert background_worker_limit(8) == 2
