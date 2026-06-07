"""Try TMS login candidates to find the current working password."""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utils.tms import TmsUser
from utils.tms_captcha_solver.imgto_txt import solve_captcha

CAPTCHA_RETRIES = 6


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test TMS password candidates.")
    parser.add_argument("--broker", default=os.getenv("TMS_BROKER_NO", "35"))
    parser.add_argument("--username", default=os.getenv("TMS_USERNAME"), required=False)
    parser.add_argument("--password", default=os.getenv("TMS_PASSWORD"), required=False)
    return parser.parse_args()


def build_headers(broker_no: str) -> dict[str, str]:
    return {
        "authority": f"tms{broker_no}.nepsetms.com.np",
        "accept": "application/json, text/plain, */*",
        "accept-language": "en-US,en;q=0.7",
        "content-type": "application/json",
        "origin": f"https://tms{broker_no}.nepsetms.com.np",
        "referer": f"https://tms{broker_no}.nepsetms.com.np/login",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
    }


def build_candidates(original_password: str) -> list[tuple[str, str]]:
    seen: set[str] = set()
    ordered: list[tuple[str, str]] = []

    def add(label: str, password: str) -> None:
        if password in seen:
            return
        seen.add(password)
        ordered.append((label, password))

    add("original", original_password)
    for label, password in TmsUser.rotation_password_candidates(original_password):
        add(label, password)
    return ordered


async def fetch_captcha(
    session: aiohttp.ClientSession,
    base: str,
    headers: dict[str, str],
) -> tuple[str, str]:
    async with session.get(f"{base}/tmsapi/authApi/captcha/id", headers=headers) as response:
        captcha_id = (await response.json())["id"]
    async with session.get(f"{base}/tmsapi/authApi/captcha/image/{captcha_id}", headers=headers) as response:
        image = await response.read()
    captcha = await solve_captcha(image)
    return captcha_id, captcha


async def try_password(
    session: aiohttp.ClientSession,
    base: str,
    headers: dict[str, str],
    username: str,
    label: str,
    plain_password: str,
) -> dict | None:
    encoded = TmsUser.encode_base64(plain_password)
    last_body: dict = {}

    for attempt in range(1, CAPTCHA_RETRIES + 1):
        captcha_id, captcha = await fetch_captcha(session, base, headers)
        payload = {
            "userName": username,
            "password": encoded,
            "jwt": "",
            "otp": "",
            "captchaIdentifier": captcha_id,
            "userCaptcha": captcha,
        }
        async with session.post(f"{base}/tmsapi/authApi/authenticate", headers=headers, json=payload) as response:
            body = await response.json()
        last_body = body
        status = str(body.get("status", ""))
        message = str(body.get("message", ""))

        if TmsUser.is_login_success(status):
            return {
                "label": label,
                "plain_password": plain_password,
                "status": status,
                "message": message,
                "expiry": (body.get("data") or {}).get("user", {}).get("passwordExpirationDate"),
            }

        if "credential" in message.lower():
            print(f"  wrong password ({label})")
            return None

        if status == "108":
            print(f"  captcha retry {attempt}/{CAPTCHA_RETRIES} for {label}")
            continue

        print(f"  unexpected status={status} message={message} for {label}")
        return None

    print(f"  gave up on {label} after captcha failures; last={last_body.get('message')}")
    return None


async def main() -> None:
    args = parse_args()
    if not args.username or not args.password:
        raise SystemExit(
            "Provide --username and --password, or set TMS_USERNAME and TMS_PASSWORD in the environment."
        )

    base = f"https://tms{args.broker}.nepsetms.com.np"
    headers = build_headers(args.broker)
    candidates = build_candidates(args.password)
    print(f"Testing {len(candidates)} password candidate(s) for {args.username}...")

    async with aiohttp.ClientSession() as session:
        for index, (label, plain_password) in enumerate(candidates, start=1):
            print(f"[{index}/{len(candidates)}] trying {label}")
            result = await try_password(session, base, headers, args.username, label, plain_password)
            if result:
                print("\nFOUND WORKING PASSWORD")
                print("label:", result["label"])
                print("password:", result["plain_password"])
                print("status:", result["status"])
                print("message:", result["message"])
                print("expiry:", result["expiry"])
                return

    print("\nNo working password found in candidate list.")


if __name__ == "__main__":
    asyncio.run(main())
