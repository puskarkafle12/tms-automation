"""Standalone low-priority backtest queue worker."""

import os

from utils.backtesting.v2_jobs import worker_loop


if __name__ == "__main__":
    try:
        os.nice(max(0, int(os.getenv("BACKTEST_WORKER_NICE", "10"))))
    except (AttributeError, OSError, ValueError):
        pass
    worker_loop()
