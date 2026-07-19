"""Standalone low-priority backtest queue worker."""

import os

from utils.backtesting.v2_jobs import worker_loop


if __name__ == "__main__":
    try:
        os.nice(max(0, int(os.getenv("BACKTEST_WORKER_NICE", "5"))))
    except (AttributeError, OSError, ValueError):
        pass
    refresh_only = os.getenv("BACKTEST_REFRESH_ONLY", "false").strip().lower() in {
        "1", "true", "yes", "on",
    }
    worker_loop(refresh_only=refresh_only)
