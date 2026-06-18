from __future__ import annotations

import os
from pathlib import Path


def _load_dotenv() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

# test (default): local only — no ngrok tunnel
# prod: enable ngrok public URL in Docker
ENVIRONMENT = (os.getenv("ENVIRONMENT") or "test").strip().lower()


def is_production() -> bool:
    return ENVIRONMENT in {"production", "prod"}


def is_testing() -> bool:
    return not is_production()


def public_app_url(host: str = "localhost", port: int = 3000) -> str:
    if is_production() and os.getenv("NGROK_DOMAIN"):
        domain = os.getenv("NGROK_DOMAIN", "").strip()
        domain = domain.removeprefix("https://").removeprefix("http://")
        if domain:
            return f"https://{domain}"
    return f"http://{host}:{port}"
