"""
Batch test the fast captcha solver: solve 100 captchas, submit each with
wrong password, track acceptance/rejection by TMS.

Usage:
    python3 scripts/batch_test_captcha.py [--count 100] [--broker 35]
"""
from __future__ import annotations

import asyncio
import base64
import json
import sys
import time
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
    payload = json.loads(TEST_USER_FILE.read_text(encoding="utf-8"))
    users = payload.get("users") or []
    if not users:
        raise RuntimeError(f"No users found in {TEST_USER_FILE}")
    return users[0]


async def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Batch test captcha solver accuracy")
    parser.add_argument("--count", type=int, default=100, help="Number of captchas to test")
    parser.add_argument("--broker", type=str, default="35", help="Broker number")
    args = parser.parse_args()

    user = load_test_user()
    client_id = str(user["client_id"]).strip()
    broker_no = str(user["broker_no"]).strip()
    password = str(user["password"]).strip()
    password_b64 = base64.b64encode(password.encode()).decode()

    base = f"https://tms{broker_no}.nepsetms.com.np"
    dummy_password = base64.b64encode(b"wrong-password-for-testing").decode()

    print(f"Testing fast captcha solver for broker {broker_no}")
    print(f"User: {client_id}")
    print(f"Target: {args.count} captchas")
    print()

    stats = {
        "total": 0,
        "solved": 0,       # solve_captcha returned a 6-char string
        "accepted": 0,     # TMS accepted the captcha (credential error = captcha OK)
        "rejected": 0,     # TMS rejected the captcha (status 108)
        "errors": 0,       # HTTP/network errors
        "solve_times": [],
    }

    async with aiohttp.ClientSession() as session:
        for i in range(args.count):
            stats["total"] += 1

            # --- download captcha ---
            try:
                async with session.get(f"{base}/tmsapi/authApi/captcha/id", headers=HEADERS) as resp:
                    captcha_id = (await resp.json())["id"]
                async with session.get(
                    f"{base}/tmsapi/authApi/captcha/image/{captcha_id}", headers=HEADERS
                ) as resp:
                    img_bytes = await resp.read()
            except Exception as e:
                print(f"[{i+1:3d}] NETWORK ERROR downloading captcha: {e}")
                stats["errors"] += 1
                continue

            # --- solve ---
            t0 = time.perf_counter()
            captcha_text = await solve_captcha(img_bytes)
            t1 = time.perf_counter()
            solve_ms = (t1 - t0) * 1000
            stats["solve_times"].append(solve_ms)

            if not captcha_text or len(captcha_text) != 6:
                print(f"[{i+1:3d}] SKIP  text={captcha_text!r:8s}  ({solve_ms:5.0f}ms)")
                continue

            stats["solved"] += 1

            # --- submit login with dummy password ---
            payload = {
                "userName": client_id,
                "password": dummy_password,
                "jwt": "",
                "otp": "",
                "captchaIdentifier": captcha_id,
                "userCaptcha": captcha_text,
            }
            try:
                async with session.post(
                    f"{base}/tmsapi/authApi/authenticate",
                    headers=HEADERS,
                    json=payload,
                ) as resp:
                    body = await resp.json()
                    tms_status = str(body.get("status", ""))
                    tms_msg = str(body.get("message", "")).lower()

                is_accepted = (
                    "credential" in tms_msg
                    or tms_status == "202"
                    or "userdetails" in tms_msg
                )
                is_rejected = tms_status == "108"

                if is_accepted:
                    stats["accepted"] += 1
                    marker = "ACCEPT"
                elif is_rejected:
                    stats["rejected"] += 1
                    marker = "REJECT"
                else:
                    stats["rejected"] += 1
                    marker = f"OTHER({tms_status})"

                print(
                    f"[{i+1:3d}] {marker:6s} text={captcha_text!r}  "
                    f"({solve_ms:5.0f}ms)"
                )
            except Exception as e:
                print(f"[{i+1:3d}] ERROR submitting login: {e}")
                stats["errors"] += 1

        # --- summary ---
        print()
        print("=" * 60)
        print("BATCH TEST RESULTS")
        print("=" * 60)
        print(f"  Total captchas attempted:  {stats['total']}")
        print(f"  Successfully solved (6-char): {stats['solved']}")
        if stats["solve_times"]:
            avg_ms = sum(stats["solve_times"]) / len(stats["solve_times"])
            max_ms = max(stats["solve_times"])
            min_ms = min(stats["solve_times"])
            print(f"  Solve time:  avg={avg_ms:.0f}ms  min={min_ms:.0f}ms  max={max_ms:.0f}ms")
        print(f"  Accepted by TMS:          {stats['accepted']}")
        print(f"  Rejected by TMS:          {stats['rejected']}")
        print(f"  Network errors:           {stats['errors']}")

        solved = stats["solved"]
        accepted = stats["accepted"]
        rejected = stats["rejected"]

        if solved > 0:
            solve_rate = solved / stats["total"] * 100
            print(f"  Solve rate:               {solve_rate:.1f}%")
        if accepted + rejected > 0:
            accuracy = accepted / (accepted + rejected) * 100 if (accepted + rejected) > 0 else 0
            print(f"  Captcha accuracy:         {accuracy:.1f}%  ({accepted}/{accepted + rejected})")
        print("=" * 60)

    return 0 if accepted > rejected else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
