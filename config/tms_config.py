# config.py

import asyncio
from datetime import datetime, time
from typing import Dict, Optional


start_time = time(hour=9, minute=0)
end_time = time(hour=15, minute=0)
is_running = False
check_orders_task: Optional[asyncio.Task] = None
monitor_interval = 5
monitor_tick_seconds = 3
nepse_alpha_interval_seconds = 1800
enable_scan_staggering = True
max_price_fetch_concurrency = 5

scheduled_started_at: Optional[datetime] = None
scheduled_phase: str = "stopped"
scheduled_status_message: str = ""

grabber_started_at: Dict[str, datetime] = {}
grabber_phase: Dict[str, str] = {}
grabber_status_message: Dict[str, str] = {}

# (client_id, script_name) pairs whose in-memory monitor scan counts should reset.
scan_count_reset_keys: set = set()
