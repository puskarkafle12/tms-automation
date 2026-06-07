"""Submit OCR captcha with dummy credentials to see if TMS accepts captcha format."""
from __future__ import annotations

import asyncio
import base64
import sys
from pathlib import Path

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utils.tms_captcha_solver.imgto_txt import solve_captcha


HEADERS = {
    "authority": "tms35.nepsetms.com.np",
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-US,en;q=0.7",
    "content-type": "application/json",
    "origin": "https://tms35.nepsetms.com.np",
    "referer": "https://tms35.nepsetms.com.np/login",
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
}


async def main(broker_no: str = "35", username: str = "YOUR_CLIENT_ID") -> None:
    base = f"https://tms{broker_no}.nepsetms.com.np"
    async with aiohttp.ClientSession() as captcha_session:
        async with captcha_session.get(f"{base}/tmsapi/authApi/captcha/id", headers=HEADERS) as response:
            captcha_id = (await response.json())["id"]
        async with captcha_session.get(f"{base}/tmsapi/authApi/captcha/image/{captcha_id}", headers=HEADERS) as response:
            image = await response.read()

    captcha = await solve_captcha(image)
    payload = {
        "userName": username,
        "password": base64.b64encode(b"invalid-password-test").decode("utf-8"),
        "jwt": "",
        "otp": "",
        "captchaIdentifier": captcha_id,
        "userCaptcha": captcha,
    }

    async with aiohttp.ClientSession() as login_session:
        async with login_session.post(f"{base}/tmsapi/authApi/authenticate", headers=HEADERS, json=payload) as response:
            body = await response.json()

    print("captcha_id:", captcha_id)
    print("ocr_text:", repr(captcha))
    print("http_status:", response.status)
    print("tms_status:", body.get("status"))
    print("tms_message:", body.get("message"))
    if body.get("status") == "108":
        print("RESULT: captcha rejected by TMS (OCR likely wrong)")
    elif "credential" in str(body.get("message", "")).lower():
        print("RESULT: captcha accepted, credentials rejected (OCR is working)")
    else:
        print("RESULT:", body)


if __name__ == "__main__":
    asyncio.run(main())
