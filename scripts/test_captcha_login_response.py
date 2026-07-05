"""
Test the algorithmic captcha solver (port of arpandaze/tms-captcha extension)
with live TMS API for broker 35 using test user credentials.

Usage:
    python3 scripts/test_captcha_login_response.py
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from pathlib import Path

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utils.tms_captcha_solver.solver import solve_captcha

TEST_USER_FILE = ROOT / "utils" / "test_user_login_details.json"

HEADERS = {
    "authority": "tms35.nepsetms.com.np",
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-US,en;q=0.7",
    "content-type": "application/json",
    "origin": "https://tms35.nepsetms.com.np",
    "referer": "https://tms35.nepsetms.com.np/login",
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
}


def load_test_user() -> dict:
    """Load test user credentials from the JSON file."""
    payload = json.loads(TEST_USER_FILE.read_text(encoding="utf-8"))
    users = payload.get("users") or []
    if not users:
        raise RuntimeError(f"No users found in {TEST_USER_FILE}")
    return users[0]


async def main() -> None:
    user = load_test_user()
    client_id = str(user["client_id"]).strip()
    broker_no = str(user["broker_no"]).strip()
    password = str(user["password"]).strip()
    password_b64 = base64.b64encode(password.encode()).decode()

    base = f"https://tms{broker_no}.nepsetms.com.np"
    print(f"Testing captcha solver for broker {broker_no}")
    print(f"User: {client_id}")
    print(f"URL:  {base}")
    print()

    # Step 1: Get captcha ID and image
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{base}/tmsapi/authApi/captcha/id", headers=HEADERS) as resp:
            captcha_id = (await resp.json())["id"]

        async with session.get(
            f"{base}/tmsapi/authApi/captcha/image/{captcha_id}", headers=HEADERS
        ) as resp:
            image_data = await resp.read()

    print(f"Captcha ID: {captcha_id}")
    print(f"Image size: {len(image_data)} bytes")

    # Step 2: Solve the captcha using the extension's algorithm
    captcha_text = await solve_captcha(image_data)
    print(f"Solved:    {captcha_text!r}")

    if not captcha_text or len(captcha_text) != 6:
        print("RESULT: Could not solve captcha (invalid result)")
        return

    # Step 3: Submit login with actual password
    payload = {
        "userName": client_id,
        "password": password_b64,
        "jwt": "",
        "otp": "",
        "captchaIdentifier": captcha_id,
        "userCaptcha": captcha_text,
    }

    async with aiohttp.ClientSession() as login_session:
        async with login_session.post(
            f"{base}/tmsapi/authApi/authenticate",
            headers=HEADERS,
            json=payload,
        ) as resp:
            body = await resp.json()

    # Print results
    print(f"HTTP:      {resp.status}")
    print(f"TMS:       {body.get('status')}")
    print(f"Message:   {body.get('message')!r}")

    tms_status = str(body.get("status", ""))
    tms_msg = str(body.get("message", "")).lower()

    if tms_status == "108":
        print("RESULT: ❌ Captcha REJECTED by TMS (solver returned wrong text)")
    elif tms_status == "202" or "userdetails" in tms_msg:
        print("RESULT: ✅✅✅ Login SUCCESSFUL! Captcha solver works!")
        if body.get("data"):
            user_data = body["data"].get("user", {})
            print(f"        User: {user_data.get('displayName')} ({user_data.get('userName')})")
    elif "credential" in tms_msg:
        print("RESULT: ✅ Captcha ACCEPTED (wrong password used)")
    else:
        tms_data = body.get("data", {})
        if tms_data:
            user_data = tms_data.get("user", {})
            if user_data:
                print("RESULT: ✅✅✅ Login SUCCESSFUL! Captcha solver works!")
                print(f"        User: {user_data.get('displayName')} ({user_data.get('userName')})")
            else:
                print(f"RESULT: {body}")
        else:
            print(f"RESULT: {body}")


if __name__ == "__main__":
    asyncio.run(main())
