from utils.backtesting.batch import background_worker_limit


def test_background_scans_default_to_one_worker(monkeypatch):
    monkeypatch.delenv("BACKTEST_MAX_WORKERS", raising=False)
    monkeypatch.delenv("BACKTEST_RESERVED_CPUS", raising=False)
    assert background_worker_limit(8) == 1


def test_background_worker_limit_honors_server_cap(monkeypatch):
    monkeypatch.setenv("BACKTEST_MAX_WORKERS", "2")
    monkeypatch.setenv("BACKTEST_RESERVED_CPUS", "1")
    assert 1 <= background_worker_limit(12) <= 2
