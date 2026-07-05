"""Log in a saved TMS user and test live TMS websocket price streams."""
from __future__ import annotations

import asyncio
import argparse
import inspect
import json
import sys
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utils.tms import TmsUser

TEST_USER_FILE = ROOT / "utils" / "test_user_login_details.json"
DEFAULT_TRANSACTIONS = ("start_stockquote", "start_index")


def load_test_user() -> dict:
    payload = json.loads(TEST_USER_FILE.read_text(encoding="utf-8"))
    users = payload.get("users") or []
    if not users:
        raise RuntimeError(f"No users found in {TEST_USER_FILE}")
    return users[0]


def build_cookie_header(tokens: dict) -> str:
    return "; ".join(f"{key}={value}" for key, value in tokens.items() if value)


def connect_kwargs(headers: dict) -> dict:
    signature = inspect.signature(websockets.connect)
    if "additional_headers" in signature.parameters:
        return {"additional_headers": headers}
    return {"extra_headers": headers}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Log in and test the TMS websocket feed.")
    parser.add_argument(
        "--symbol",
        action="append",
        help="Stock symbol to subscribe with start_stockquote. May be passed multiple times.",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=0,
        help="Subscribe to the first N securities from TMS if no --symbol is provided.",
    )
    parser.add_argument(
        "--fanout",
        action="store_true",
        help="Open one websocket per symbol instead of multiplexing symbols on a single socket.",
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=5,
        help="Maximum websocket sessions to open at once in fanout mode.",
    )
    parser.add_argument(
        "--transaction",
        action="append",
        choices=[
            "start_stockquote",
            "start_ticker",
            "start_marketwatch",
            "start_index",
            "start_clientPortfolio",
            "start_top25securities",
        ],
        help="Control transaction to start. May be passed multiple times.",
    )
    parser.add_argument("--frames", type=int, default=12, help="Number of websocket frames to print.")
    parser.add_argument("--timeout", type=int, default=20, help="Seconds to wait for each frame.")
    return parser.parse_args()


async def run_symbol_socket(
    socket_url: str,
    headers: dict,
    symbol: str,
    security_id: str,
    transactions: list[str],
    frames: int,
    timeout: int,
) -> dict:
    result: dict = {"symbol": symbol, "security_id": security_id, "messages": [], "error": None}
    try:
        async with websockets.connect(socket_url, **connect_kwargs(headers)) as websocket:
            for transaction in transactions:
                argument = security_id if transaction == "start_stockquote" else "undefined"
                await websocket.send(json.dumps({
                    "header": {"channel": "@control", "transaction": transaction},
                    "payload": {"argument": argument},
                }))
            for index in range(frames):
                message = await asyncio.wait_for(websocket.recv(), timeout=timeout)
                result["messages"].append(message)
                print(f"[{symbol}] MSG {index + 1}: {message}")
    except Exception as exc:
        result["error"] = str(exc)
        print(f"[{symbol}] ERROR: {exc}")
    return result


async def main() -> None:
    args = parse_args()
    transactions = args.transaction or list(DEFAULT_TRANSACTIONS)
    user = load_test_user()
    client_id = str(user["client_id"]).strip()
    broker_no = str(user["broker_no"]).strip()
    password = TmsUser.to_tms_password_payload(str(user["password"]).strip())

    tms_user = TmsUser(
        broker_no=broker_no,
        username=client_id,
        password=password,
        request_per_sec=5,
    )
    login_status = await tms_user.try_cached_login()
    login_response = tms_user.login_response or {}
    tokens = dict(tms_user.tokens or {})

    request_owner = str(login_response.get("request_owner") or "").strip()
    client_dealer_id = str(login_response.get("client_dealer_id") or "").strip()
    if not request_owner or not client_dealer_id:
        raise RuntimeError("Login succeeded, but request_owner/client_dealer_id are missing")

    requested_symbols = [str(item).strip().upper() for item in (args.symbol or []) if str(item).strip()]
    if not requested_symbols and args.count > 0:
        securities = await tms_user.get_securities()
        requested_symbols = [
            str(stock.get("symbol") or "").strip().upper()
            for stock in securities
            if str(stock.get("symbol") or "").strip()
        ][: args.count]
    if not requested_symbols:
        requested_symbols = ["API"]

    security_ids: dict[str, str] = {}
    if "start_stockquote" in transactions:
        for symbol in requested_symbols:
            security = await tms_user.get_security_id(symbol)
            security_id = str(security.get("id") or "").strip()
            if not security_id:
                raise RuntimeError(f"Could not resolve security id for symbol {symbol!r}")
            security_ids[symbol] = security_id

    socket_url = (
        f"wss://tms{broker_no}.nepsetms.com.np//tmsapi/socket"
        f"?memberId={request_owner}&clientId={client_dealer_id}&dealerId=&userId={request_owner}"
    )
    headers = {
        "Pragma": "no-cache",
        "Origin": f"https://tms{broker_no}.nepsetms.com.np",
        "Accept-Language": "en-US,en;q=0.9",
        "Cookie": build_cookie_header(tokens),
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Cache-Control": "no-cache",
        "Sec-GPC": "1",
    }

    print(json.dumps({
        "login_status": login_status,
        "client_id": client_id,
        "broker_no": broker_no,
        "request_owner": request_owner,
        "client_dealer_id": client_dealer_id,
        "symbols": requested_symbols,
        "security_ids": security_ids,
        "socket_url": socket_url,
    }, indent=2, default=str))

    if args.fanout and len(requested_symbols) > 1:
        semaphore = asyncio.Semaphore(max(1, int(args.max_concurrency)))

        async def guarded(symbol: str) -> dict:
            async with semaphore:
                return await run_symbol_socket(
                    socket_url=socket_url,
                    headers=headers,
                    symbol=symbol,
                    security_id=security_ids[symbol],
                    transactions=transactions,
                    frames=args.frames,
                    timeout=args.timeout,
                )

        results = await asyncio.gather(*(guarded(symbol) for symbol in requested_symbols))
        summary = {
            "total_symbols": len(results),
            "ok": sum(1 for item in results if not item["error"]),
            "failed": [item["symbol"] for item in results if item["error"]],
        }
        print(json.dumps(summary, indent=2, default=str))
        return

    async with websockets.connect(socket_url, **connect_kwargs(headers)) as websocket:
        for transaction in transactions:
            if transaction == "start_stockquote":
                for symbol in requested_symbols:
                    await websocket.send(json.dumps({
                        "header": {"channel": "@control", "transaction": transaction},
                        "payload": {"argument": security_ids[symbol]},
                    }))
            else:
                await websocket.send(json.dumps({
                    "header": {"channel": "@control", "transaction": transaction},
                    "payload": {"argument": "undefined"},
                }))

        for index in range(args.frames):
            message = await asyncio.wait_for(websocket.recv(), timeout=args.timeout)
            print(f"MSG {index + 1}: {message}")


if __name__ == "__main__":
    asyncio.run(main())
