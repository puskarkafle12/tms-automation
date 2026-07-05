from __future__ import annotations

import asyncio
import inspect
import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import websockets


SOCKET_QUOTE_FRESH_SECONDS = 8.0
SOCKET_QUOTE_WAIT_SECONDS = 2.0


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cookie_header(tokens: Optional[dict]) -> str:
    return "; ".join(f"{key}={value}" for key, value in (tokens or {}).items() if value)


def _connect_kwargs(headers: dict) -> dict:
    signature = inspect.signature(websockets.connect)
    if "additional_headers" in signature.parameters:
        return {"additional_headers": headers}
    return {"extra_headers": headers}


def _normalize_quote(raw_quote: dict, *, symbol: str, security_id: str) -> dict:
    quote = dict(raw_quote or {})
    security = dict(quote.get("security") or {})
    security.setdefault("id", int(security_id) if str(security_id).isdigit() else security_id)
    security.setdefault("symbol", symbol)
    quote["security"] = security

    if "high" not in quote and quote.get("dayHigh") is not None:
        quote["high"] = quote.get("dayHigh")
    if "low" not in quote and quote.get("dayLow") is not None:
        quote["low"] = quote.get("dayLow")
    if "open" not in quote and quote.get("openPrice") is not None:
        quote["open"] = quote.get("openPrice")
    if "previousClose" not in quote and quote.get("closePrice") is not None:
        quote["previousClose"] = quote.get("closePrice")
    return quote


def _quote_signature(quote: Optional[dict]) -> str:
    if not quote:
        return ""
    security = quote.get("security") or {}
    top_buy = quote.get("topBuy") or []
    top_sell = quote.get("topSell") or []
    payload = {
        "symbol": security.get("symbol") or quote.get("symbol"),
        "ltp": quote.get("ltp"),
        "volume": quote.get("volume"),
        "lastTradedTime": quote.get("lastTradedTime"),
        "change": quote.get("change"),
        "changePercentage": quote.get("changePercentage"),
        "topBuy": [
            (row.get("price"), row.get("quantity"), row.get("totalOrders"))
            for row in top_buy[:5]
        ],
        "topSell": [
            (row.get("price"), row.get("quantity"), row.get("totalOrders"))
            for row in top_sell[:5]
        ],
    }
    return json.dumps(payload, sort_keys=True, default=str)


class LiveQuoteSocketManager:
    """Shared TMS stockquote sockets keyed by symbol to avoid duplicate streams."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._streams: Dict[str, dict] = {}

    @staticmethod
    def _key(symbol: str) -> str:
        return str(symbol or "").strip().upper()

    def get_snapshot(self, symbol: str) -> Optional[dict]:
        stream = self._streams.get(self._key(symbol))
        if not stream:
            return None
        quote = stream.get("quote")
        return {
            "symbol": stream.get("symbol"),
            "security_id": stream.get("security_id"),
            "status": stream.get("status") or "idle",
            "source": "socket",
            "message_count": int(stream.get("message_count") or 0),
            "error_count": int(stream.get("error_count") or 0),
            "last_error": stream.get("last_error"),
            "started_at": stream.get("started_at"),
            "last_received_at": stream.get("last_received_at"),
            "last_requested_at": stream.get("last_requested_at"),
            "quote_signature": stream.get("quote_signature"),
            "quote": quote,
            "fresh": self.is_fresh(symbol),
        }

    def is_fresh(self, symbol: str, *, max_age_seconds: float = SOCKET_QUOTE_FRESH_SECONDS) -> bool:
        stream = self._streams.get(self._key(symbol))
        if not stream or not stream.get("quote"):
            return False
        last_received_monotonic = float(stream.get("last_received_monotonic") or 0)
        return last_received_monotonic > 0 and time.monotonic() - last_received_monotonic <= max_age_seconds

    async def ensure_stream(
        self,
        tms_user: Any,
        symbol: str,
        security_id: str,
        *,
        force_restart: bool = False,
    ) -> dict:
        key = self._key(symbol)
        old_task: Optional[asyncio.Task] = None
        async with self._lock:
            stream = self._streams.get(key)
            if stream:
                stream["last_requested_at"] = _utc_now_iso()
                stream.setdefault("quote_event", asyncio.Event())
                task = stream.get("task")
                if task is not None and not task.done():
                    if not force_restart:
                        return self.get_snapshot(key) or {}
                    old_task = task
                    self._streams.pop(key, None)
                elif not force_restart:
                    return self.get_snapshot(key) or {}

            stream = {
                "symbol": key,
                "security_id": str(security_id),
                "status": "connecting",
                "message_count": 0,
                "quote_event": asyncio.Event(),
                "error_count": int((stream or {}).get("error_count") or 0),
                "last_error": None,
                "started_at": _utc_now_iso(),
                "last_requested_at": _utc_now_iso(),
                "last_received_at": None,
                "last_received_monotonic": 0.0,
                "quote_signature": "",
                "quote": (stream or {}).get("quote") if stream else None,
            }
            task = asyncio.create_task(self._run_stream(tms_user, key, str(security_id)))
            stream["task"] = task
            self._streams[key] = stream
        if old_task is not None:
            old_task.cancel()
            try:
                await old_task
            except asyncio.CancelledError:
                pass
        return self.get_snapshot(key) or {}

    async def wait_for_quote(self, symbol: str, *, timeout: float = SOCKET_QUOTE_WAIT_SECONDS) -> Optional[dict]:
        deadline = time.monotonic() + max(0.0, timeout)
        while time.monotonic() < deadline:
            snapshot = self.get_snapshot(symbol)
            if snapshot and snapshot.get("quote"):
                return snapshot
            await asyncio.sleep(0.05)
        return self.get_snapshot(symbol)

    async def wait_for_next_quote(
        self,
        symbol: str,
        *,
        after_message_count: int = 0,
        timeout: float = SOCKET_QUOTE_WAIT_SECONDS,
    ) -> Optional[dict]:
        key = self._key(symbol)
        deadline = time.monotonic() + max(0.0, timeout)
        while time.monotonic() < deadline:
            stream = self._streams.get(key)
            if not stream:
                return None
            if int(stream.get("message_count") or 0) > int(after_message_count or 0) and stream.get("quote"):
                return self.get_snapshot(key)
            event = stream.get("quote_event")
            remaining = max(0.0, deadline - time.monotonic())
            if not event or remaining <= 0:
                break
            try:
                await asyncio.wait_for(event.wait(), timeout=min(remaining, 0.5))
            except asyncio.TimeoutError:
                pass
            if event:
                event.clear()
        return None

    async def wait_for_next_distinct_quote(
        self,
        symbol: str,
        *,
        after_signature: str = "",
        timeout: float = SOCKET_QUOTE_WAIT_SECONDS,
    ) -> Optional[dict]:
        key = self._key(symbol)
        deadline = time.monotonic() + max(0.0, timeout)
        while time.monotonic() < deadline:
            stream = self._streams.get(key)
            if not stream:
                return None
            current_signature = str(stream.get("quote_signature") or "")
            if current_signature and current_signature != str(after_signature or "") and stream.get("quote"):
                return self.get_snapshot(key)
            event = stream.get("quote_event")
            remaining = max(0.0, deadline - time.monotonic())
            if not event or remaining <= 0:
                break
            try:
                await asyncio.wait_for(event.wait(), timeout=min(remaining, 0.5))
            except asyncio.TimeoutError:
                pass
            if event:
                event.clear()
        return None

    async def close_symbol(self, symbol: str) -> None:
        key = self._key(symbol)
        async with self._lock:
            stream = self._streams.pop(key, None)
        if stream and stream.get("task"):
            stream["task"].cancel()
            try:
                await stream["task"]
            except asyncio.CancelledError:
                pass

    async def close_all(self) -> None:
        async with self._lock:
            streams = list(self._streams.values())
            self._streams.clear()
        for stream in streams:
            task = stream.get("task")
            if task:
                task.cancel()
        for stream in streams:
            task = stream.get("task")
            if task:
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    async def _run_stream(self, tms_user: Any, symbol: str, security_id: str) -> None:
        key = self._key(symbol)
        stream = self._streams[key]
        try:
            login_response = tms_user.login_response or {}
            request_owner = str(login_response.get("request_owner") or "").strip()
            client_dealer_id = str(login_response.get("client_dealer_id") or "").strip()
            broker_no = str(tms_user.broker_no or "").strip()
            if not request_owner or not client_dealer_id or not broker_no:
                raise RuntimeError("missing TMS websocket session identifiers")

            socket_url = (
                f"wss://tms{broker_no}.nepsetms.com.np//tmsapi/socket"
                f"?memberId={request_owner}&clientId={client_dealer_id}&dealerId=&userId={request_owner}"
            )
            headers = {
                "Pragma": "no-cache",
                "Origin": f"https://tms{broker_no}.nepsetms.com.np",
                "Accept-Language": "en-US,en;q=0.9",
                "Cookie": _cookie_header(tms_user.tokens),
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
                "Cache-Control": "no-cache",
                "Sec-GPC": "1",
            }

            async with websockets.connect(socket_url, **_connect_kwargs(headers)) as websocket:
                stream["status"] = "connected"
                await websocket.send(json.dumps({
                    "header": {"channel": "@control", "transaction": "start_stockquote"},
                    "payload": {"argument": str(security_id)},
                }))
                stream["status"] = "live"

                while True:
                    message = await websocket.recv()
                    frames = json.loads(message)
                    for frame in frames if isinstance(frames, list) else [frames]:
                        header = frame.get("header") or {}
                        if header.get("transaction") != "stockquote":
                            continue
                        data = (frame.get("payload") or {}).get("data") or []
                        if not data:
                            continue
                        quote = _normalize_quote(data[0], symbol=symbol, security_id=security_id)
                        signature = _quote_signature(quote)
                        stream["quote"] = quote
                        stream["quote_signature"] = signature
                        stream["message_count"] = int(stream.get("message_count") or 0) + 1
                        stream["last_received_at"] = _utc_now_iso()
                        stream["last_received_monotonic"] = time.monotonic()
                        stream["status"] = "live"
                        event = stream.get("quote_event")
                        if event:
                            event.set()
        except asyncio.CancelledError:
            stream["status"] = "closed"
            raise
        except Exception as exc:
            stream["status"] = "failed"
            stream["last_error"] = str(exc)
            stream["error_count"] = int(stream.get("error_count") or 0) + 1


live_quote_manager = LiveQuoteSocketManager()
