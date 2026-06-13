# config.py

from datetime import datetime, time
from typing import Dict, Optional


start_time = time(hour=9, minute=0)
end_time = time(hour=15, minute=0)
is_running = False
monitor_interval = 5

scheduled_started_at: Optional[datetime] = None
scheduled_phase: str = "stopped"
scheduled_status_message: str = ""

grabber_started_at: Dict[str, datetime] = {}
grabber_phase: Dict[str, str] = {}
grabber_status_message: Dict[str, str] = {}
