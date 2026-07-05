import asyncio
import inspect
import json
from pathlib import Path

import websockets

from utils.tms import TmsUser


TEST_USER_FILE = Path(__file__).resolve().parent / "utils" / "test_user_login_details.json"


def load_test_user() -> dict:
    data = json.loads(TEST_USER_FILE.read_text(encoding="utf-8"))
    return data["users"][0]


def build_cookie_header(tokens: dict) -> str:
    return "; ".join(f"{key}={value}" for key, value in tokens.items() if value)


def connect_kwargs(headers: dict) -> dict:
    signature = inspect.signature(websockets.connect)
    if "additional_headers" in signature.parameters:
        return {"additional_headers": headers}
    return {"extra_headers": headers}


async def main():
    user = load_test_user()
    broker_no = str(user["broker_no"]).strip()
    client_id = str(user["client_id"]).strip()
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
        raise RuntimeError("Missing session identifiers after login")

    symbol = "API"
    security = await tms_user.get_security_id(symbol)
    security_id = str(security.get("id") or "").strip()
    if not security_id:
        raise RuntimeError(f"Missing security id for {symbol}")

    uri = (
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
        "symbol": symbol,
        "security_id": security_id,
        "uri": uri,
    }, indent=2, default=str))

    async with websockets.connect(uri, **connect_kwargs(headers)) as websocket:
        await websocket.send(json.dumps({
            "header": {"channel": "@control", "transaction": "start_stockquote"},
            "payload": {"argument": security_id},
        }))
        count = 0
        while True:
            response = await asyncio.wait_for(websocket.recv(), timeout=15)
            count += 1
            print(f"MSG {count}: {response}")


if __name__ == "__main__":
    asyncio.run(main())
