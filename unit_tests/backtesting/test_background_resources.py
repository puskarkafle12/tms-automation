from utils.backtesting.batch import (
    background_cache_worker_limit,
    background_chunk_delay_seconds,
    background_refresh_worker_limit,
    background_turn_size,
    background_worker_limit,
)


def test_background_scans_default_to_one_worker(monkeypatch):
    monkeypatch.delenv("BACKTEST_MAX_WORKERS", raising=False)
    monkeypatch.delenv("BACKTEST_OFF_HOURS_MAX_WORKERS", raising=False)
    monkeypatch.setenv("BACKTEST_RESERVED_CPUS", "1")
    monkeypatch.setattr("utils.backtesting.batch.os.cpu_count", lambda: 4)
    assert background_worker_limit(8, market_constrained=False) == 1


def test_background_scans_keep_one_worker_on_small_hosts(monkeypatch):
    monkeypatch.delenv("BACKTEST_MAX_WORKERS", raising=False)
    monkeypatch.delenv("BACKTEST_OFF_HOURS_MAX_WORKERS", raising=False)
    monkeypatch.setenv("BACKTEST_RESERVED_CPUS", "1")
    monkeypatch.setattr("utils.backtesting.batch.os.cpu_count", lambda: 2)
    assert background_worker_limit(8, market_constrained=False) == 1


def test_background_worker_limit_honors_server_cap(monkeypatch):
    monkeypatch.setenv("BACKTEST_MAX_WORKERS", "2")
    monkeypatch.setenv("BACKTEST_RESERVED_CPUS", "1")
    monkeypatch.setattr("utils.backtesting.batch.os.cpu_count", lambda: 8)
    assert background_worker_limit(12, market_constrained=False) == 2


def test_background_scans_use_two_workers_when_capacity_is_available(monkeypatch):
    monkeypatch.setenv("BACKTEST_MAX_WORKERS", "2")
    monkeypatch.setenv("BACKTEST_RESERVED_CPUS", "1")
    monkeypatch.setattr("utils.backtesting.batch.os.cpu_count", lambda: 4)
    assert background_worker_limit(8, market_constrained=False) == 2


def test_live_market_keeps_research_to_one_worker(monkeypatch):
    monkeypatch.delenv("BACKTEST_MAX_WORKERS", raising=False)
    monkeypatch.delenv("BACKTEST_MARKET_MAX_WORKERS", raising=False)
    monkeypatch.setenv("BACKTEST_RESERVED_CPUS", "1")
    monkeypatch.setattr("utils.backtesting.batch.os.cpu_count", lambda: 8)
    assert background_worker_limit(None, market_constrained=True) == 1
    assert background_turn_size(1, market_constrained=True) == 1


def test_off_hours_default_keeps_round_robin_to_one_stock(monkeypatch):
    monkeypatch.delenv("BACKTEST_MAX_WORKERS", raising=False)
    monkeypatch.delenv("BACKTEST_OFF_HOURS_MAX_WORKERS", raising=False)
    monkeypatch.delenv("BACKTEST_ROUND_ROBIN_STOCKS_PER_TURN", raising=False)
    monkeypatch.delenv("BACKTEST_OFF_HOURS_STOCKS_PER_TURN", raising=False)
    monkeypatch.setenv("BACKTEST_RESERVED_CPUS", "1")
    monkeypatch.setattr("utils.backtesting.batch.os.cpu_count", lambda: 8)
    workers = background_worker_limit(None, market_constrained=False)
    assert workers == 1
    assert background_turn_size(workers, market_constrained=False) == 1


def test_off_hours_worker_and_turn_caps_are_configurable(monkeypatch):
    monkeypatch.delenv("BACKTEST_MAX_WORKERS", raising=False)
    monkeypatch.setenv("BACKTEST_OFF_HOURS_MAX_WORKERS", "4")
    monkeypatch.setenv("BACKTEST_OFF_HOURS_STOCKS_PER_TURN", "6")
    monkeypatch.setenv("BACKTEST_RESERVED_CPUS", "1")
    monkeypatch.setattr("utils.backtesting.batch.os.cpu_count", lambda: 12)
    workers = background_worker_limit(None, market_constrained=False)
    assert workers == 4
    assert background_turn_size(workers, market_constrained=False) == 6


def test_off_hours_default_stays_conservative_on_large_hosts(monkeypatch):
    monkeypatch.delenv("BACKTEST_MAX_WORKERS", raising=False)
    monkeypatch.delenv("BACKTEST_OFF_HOURS_MAX_WORKERS", raising=False)
    monkeypatch.setenv("BACKTEST_RESERVED_CPUS", "1")
    monkeypatch.setattr("utils.backtesting.batch.os.cpu_count", lambda: 10)
    assert background_worker_limit(None, market_constrained=False) == 1


def test_background_helper_caps_are_conservative_by_default(monkeypatch):
    monkeypatch.delenv("BACKTEST_CACHE_MAX_WORKERS", raising=False)
    monkeypatch.delenv("BACKTEST_REFRESH_FETCH_WORKERS", raising=False)
    monkeypatch.delenv("BACKTEST_CHUNK_DELAY_SECONDS", raising=False)
    assert background_cache_worker_limit(8) == 1
    assert background_refresh_worker_limit(8) == 2
    assert background_chunk_delay_seconds() == 1.0


def test_background_helper_caps_are_configurable(monkeypatch):
    monkeypatch.setenv("BACKTEST_CACHE_MAX_WORKERS", "3")
    monkeypatch.setenv("BACKTEST_REFRESH_FETCH_WORKERS", "4")
    monkeypatch.setenv("BACKTEST_CHUNK_DELAY_SECONDS", "0.25")
    assert background_cache_worker_limit(8) == 3
    assert background_refresh_worker_limit(8) == 4
    assert background_chunk_delay_seconds() == 0.25
