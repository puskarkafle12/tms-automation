import asyncio
import base64
from datetime import date, datetime, time
from http.cookies import SimpleCookie
import json
import time as monotonic_time
from typing import Any, Dict, Iterator, List, Optional, Tuple
import aiohttp
from database import get_db_session
from exceptions.login_exceptions import LoginFailedException
from models.logged_in_user import LoggedInUsers
from models.tms_password_backup import TmsPasswordBackup
from models.user import User
from utils.tms_captcha_solver.solver import solve_captcha
from utils.tms_broker import normalize_broker_no
from utils.base_functions import (
    NEPSE_INTRADAY_LIMIT_PERCENT,
    calculate_high_price,
    get_tokens,
    is_stock_grabber_stop_reached,
    log_time,
    logout_user,
    save_collateral,
    save_tokens,
    summarize_login_message,
)
from utils.live_quote_socket import is_live_socket_snapshot, live_quote_manager

class TmsUser:
    DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=12, connect=4, sock_read=8)
    QUOTE_TIMEOUT = aiohttp.ClientTimeout(total=3, connect=1, sock_read=2)
    TRADEBOOK_TIMEOUT = aiohttp.ClientTimeout(total=90, connect=10, sock_read=60)
    TRADEBOOK_CHUNK_DAYS = 366
    TRADEBOOK_MAX_CONCURRENT_CHUNKS = 4
    TRADEBOOK_PAGE_RETRIES = 3
    AUTH_REFRESH_TIMEOUT = aiohttp.ClientTimeout(total=8, connect=3, sock_read=4)
    AUTH_REFRESH_COOLDOWN_SECONDS = 60
    _security_cache: Dict[str, tuple[float, List[Dict]]] = {}
    _security_cache_ttl = 300.0
    _collateral_cache: Dict[str, tuple[float, Dict]] = {}
    _collateral_cache_ttl = 300.0
    _quote_cache: Dict[str, tuple[float, Dict]] = {}
    _quote_cache_ttl = 2.0
    _quote_stale_ttl = 60.0
    _quote_failures: Dict[str, tuple[int, float]] = {}
    _quote_circuit_failure_limit = 3
    _quote_circuit_cooldown = 15.0
    _stock_grabber_socket_wait_seconds = 0.15
    _full_login_lock: Optional[asyncio.Lock] = None
    _non_live_request_cache: Dict[str, tuple[float, int, object]] = {}
    _non_live_request_cache_ttl = 3600.0
    _market_live_override: Optional[tuple[float, bool]] = None
    _market_live_override_ttl = 90.0

    def __init__(
        self,
        broker_no,
        username=None,
        password=None,
        tokens=None,
        stock_symbol=None,
        request_per_sec=2,
        scan_mode="socket",
        resume_scan_count=0,
        resume_previous_ltp=0.0,
        resume_stable_rate=None,
    ):
        broker_no = normalize_broker_no(str(broker_no or ""))
        self.final_order_quantity = 20
        self.order_quantity=10
        self.client_id = username
        self.password = password
        self.tokens = tokens
        self.driver = None
        self.session: Optional[aiohttp.ClientSession] = None
        self._auth_refresh_lock = asyncio.Lock()
        self._session_lock = asyncio.Lock()
        self._auth_refresh_failed_at: float = 0.0
        self._allow_full_login_on_refresh = True
        self.security = None
        self.stock_symbol = stock_symbol
        self.scan_mode = "fixed" if str(scan_mode or "").lower() == "fixed" else "socket"
        self.max_request_per_sec = 5.0  # Maximum fetch rate
        self.min_request_per_sec = 3.0
        requested_rate = float(request_per_sec or self.min_request_per_sec)
        self.request_per_sec = min(self.max_request_per_sec, max(requested_rate, self.min_request_per_sec))
        self.total_requests = 0  #
        self.broker_no = broker_no
        self.client_details = None
        self.success_count = 0  # Track successful requests
        self.stable_rate = None  # Fixed rate once determined
        self.stable_cycles = 0  # Count cycles with high success rate
        self.trial_requests = 0  # Count requests during trial period
        self.scan_count = int(resume_scan_count or 0)
        self.resume_previous_ltp = float(resume_previous_ltp or 0.0)
        if resume_stable_rate and float(resume_stable_rate) > 0:
            self.stable_rate = min(self.max_request_per_sec, max(float(resume_stable_rate), self.min_request_per_sec))
            self.request_per_sec = self.stable_rate
        self.updates: List[Dict] = []  # Store updates for polling

        self.headers = {
            'authority': f'tms{broker_no}.nepsetms.com.np',
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'en-US,en;q=0.7',
            'content-type': 'application/json',
            'origin': f'https://tms{self.broker_no}.nepsetms.com.np',
            'referer': f'https://tms{self.broker_no}.nepsetms.com.np/login',
            'sec-ch-ua': '"Not.A/Brand";v="8", "Chromium";v="114", "Brave";v="114"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"macOS"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'sec-gpc': '1',
            'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
        }
    def __del__(self):
        if self.session and not getattr(self.session, "closed", True):
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                try:
                    asyncio.run(self.close())
                except Exception as e:
                    print(f"Exception during __del__: {e}")
            except Exception as e:
                print(f"Exception during __del__: {e}")
            else:
                loop.create_task(self.close())

    async def close(self):
        if self.session and not getattr(self.session, "closed", True):
            close = getattr(self.session, "close", None)
            if callable(close):
                close_result = close()
                if asyncio.iscoroutine(close_result):
                    await close_result
        self.session = None

    async def __aenter__(self):
        return self

    # async def __aexit__(self, exc_type, exc, tb):
    #     await self.close()

    async def try_token_login(self):
        if self.tokens:
            try:
                self.login_response = self.tokens
                request_owner = self.tokens['request_owner']
                self.tokens = self.tokens['tokens']
                self.headers = self.get_header(request_owner, self.tokens)
                self.client_details = await self.get_client_details(self.tokens, self.headers, self.login_response['client_dealer_id'])
            except Exception as e:
                db = get_db_session()
                try:
                    user = db.query(User).filter(User.client_id == self.client_id).first()
                    if not user:
                        print()
                    if user.auto_login:
                        self.password = user.password
                        self.broker_no = user.broker_no
                        try:
                            await self.try_cached_login()
                        except Exception as e:
                            logged_in_user = db.query(LoggedInUsers).filter(LoggedInUsers.client_id == self.client_id).first()
                            logged_in_user.status = "logged_out"
                            logged_in_user.message = "exception while login error message ::" + str(e)
                            db.commit()
                            raise LoginFailedException("login failed " + str(e))
                    else:
                        logged_in_user = db.query(LoggedInUsers).filter(LoggedInUsers.client_id == self.client_id).first()
                        logged_in_user.status = "logged_out"
                        logged_in_user.message = "auto login disabled user token expire re-login again::" + str(e)
                        db.commit()
                        raise LoginFailedException("login failed " + str(e))
                finally:
                    db.close()

    async def _load_password_from_db(self) -> None:
        if self.password:
            return
        db = get_db_session()
        try:
            user = db.query(User).filter(User.client_id == self.client_id).first()
            if user:
                self.password = user.password
                if user.broker_no:
                    self.broker_no = user.broker_no
        finally:
            db.close()

    async def _load_session_from_store(self) -> bool:
        stored, broker_no = get_tokens(self.client_id)
        if broker_no:
            self.broker_no = broker_no
        if not stored:
            return False

        tokens = stored.get("tokens") or {}
        request_owner = stored.get("request_owner")
        client_dealer_id = stored.get("client_dealer_id")
        if not tokens or request_owner is None or client_dealer_id is None:
            return False

        self.login_response = stored
        self.tokens = tokens
        self.headers = self.get_header(request_owner, self.tokens)
        return True

    async def _validate_session(self) -> None:
        client_dealer_id = (self.login_response or {}).get("client_dealer_id")
        if not client_dealer_id:
            raise LoginFailedException("Missing client dealer id in cached session")
        self.client_details = await self.get_client_details(
            self.tokens,
            self.headers,
            client_dealer_id,
        )
        if self.login_response is not None:
            self.login_response["client_details"] = self.client_details

    async def _persist_logged_in_session(
        self,
        message: str,
        *,
        update_login_time: bool = False,
    ) -> None:
        if not self.login_response:
            return
        self.login_response["tokens"] = dict(self.tokens or {})
        save_tokens(
            self.client_id,
            self.login_response,
            self.broker_no,
            update_login_time=update_login_time,
        )
        await self.save_login_info()

    def _login_success_payload(
        self,
        message: str,
        rotation_result: Optional[Dict] = None,
    ) -> Dict:
        rotation_result = rotation_result or {}
        return {
            "status": "success",
            "message": message,
            "password_expiry": (self.login_response or {}).get("password_expiry"),
            "password_rotated": rotation_result.get("rotated", False),
            "new_password_plain": rotation_result.get("new_password_plain"),
        }

    async def _full_login_and_persist(self) -> Dict:
        await self._load_password_from_db()
        if not self.password:
            raise LoginFailedException("No TMS password available for login")

        async with self._get_full_login_lock():
            self.login_response = await self.login()
            self.tokens = self.login_response["tokens"]
            self.headers = self.get_header(self.login_response["request_owner"], self.tokens)
            rotation_result = await self.rotate_password_if_expired()
            await self._validate_session()
            message = (
                rotation_result["message"]
                if rotation_result.get("rotated")
                else "token refreshed and stored in the database"
            )
            await self._persist_logged_in_session(message, update_login_time=True)
            return self._login_success_payload(message, rotation_result)

    async def try_cached_login(self, *, allow_full_login: bool = True):
        self._allow_full_login_on_refresh = allow_full_login
        await self._load_password_from_db()
        rotation_result: Dict = {"rotated": False}

        if await self._load_session_from_store():
            try:
                rotation_result = await self.rotate_password_if_expired()
                await self._validate_session()
                message = (
                    rotation_result["message"]
                    if rotation_result.get("rotated")
                    else "token successfully loaded from the cache file"
                )
                await self._persist_logged_in_session(message, update_login_time=False)
                return self._login_success_payload(message, rotation_result)
            except Exception:
                pass

            if await self.refresh_auth_token():
                try:
                    rotation_result = await self.rotate_password_if_expired()
                    await self._validate_session()
                    message = "token refreshed without captcha"
                    await self._persist_logged_in_session(message, update_login_time=False)
                    return self._login_success_payload(message, rotation_result)
                except Exception:
                    pass

        if not allow_full_login:
            raise LoginFailedException("Cached TMS session is unavailable; full captcha login skipped")

        return await self._full_login_and_persist()

    async def get_captcha_id(self, headers):
        await self._ensure_session()
        async with self.session.get(f'https://tms{self.broker_no}.nepsetms.com.np/tmsapi/authApi/captcha/id', headers=headers) as response:
            return (await response.json())['id']

    async def get_captcha_image(self, headers, captcha_id):
        await self._ensure_session()
        async with self.session.get(f'https://tms{self.broker_no}.nepsetms.com.np/tmsapi/authApi/captcha/image/{captcha_id}', headers=headers) as response:
            return await response.read()

    def get_header(self, request_owner, token):
        header = {
            'authority': f'tms{self.broker_no}.nepsetms.com.np',
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'en-US,en;q=0.9',
            'host-session-id': 'TVRJPS1lYWU2MTU0ZS0xODkyLTQxNDEtYTczZS1kMGI1YmM5N2I1YzQ=',
            'membercode': str(self.broker_no),
            'referer': f'https://tms{self.broker_no}.nepsetms.com.np/tms/me/memberclientorderentry',
            'request-owner': str(request_owner),
            'sec-ch-ua': '"Google Chrome";v="117", "Not;A=Brand";v="8", "Chromium";v="117"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"macOS"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36',
            'x-xsrf-token': token['XSRF-TOKEN'],
        }
        return header

    async def get_request_owner(self, cookies, headers):
        await self._ensure_session()
        async with self.session.get(
            f'https://tms{self.broker_no}.nepsetms.com.np/tmsapi/exchangeIndex/getExchangeIndexForCurrentUser',
            cookies=cookies,
            headers=headers,
        ) as response:
            return json.loads(await response.text())['data'][0]['userId']

    @classmethod
    def clear_security_cache(cls, broker_no: Optional[str] = None) -> None:
        if broker_no is None:
            cls._security_cache.clear()
            return
        cls._security_cache.pop(str(broker_no), None)

    @classmethod
    def clear_collateral_cache(cls, client_id: Optional[str] = None) -> None:
        if client_id is None:
            cls._collateral_cache.clear()
            return
        cls._collateral_cache.pop(str(client_id), None)

    @classmethod
    def get_cached_collateral_for_client(cls, client_id: str) -> Optional[Dict]:
        cached = cls._collateral_cache.get(str(client_id))
        now = monotonic_time.monotonic()
        if cached and now - cached[0] < cls._collateral_cache_ttl:
            return cached[1]
        return None

    def _collateral_cache_key(self) -> str:
        if self.client_id:
            return str(self.client_id)
        if self.client_details:
            return str(self.client_details.get("id") or "")
        return ""

    def get_cached_client_collateral(self) -> Optional[Dict]:
        return self.get_cached_collateral_for_client(self._collateral_cache_key())

    async def get_securities(self, *, force_refresh: bool = False) -> List[Dict]:
        broker_key = str(self.broker_no)
        cached = self._security_cache.get(broker_key)
        now = monotonic_time.monotonic()
        if not force_refresh and cached and now - cached[0] < self._security_cache_ttl:
            return cached[1]

        _, stocks = await self._authenticated_request(
            "GET",
            f'https://tms{self.broker_no}.nepsetms.com.np/tmsapi/stock/securities',
            expected_statuses={200},
        )
        self._security_cache[broker_key] = (now, stocks)
        return stocks

    async def get_security_id(self, symbol) -> Dict:
        symbol = symbol.upper().strip()
        for stock in await self.get_securities():
            if stock.get('symbol') == symbol:
                return stock
        return {}

    async def login_request(self, logindata):
        json_data = {
            'userName': logindata['username'],
            'password': logindata['password'],
            'jwt': '',
            'otp': '',
            'captchaIdentifier': logindata['captcha_id'],
            'userCaptcha': logindata['captcha'],
        }
        await self._ensure_session()
        async with self.session.post(
            f'https://tms{self.broker_no}.nepsetms.com.np/tmsapi/authApi/authenticate',
            headers=self.headers,
            json=json_data,
        ) as response:
            simple_cookie = SimpleCookie(response.cookies)
            tokens_dict = {key: morsel.value for key, morsel in simple_cookie.items()}
            response_data = await response.json()
            return response_data, tokens_dict

    @staticmethod
    def is_login_success(status: Optional[str]) -> bool:
        return str(status) in ("202", "210")

    @staticmethod
    def is_password_expired(password_expiry: Optional[str], today: Optional[date] = None) -> bool:
        if not password_expiry:
            return False
        try:
            expiry_date = datetime.fromisoformat(str(password_expiry)[:10]).date()
        except ValueError:
            return False
        return expiry_date <= (today or date.today())

    @staticmethod
    def decode_password_payload(encoded_password: str) -> str:
        return base64.b64decode(encoded_password.encode("utf-8")).decode("utf-8")

    TMS_PASSWORD_MIN_LEN = 7
    TMS_PASSWORD_MAX_LEN = 14

    @staticmethod
    def satisfies_tms_password_rules(password: str) -> bool:
        if not (TmsUser.TMS_PASSWORD_MIN_LEN <= len(password) <= TmsUser.TMS_PASSWORD_MAX_LEN):
            return False
        if not any(char.isupper() for char in password):
            return False
        if not any(char.isdigit() for char in password):
            return False
        if not any(not char.isalnum() for char in password):
            return False
        return True

    @staticmethod
    def password_rotation_number(plain_password: str) -> int:
        _, rotation_number = TmsUser.password_rotation_parts(plain_password)
        return rotation_number

    @staticmethod
    def password_rotation_parts(plain_password: str) -> tuple[str, int]:
        trailing_digits = ""
        for char in reversed(plain_password):
            if not char.isdigit():
                break
            trailing_digits = char + trailing_digits
        if trailing_digits:
            return plain_password[: -len(trailing_digits)], int(trailing_digits)
        return plain_password[:-1], 0

    @staticmethod
    def with_rotation_number(plain_password: str, rotation_number: int) -> str:
        """Replace the tail of the password so length stays the same.

        Examples:
            Abcdef@9  -> Abcdef10   (last 2 chars "@9" become "10")
            Abc@ef99  -> Abc@e100   (last 3 chars "f99" become "100")
        """
        new_suffix = str(rotation_number)
        replace_len = len(new_suffix)
        if replace_len > len(plain_password):
            raise LoginFailedException(
                "Cannot rotate password: new suffix is longer than the current password."
            )
        return plain_password[:-replace_len] + new_suffix

    @staticmethod
    def describe_numbered_password(rotation_number: int) -> str:
        if rotation_number < 10:
            return f"rotation {rotation_number} (last digit)"
        return f"rotation {rotation_number} (last {len(str(rotation_number))} digits)"

    @staticmethod
    def rotation_password_candidates(plain_password: str) -> List[tuple[str, str]]:
        """Build unused-password candidates; TMS rejects passwords already in history."""
        results: List[tuple[str, str]] = []
        seen = {plain_password}

        def add(label: str, candidate: str) -> None:
            if candidate in seen or not TmsUser.satisfies_tms_password_rules(candidate):
                return
            seen.add(candidate)
            results.append((label, candidate))

        current_number = TmsUser.password_rotation_number(plain_password)
        for rotation_number in range(current_number + 1, 1000):
            add(
                TmsUser.describe_numbered_password(rotation_number),
                TmsUser.with_rotation_number(plain_password, rotation_number),
            )

        if not results:
            raise LoginFailedException(
                "Cannot build a new numbered password for rotation within TMS 7-14 char rules."
            )
        return results

    async def rotate_password_if_expired(self, *, auto_rotate: bool = True) -> Dict:
        password_expiry = (self.login_response or {}).get("password_expiry")
        if not self.is_password_expired(password_expiry):
            return {"rotated": False, "message": "password is not expired"}

        if not auto_rotate:
            raise LoginFailedException(
                f"TMS password expired on {password_expiry}. Enable auto rotation to continue."
            )

        old_password = self.password
        plain_password = self.decode_password_payload(old_password)
        candidates = self.rotation_password_candidates(plain_password)
        last_error: Optional[Exception] = None
        current_label = self.describe_numbered_password(
            self.password_rotation_number(plain_password)
        )

        for new_label, new_plain in candidates:
            new_password = self.encode_base64(new_plain)
            try:
                await self.change_password(old_password, new_password)
                self.password = new_password
                await self.save_login_info()
                await self.save_password_backup(new_password, new_label)
                return {
                    "rotated": True,
                    "password_changed": True,
                    "new_password_plain": new_plain,
                    "message": (
                        f"TMS password expired on {password_expiry}. "
                        f"Changed from {current_label} to {new_label}. "
                        f"Use this new password for future logins: {new_plain}"
                    ),
                }
            except Exception as exc:
                last_error = exc
                continue

        self.password = old_password
        tried = ", ".join(label for label, _ in candidates[:12])
        if len(candidates) > 12:
            tried += f", ... (+{len(candidates) - 12} more)"
        raise LoginFailedException(
            f"Password rotation failed after trying {len(candidates)} new password(s) [{tried}]: {last_error}"
        )

    async def change_password(self, current_password: str, new_password: str) -> Dict:
        if not self.tokens or not self.headers:
            raise LoginFailedException("Cannot change password without an authenticated TMS session")

        await self._ensure_session()
        payload = {
            "currentPassword": current_password,
            "newPassword": new_password,
        }
        headers = {
            **self.headers,
            "content-type": "application/json",
            "membercode": str(self.broker_no),
            "origin": f"https://tms{self.broker_no}.nepsetms.com.np",
            "referer": f"https://tms{self.broker_no}.nepsetms.com.np/tms/changepassword",
        }
        url = f"https://tms{self.broker_no}.nepsetms.com.np/tmsapi/authApi/authenticate/updatepassword"
        async with self.session.post(
            url, headers=headers, cookies=self.tokens, json=payload, timeout=aiohttp.ClientTimeout(total=30)
        ) as response:
            response_text = await response.text()
            try:
                response_json = json.loads(response_text) if response_text else {}
            except json.JSONDecodeError:
                response_json = {"message": response_text[:300]}
            if 200 <= response.status < 300:
                tms_status = str(response_json.get("status", ""))
                if tms_status and tms_status not in ("200", "202", "210"):
                    raise LoginFailedException(
                        self.auth_failure_message(response_json, "updatepassword failed")
                    )
                return {"status": response.status, "message": "password changed", "response": response_json}
            raise LoginFailedException(
                f"updatepassword returned HTTP {response.status}: {response_json.get('message', response_text[:200])}"
            )

    async def fetch_securities_details(self):
        url = f'https://tms{self.broker_no}.nepsetms.com.np/tmsapi/rtApi/ws/top25securities'
        try:
            _, payload = await self._authenticated_request("GET", url, expected_statuses={200})
            return payload
        except aiohttp.ClientError as e:
            return {"error": str(e)}

    async def get_client_details(self, cookies, headers, client_dealer_id):
        _, payload = await self._authenticated_request(
            "GET",
            f'https://tms{self.broker_no}.nepsetms.com.np/tmsapi/clientApi/clientDealer/info/{client_dealer_id}',
            cookies=cookies,
            headers=headers,
            expected_statuses={200},
            retry_on_unauthorized=False,
        )
        return payload

    async def save_login_info(self):
        db = get_db_session()
        try:
            user = db.query(User).filter(User.client_id == self.client_id, User.broker_no == self.broker_no).first()
            if user:
                user.auto_login = True
                if user.password != self.password:
                    user.password = self.password
                    db.commit()
            else:
                new_user = User(client_id=self.client_id, password=self.password, broker_no=self.broker_no, auto_login=True)
                db.add(new_user)
                db.commit()
        except Exception as e:
            print(f"Cannot save the login info to db: {e}")
            db.rollback()
        finally:
            db.close()

    async def save_password_backup(self, encoded_password: str, rotation_label: str) -> None:
        db = get_db_session()
        try:
            backup = TmsPasswordBackup(
                client_id=self.client_id,
                broker_no=self.broker_no,
                password=encoded_password,
                rotation_label=rotation_label,
            )
            db.add(backup)
            db.commit()
        except Exception as e:
            print(f"Cannot save password backup to db: {e}")
            db.rollback()
        finally:
            db.close()

    async def login(self):
        async def get_captcha_data():
            captcha_id = await self.get_captcha_id(self.headers)
            binary_captcha_image = await self.get_captcha_image(self.headers, captcha_id)
            captcha = await solve_captcha(binary_captcha_image)  # Assumes solve_captcha is async-compatible
            return captcha_id, captcha

        login_data = {}
        login_data["captcha_id"], login_data["captcha"] = await get_captcha_data()
        login_data["username"] = self.client_id
        login_data["password"] = self.password

        response_json, tokens_dict = await self.login_request(login_data)

        if response_json.get('status') == '108':
            for _ in range(5):
                login_data["captcha_id"], login_data["captcha"] = await get_captcha_data()
                response_json, tokens_dict = await self.login_request(login_data)

                if 'Credentials Not Found' in str(response_json.get('message', '')):
                    raise LoginFailedException(
                        self.auth_failure_message(response_json, "Credentials Not Found")
                    )

                if self.is_login_success(response_json.get('status')):
                    return self._create_response(response_json, tokens_dict)

            raise LoginFailedException(
                self.auth_failure_message(
                    response_json,
                    "CAPTCHA_VALIDATION_FAILED after 5 attempts",
                )
            )

        if not self.is_login_success(response_json.get('status')):
            raise LoginFailedException(self.auth_failure_message(response_json))

        return self._create_response(response_json, tokens_dict)

    @staticmethod
    def auth_failure_message(response_json: Optional[Dict], default_message: str = "Login failed.") -> str:
        if not isinstance(response_json, dict):
            return default_message

        message = response_json.get("message") or response_json.get("error") or response_json.get("detail")
        if isinstance(message, list):
            message = " ".join(str(item) for item in message if item)
        elif isinstance(message, dict):
            message = message.get("message") or message.get("detail") or json.dumps(message)
        elif message is not None:
            message = str(message)

        status = response_json.get("status")
        http_status = response_json.get("_http_status")

        if not message:
            data = response_json.get("data")
            if isinstance(data, dict):
                nested = data.get("message") or data.get("error") or data.get("detail")
                if nested:
                    message = str(nested)

        if not message:
            message = default_message
        else:
            message = " ".join(str(message).split())

        parts = []
        if status:
            parts.append(f"status={status}")
        if http_status:
            parts.append(f"http={http_status}")
        parts.append(message)
        return " | ".join(parts)

    @staticmethod
    def login_status_summary(message: str) -> str:
        return summarize_login_message(message)

    def _create_response(self, response_json, tokens_dict):
        return {
            "client_dealer_id": response_json['data']['clientDealerMember']['client']['id'],
            "login_response": response_json['data'],
            "password_expiry": response_json['data']['user'].get('passwordExpirationDate'),
            "request_owner": response_json['data']['user'].get('id'),
            "tokens": tokens_dict,
        }

    async def check_exchange_session(self) -> Dict:
        url = f"https://tms{self.broker_no}.nepsetms.com.np/tmsapi/dnaApi/exchange/sessionCheck"
        _, payload = await self._authenticated_request("GET", url, expected_statuses={200})
        try:
            from utils.market_status import get_market_hours_status, is_market_live, parse_session_check_response

            parsed = parse_session_check_response(payload)
            self.set_market_live_override(is_market_live(get_market_hours_status(), parsed["session_active"]))
        except Exception:
            pass
        return payload

    async def get_order_book(self):
        url = f"https://tms{self.broker_no}.nepsetms.com.np/tmsapi/orderTradeApi/orderbook-v2/client/{self.client_details['id']}?&activeStatus=OPEN&activeStatus=PARTIALLY_TRADED&activeStatus=MODIFIED&activeStatus=PENDING"
        _, payload = await self._authenticated_request("GET", url, expected_statuses={200})
        return payload

    @staticmethod
    def _normalize_order_book_row(row: Dict) -> Dict:
        order_book = row.get("orderBook") if isinstance(row.get("orderBook"), dict) else {}
        extensions = order_book.get("orderBookExtensions") if isinstance(order_book.get("orderBookExtensions"), list) else []
        extension = extensions[0] if extensions and isinstance(extensions[0], dict) else {}

        symbol = TmsUser._order_book_symbol(row)
        exchange_order_id = TmsUser._order_book_exchange_order_id(row)

        return {
            **row,
            "symbol": symbol,
            "script_name": symbol,
            "buyOrSell": row.get("buyOrSell") or order_book.get("buyOrSell"),
            "orderQuantity": row.get("orderQuantity") or extension.get("orderQuantity"),
            "orderPrice": row.get("orderPrice") or extension.get("orderPrice"),
            "orderTime": row.get("orderTime") or row.get("orderPlacedTime") or order_book.get("orderTime"),
            "activeStatus": row.get("activeStatus") or order_book.get("activeStatus"),
            "displayActiveStatus": row.get("displayActiveStatus") or row.get("activeStatus") or order_book.get("activeStatus"),
            "totalTradedQuantity": row.get("totalTradedQuantity") or extension.get("totalTradedQuantity"),
            "remainingOrderQuantity": row.get("remainingOrderQuantity") or extension.get("remainingOrderQuantity"),
            "exchangeOrderId": exchange_order_id,
        }

    async def get_normalized_order_book(self) -> List[Dict]:
        payload = await self.get_order_book()
        return [self._normalize_order_book_row(row) for row in self._order_book_rows(payload)]

    async def get_normalized_daily_order_book(self) -> List[Dict]:
        payload = await self.get_order_history()
        rows = [self._normalize_order_book_row(row) for row in self._order_book_rows(payload)]
        rows.sort(key=lambda row: str(row.get("orderTime") or ""), reverse=True)
        return rows

    @staticmethod
    def _parse_tms_datetime(value) -> Optional[datetime]:
        if value in (None, ""):
            return None
        text = str(value).strip().replace("T", " ")
        if "." in text:
            head, tail = text.split(".", 1)
            digits = "".join(char for char in tail if char.isdigit())[:6]
            text = f"{head}.{digits}" if digits else head
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(text[:26], fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None

    @staticmethod
    def _format_delay(seconds: Optional[float]) -> Optional[str]:
        if seconds is None:
            return None
        sign = "-" if seconds < 0 else ""
        absolute = abs(seconds)
        if absolute < 1:
            return f"{sign}{round(absolute * 1000)} ms"
        return f"{sign}{absolute:.2f} sec"

    async def get_latest_order_timing_for_symbol(
        self,
        symbol: str,
        *,
        order_type: str,
        order_price: float,
        order_quantity: int,
        market_last_traded_time=None,
    ) -> Dict:
        normalized_symbol = str(symbol or "").strip().upper()
        side_code = 1 if str(order_type).lower() == "buy" else 2
        rows: List[Dict] = []
        for loader in (self.get_normalized_order_book, self.get_normalized_daily_order_book):
            try:
                rows.extend(await loader())
            except Exception:
                continue

        candidates = []
        for row in rows:
            if str(row.get("symbol") or "").strip().upper() != normalized_symbol:
                continue
            row_side = row.get("buyOrSell")
            if row_side not in (None, "", side_code, str(side_code)):
                continue
            row_time = self._parse_tms_datetime(row.get("orderTime"))
            if row_time is None:
                continue
            candidates.append(row)

        candidates.sort(
            key=lambda row: self._parse_tms_datetime(row.get("orderTime")) or datetime.min,
            reverse=True,
        )
        matched_order = candidates[0] if candidates else None
        order_time = self._parse_tms_datetime(matched_order.get("orderTime")) if matched_order else None
        market_time = self._parse_tms_datetime(market_last_traded_time)
        delay_seconds = (order_time - market_time).total_seconds() if order_time and market_time else None
        return {
            "symbol": normalized_symbol,
            "market_last_traded_time": str(market_last_traded_time) if market_last_traded_time else None,
            "tms_order_time": matched_order.get("orderTime") if matched_order else None,
            "delay_seconds": delay_seconds,
            "delay_ms": round(delay_seconds * 1000, 3) if delay_seconds is not None else None,
            "delay_display": self._format_delay(delay_seconds),
            "exchange_order_id": matched_order.get("exchangeOrderId") if matched_order else None,
            "order_status": matched_order.get("displayActiveStatus") or matched_order.get("activeStatus") if matched_order else None,
            "order_price": matched_order.get("orderPrice") if matched_order else order_price,
            "order_quantity": matched_order.get("orderQuantity") if matched_order else order_quantity,
            "matched_order": matched_order,
        }

    @staticmethod
    def _order_book_rows(payload) -> List[Dict]:
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, dict)]
        if not isinstance(payload, dict):
            return []
        for key in ("content", "data", "result", "orderBook", "orders", "tradeBookHistory", "tradeBook"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
        return []

    @staticmethod
    def _normalize_tradebook_row(row: Dict) -> Dict:
        normalized = dict(row)
        symbol = str(normalized.get("symbol") or normalized.get("script_name") or "").strip().upper()
        if symbol:
            normalized["symbol"] = symbol
            normalized.setdefault("script_name", symbol)
        return normalized

    @staticmethod
    def _iter_yearly_date_ranges(start: date, end: date) -> Iterator[Tuple[str, str]]:
        current = start
        while current <= end:
            year_end = date(current.year, 12, 31)
            chunk_end = min(year_end, end)
            yield current.isoformat(), chunk_end.isoformat()
            if chunk_end >= end:
                break
            current = date(chunk_end.year + 1, 1, 1)

    @staticmethod
    def _dedupe_tradebook_rows(rows: List[Dict]) -> List[Dict]:
        seen: set = set()
        unique: List[Dict] = []
        for row in rows:
            row_id = row.get("id")
            key = row_id if row_id is not None else (
                f"{row.get('exchangeTradeId')}:{row.get('exchangeOrderId')}"
            )
            if key in seen:
                continue
            seen.add(key)
            unique.append(row)
        return unique

    @staticmethod
    def _tradebook_row_sort_key(row: Dict) -> str:
        return str(row.get("tradeTime") or row.get("trade_time") or "")

    @staticmethod
    def _nested_value(row: Dict, paths: List[List[str]]):
        for path in paths:
            current = row
            for key in path:
                if not isinstance(current, dict) or key not in current:
                    current = None
                    break
                current = current[key]
            if current not in (None, ""):
                return current
        return None

    @classmethod
    def _order_book_symbol(cls, row: Dict) -> str:
        value = cls._nested_value(row, [
            ["symbol"],
            ["script_name"],
            ["securitySymbol"],
            ["security", "symbol"],
            ["orderBook", "security", "symbol"],
        ])
        return str(value or "").strip().upper()

    @classmethod
    def _order_book_exchange_order_id(cls, row: Dict) -> Optional[str]:
        value = cls._nested_value(row, [
            ["exchangeOrderId"],
            ["exchange_order_id"],
            ["orderBook", "exchangeOrderId"],
        ])
        if value in (None, ""):
            return None
        return str(value).strip()

    async def get_open_order_ids_for_symbol(self, symbol: str) -> set[str]:
        normalized_symbol = (symbol or "").strip().upper()
        if not normalized_symbol:
            return set()
        order_book = await self.get_order_book()
        order_ids = set()
        for row in self._order_book_rows(order_book):
            if self._order_book_symbol(row) != normalized_symbol:
                continue
            exchange_order_id = self._order_book_exchange_order_id(row)
            if exchange_order_id:
                order_ids.add(exchange_order_id)
        return order_ids

    async def cancel_open_orders_for_symbol(self, symbol: str, exchange_order_ids: set[str]) -> List[Dict]:
        if not exchange_order_ids:
            return []
        normalized_symbol = (symbol or "").strip().upper()
        order_book = await self.get_order_book()
        results = []
        for row in self._order_book_rows(order_book):
            if self._order_book_symbol(row) != normalized_symbol:
                continue
            exchange_order_id = self._order_book_exchange_order_id(row)
            if not exchange_order_id or exchange_order_id not in exchange_order_ids:
                continue
            try:
                response = await self.cancel_order(exchange_order_id)
                results.append({
                    "exchangeOrderId": exchange_order_id,
                    "status": "cancelled",
                    "response": response,
                })
            except Exception as exc:
                results.append({
                    "exchangeOrderId": exchange_order_id,
                    "status": "failed",
                    "message": str(exc),
                })
        return results

    @staticmethod
    def encode_base64(input_string: str) -> str:
        input_bytes = input_string.encode('utf-8')
        base64_encoded_bytes = base64.b64encode(input_bytes)
        return base64_encoded_bytes.decode('utf-8')

    @staticmethod
    def to_tms_password_payload(password: str) -> str:
        """Accept plain TMS password or an already base64-encoded payload."""
        value = (password or "").strip()
        if not value:
            return value
        if len(value) % 4 == 0 and any(char in value for char in "=+/"):
            try:
                decoded = base64.b64decode(value.encode("utf-8"), validate=True).decode("utf-8")
                if decoded and all(char.isprintable() for char in decoded):
                    return value
            except Exception:
                pass
        return TmsUser.encode_base64(value)

    async def get_user_stock_details(self):
        url = f'https://tms{self.broker_no}.nepsetms.com.np/tmsapi/dp-holding/client/freebalance/{self.client_details["id"]}/CLI'
        _, payload = await self._authenticated_request("GET", url, expected_statuses={200})
        return payload

    @staticmethod
    def calculate_available_collateral(payload: Dict) -> Dict:
        collateral_amount = float(payload.get("collateralAmount") or 0)
        utilized_collateral_amount = float(payload.get("utilizedcollateralAmount") or 0)
        multiplication_factor = float(payload.get("collateralMultiplicationFactor") or 1)
        available_collateral = (collateral_amount * multiplication_factor) - utilized_collateral_amount
        return {
            "collateralAmount": collateral_amount,
            "utilizedcollateralAmount": utilized_collateral_amount,
            "collateralMultiplicationFactor": multiplication_factor,
            "availableCollateral": available_collateral,
        }

    @staticmethod
    def has_collateral_values(payload) -> bool:
        if not isinstance(payload, dict):
            return False
        return any(
            payload.get(key) is not None
            for key in (
                "collateralAmount",
                "utilizedcollateralAmount",
                "collateralMultiplicationFactor",
            )
        )

    async def get_client_collateral(self, *, force_refresh: bool = False):
        if not force_refresh:
            cached = self.get_cached_client_collateral()
            if cached is not None:
                return cached

        url = f'https://tms{self.broker_no}.nepsetms.com.np/tmsapi/dashboard/client/collateral/{self.client_details["id"]}'
        payload = None
        for attempt in range(2):
            _, payload = await self._authenticated_request("GET", url, expected_statuses={200})
            if self.has_collateral_values(payload):
                break
            if attempt == 0:
                await asyncio.sleep(0.5)
        if not self.has_collateral_values(payload):
            raise RuntimeError("Collateral response did not include collateral values")
        collateral = self.calculate_available_collateral(payload or {})
        cache_key = self._collateral_cache_key()
        if cache_key:
            self._collateral_cache[cache_key] = (monotonic_time.monotonic(), collateral)
            save_collateral(cache_key, collateral)
        return collateral

    async def refresh_client_collateral(self) -> Optional[Dict]:
        try:
            return await self.get_client_collateral(force_refresh=True)
        except Exception as exc:
            self.updates.append({
                "status": "warn",
                "message": f"Could not refresh collateral: {exc}",
            })
            return None

    async def get_order_history(self):
        url = f'https://tms{self.broker_no}.nepsetms.com.np/tmsapi/orderTradeApi/orderbook-v2/client/{self.client_details["id"]}?&activeStatus=COMPLETED&activeStatus=CANCELLED&activeStatus=REJECTED&activeStatus=TMS_REJECTED&activeStatus=PARTIALLY_CANCELLED&activeStatus=MODIFIED_CANCELLED'
        _, payload = await self._authenticated_request("GET", url, expected_statuses={200})
        return payload

    async def get_tradebook_history_page(
        self,
        from_date: str,
        to_date: str,
        page_size: int = 10,
        page_no: int = 1,
    ):
        url = (
            f"https://tms{self.broker_no}.nepsetms.com.np/tmsapi/orderTradeApi/"
            f"tradebook-history/client/{self.client_details['id']}"
            f"?fromDate={from_date}&toDate={to_date}&pageSize={page_size}&pageNo={page_no}"
        )
        headers = {
            **self.headers,
            "referer": f"https://tms{self.broker_no}.nepsetms.com.np/tms/me/trade-book-history",
            "membercode": str(self.broker_no),
        }
        last_error: Optional[Exception] = None
        for attempt in range(self.TRADEBOOK_PAGE_RETRIES):
            try:
                _, payload = await self._authenticated_request(
                    "GET",
                    url,
                    headers=headers,
                    expected_statuses={200},
                    timeout=self.TRADEBOOK_TIMEOUT,
                )
                return payload
            except Exception as exc:
                last_error = exc
                if not self._is_transient_request_error(exc) or attempt >= self.TRADEBOOK_PAGE_RETRIES - 1:
                    raise
                await self._recreate_session()
                await asyncio.sleep(min(0.5 * (attempt + 1), 2.0))
        if last_error:
            raise last_error
        raise RuntimeError("tradebook history request failed")

    @staticmethod
    def _merge_tradebook_pages(
        pages: List[List[Dict]],
        page_size: int,
        total_pages: Optional[int] = None,
    ) -> List[Dict]:
        all_rows: List[Dict] = []
        for page_no, rows in enumerate(pages, start=1):
            if not rows:
                break
            all_rows.extend(rows)
            # TMS often returns the full result set in one response even when
            # pageSize is smaller (for example pageSize=10 returning 26 rows).
            if len(rows) > page_size:
                break
            if total_pages is not None and page_no >= int(total_pages):
                break
            if len(rows) < page_size:
                break
        return all_rows

    async def _get_tradebook_history_range(
        self,
        from_date: str,
        to_date: str,
        page_size: int = 10,
    ) -> List[Dict]:
        pages: List[List[Dict]] = []
        page_no = 1
        max_pages = 500
        total_pages: Optional[int] = None

        while page_no <= max_pages:
            payload = await self.get_tradebook_history_page(
                from_date,
                to_date,
                page_size=page_size,
                page_no=page_no,
            )
            rows = self._order_book_rows(payload)
            pages.append(rows)
            if not rows:
                break

            if isinstance(payload, dict):
                total_pages = payload.get("totalPages") or payload.get("total_pages")
                total_elements = payload.get("totalElements") or payload.get("total_elements")
                if total_pages is None and total_elements is not None:
                    total_elements = int(total_elements or 0)
                    total_pages = max(1, (total_elements + page_size - 1) // page_size)

            if len(rows) > page_size:
                break
            if total_pages is not None and page_no >= int(total_pages):
                break
            if len(rows) < page_size:
                break
            page_no += 1

        merged = self._merge_tradebook_pages(pages, page_size, total_pages)
        return [self._normalize_tradebook_row(row) for row in merged]

    async def get_tradebook_history(
        self,
        from_date: str,
        to_date: str,
        page_size: int = 10,
    ) -> List[Dict]:
        start = date.fromisoformat(from_date)
        end = date.fromisoformat(to_date)
        if start > end:
            return []

        if (end - start).days > self.TRADEBOOK_CHUNK_DAYS:
            chunks = list(self._iter_yearly_date_ranges(start, end))
            semaphore = asyncio.Semaphore(self.TRADEBOOK_MAX_CONCURRENT_CHUNKS)

            async def fetch_chunk(chunk_from: str, chunk_to: str) -> List[Dict]:
                async with semaphore:
                    last_error: Optional[Exception] = None
                    for attempt in range(self.TRADEBOOK_PAGE_RETRIES):
                        try:
                            return await self._get_tradebook_history_range(
                                chunk_from,
                                chunk_to,
                                page_size,
                            )
                        except Exception as exc:
                            last_error = exc
                            if not self._is_transient_request_error(exc) or attempt >= self.TRADEBOOK_PAGE_RETRIES - 1:
                                raise
                            await self._recreate_session()
                            await asyncio.sleep(min(0.5 * (attempt + 1), 2.0))
                    if last_error:
                        raise last_error
                    return []

            chunk_results = await asyncio.gather(
                *[fetch_chunk(chunk_from, chunk_to) for chunk_from, chunk_to in chunks]
            )
            merged: List[Dict] = []
            for rows in chunk_results:
                merged.extend(rows)
            merged = self._dedupe_tradebook_rows(merged)
            merged.sort(key=self._tradebook_row_sort_key, reverse=True)
            return merged

        return await self._get_tradebook_history_range(from_date, to_date, page_size)

    async def cancel_order(self, exchange_order_id):
        json_data = {
            'orderBook': None,
            'orderPlacedBy': self.client_details['clientDealerType']['id'],
            'exchangeOrderId': exchange_order_id,
        }
        url = f'https://tms{self.broker_no}.nepsetms.com.np/tmsapi/orderApi/order/cancel/'
        _, payload = await self._authenticated_request("POST", url, json=json_data, expected_statuses={200})
        return payload

    async def order(self, orderPrice, orderQuantity, order_type, security=None):
        if not security:
            security = self.security
        orderPrice = str(orderPrice)
        if order_type.lower() == 'buy':
            buyOrSell = 1
        elif order_type.lower() == 'sell':
            buyOrSell = 2
        else:
            raise ValueError("Invalid order_type. Please use 'buy' or 'sell'.")
        json_data = {
            'orderBook': {
                'orderBookExtensions': [
                    {
                        'orderTypes': {
                            'id': 1,
                            'orderTypeCode': 'LMT',
                        },
                        'disclosedQuantity': 0,
                        'orderValidity': {
                            'id': 1,
                            'orderValidityCode': 'DAY',
                        },
                        'triggerPrice': 0,
                        'orderPrice': orderPrice,
                        'orderQuantity': orderQuantity,
                        'remainingOrderQuantity': 10,
                        'marketType': {
                            'id': 2,
                            'marketType': 'Continuous',
                        },
                    },
                ],
                'exchange': {
                    'id': 1,
                },
                'dnaConnection': {},
                'dealer': {},
                'member': {},
                'productType': {
                    'id': 1,
                    'productCode': 'CNC',
                },
                'instrumentType': {
                    'id': 1,
                    'code': 'EQ',
                },
                'client': {
                    'activeStatus': self.client_details['activeStatus'],
                    'id': self.client_details['id'],
                    'accountType': self.client_details['accountType'],
                    'allowedToTrade': self.client_details['allowedToTrade'],
                    'clientMemberCode': self.client_details['clientMemberCode'],
                    'clientOrDealer': self.client_details['clientOrDealer'],
                    'contactNumber': self.client_details['contactNumber'],
                    'emailId': None,
                    'notsUniqueClientCode': self.client_details['notsUniqueClientCode'],
                    'clientDealerType': None,
                    'clientGroup': {
                        'activeStatus': self.client_details['clientGroup']['activeStatus'],
                        'id': self.client_details['clientGroup']['id'],
                        'clientGroupCode': None,
                        'clientGroupName': None,
                    },
                    'memberBranch': {
                        'activeStatus': 'A',
                        'id': 1,
                        'branchLocation': None,
                        'branchName': None,
                        'hidden': None,
                        'branchProvince': None,
                        'branchDistrict': None,
                        'branchMunicipality': None,
                        'branchHead': None,
                        'branchPhoneNumber': None,
                    },
                    'clientDealerAddressDetails': None,
                    'clientDealerBankDetail': None,
                    'clientDealerIndividual': None,
                    'clientDealerPerTradeLimits': None,
                    'clientDealerProductMappings': None,
                    'clientDealerOrderTypeMappings': None,
                    'clientDealerTradingLimits': None,
                    'clientDepositoryDetail': None,
                    'corporateDetail': None,
                    'corporateOwnershipDetails': None,
                    'displayName': self.client_details['displayName'],
                    'blockedDate': None,
                    'remarks': None,
                    'parentId': None,
                    'recordType': None,
                    'collateralByEntities': None,
                    'shortSellMode': 0,
                    'onlineOrOffline': 1,
                    'panNumber': None,
                    'onlineFundTransfer': None,
                    'collateralCalculationMode': 1,
                    'isMarginLendingClient': None,
                    'clientRiskType': None,
                    'userAgreementChecked': None,
                    'referredBy': None,
                    'responseStatus': None,
                    'marginLendingClient': None,
                },
                'security': {
                    'id': security['id'],
                    'exchangeSecurityId': security['exchangeSecurityId'],
                    'marketProtectionPercentage': 0,
                    'divisor': 100,
                    'boardLotQuantity': 1,
                    'tickSize': 0.1,
                },
                'accountType': 1,
                'cpMemberId': 0,
                'buyOrSell': buyOrSell,
            },
            'orderPlacedBy': 2,
            'exchangeOrderId': None,
        }
        status, payload = await self._authenticated_request(
            "POST",
            f'https://tms{self.broker_no}.nepsetms.com.np/tmsapi/orderApi/order/',
            json=json_data,
            parse_json=False,
        )
        if status == 200:
            return {"status": status, "message": payload}
        try:
            content = json.loads(payload) if payload else {}
            return {"status": status, "message": content}
        except Exception as e:
            return {
                "status": 500,
                "message": f"exception occurred while loading json: {str(e)} {payload}",
            }

    async def _ensure_session(self) -> None:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(keepalive_timeout=60, limit=20),
                timeout=self.DEFAULT_TIMEOUT,
            )

    async def _recreate_session(self) -> None:
        async with self._session_lock:
            if self.session and not self.session.closed:
                await self.session.close()
            self.session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(keepalive_timeout=60, limit=20),
                timeout=self.DEFAULT_TIMEOUT,
            )

    @staticmethod
    def _is_transient_request_error(exc: BaseException) -> bool:
        if isinstance(exc, (aiohttp.ClientError, asyncio.TimeoutError, ConnectionError, OSError)):
            return True
        return "connector is closed" in str(exc).lower()

    @classmethod
    def _get_full_login_lock(cls) -> asyncio.Lock:
        if cls._full_login_lock is None:
            cls._full_login_lock = asyncio.Lock()
        return cls._full_login_lock

    @classmethod
    def set_market_live_override(cls, market_live: bool) -> None:
        cls._market_live_override = (monotonic_time.monotonic(), bool(market_live))
        if market_live:
            cls.clear_non_live_request_cache()

    @classmethod
    def is_non_live_tms_cache_enabled(cls) -> bool:
        from utils.market_status import get_market_hours_status

        hours = get_market_hours_status()
        if not hours["market_hours_open"]:
            return True

        if cls._market_live_override:
            checked_at, market_live = cls._market_live_override
            if monotonic_time.monotonic() - checked_at <= cls._market_live_override_ttl:
                return not market_live

        return False

    @classmethod
    def tms_request_cache_status(cls) -> Dict[str, Any]:
        from utils.market_status import get_market_hours_status

        hours = get_market_hours_status()
        override_live = None
        if cls._market_live_override:
            checked_at, market_live = cls._market_live_override
            if monotonic_time.monotonic() - checked_at <= cls._market_live_override_ttl:
                override_live = market_live

        enabled = cls.is_non_live_tms_cache_enabled()
        if enabled:
            reason = "market_not_live"
        elif hours["market_hours_open"]:
            reason = "market_live_or_unverified_during_market_hours"
        else:
            reason = "disabled"

        return {
            "enabled": enabled,
            "reason": reason,
            "entries": len(cls._non_live_request_cache),
            "ttl_seconds": int(cls._non_live_request_cache_ttl),
            "market_live_override": override_live,
        }

    @classmethod
    def clear_non_live_request_cache(cls) -> None:
        cls._non_live_request_cache.clear()

    @staticmethod
    def _request_cache_value_token(value: Any) -> str:
        if value is None or isinstance(value, (str, int, float, bool)):
            return str(value)
        try:
            return json.dumps(value, sort_keys=True, default=str)
        except Exception:
            return str(value)

    @classmethod
    def _non_live_request_cache_key(cls, method: str, url: str, kwargs: Dict[str, Any]) -> str:
        stable_parts = []
        for key, value in sorted(kwargs.items()):
            if key.lower() in {"headers", "cookies"}:
                continue
            stable_parts.append(f"{key}={cls._request_cache_value_token(value)}")
        return f"{method.upper()} {url} {'&'.join(stable_parts)}"

    @classmethod
    def _get_non_live_cached_request(cls, cache_key: str) -> Optional[tuple[int, object]]:
        cached = cls._non_live_request_cache.get(cache_key)
        if not cached:
            return None
        cached_at, status, payload = cached
        if monotonic_time.monotonic() - cached_at <= cls._non_live_request_cache_ttl:
            return status, payload
        cls._non_live_request_cache.pop(cache_key, None)
        return None

    @classmethod
    def _set_non_live_cached_request(cls, cache_key: str, status: int, payload: object) -> None:
        cls._non_live_request_cache[cache_key] = (monotonic_time.monotonic(), status, payload)

    @classmethod
    def clear_quote_cache(cls, broker_no: Optional[str] = None) -> None:
        if broker_no is None:
            cls._quote_cache.clear()
            cls._quote_failures.clear()
            return
        prefix = f"{normalize_broker_no(str(broker_no))}:"
        cls._quote_cache = {
            key: value for key, value in cls._quote_cache.items()
            if not key.startswith(prefix)
        }
        cls._quote_failures = {
            key: value for key, value in cls._quote_failures.items()
            if not key.startswith(prefix)
        }

    @classmethod
    def _get_cached_quote(cls, key: str, max_age: float) -> Optional[Dict]:
        cached = cls._quote_cache.get(key)
        if not cached:
            return None
        cached_at, quote = cached
        if monotonic_time.monotonic() - cached_at <= max_age:
            return quote
        return None

    @classmethod
    def _quote_circuit_open_seconds(cls, key: str) -> float:
        _, open_until = cls._quote_failures.get(key, (0, 0.0))
        remaining = open_until - monotonic_time.monotonic()
        return remaining if remaining > 0 else 0.0

    @classmethod
    def _record_quote_success(cls, key: str, quote: Dict) -> None:
        cls._quote_cache[key] = (monotonic_time.monotonic(), quote)
        cls._quote_failures.pop(key, None)

    @classmethod
    def _record_quote_failure(cls, key: str) -> None:
        failures, open_until = cls._quote_failures.get(key, (0, 0.0))
        now = monotonic_time.monotonic()
        failures = failures + 1 if open_until <= now else failures
        if failures >= cls._quote_circuit_failure_limit:
            open_until = now + cls._quote_circuit_cooldown
        cls._quote_failures[key] = (failures, open_until)

    async def refresh_auth_token(self) -> bool:
        if not self.tokens or not self.headers:
            return False

        url = f"https://tms{self.broker_no}.nepsetms.com.np/tmsapi/authApi/authenticate/refresh"
        await self._ensure_session()
        async with self.session.post(
            url,
            headers=self.headers,
            cookies=self.tokens,
            json={},
            timeout=self.AUTH_REFRESH_TIMEOUT,
        ) as response:
            try:
                response_json = await response.json(content_type=None)
            except Exception:
                return False

            status = str(response_json.get("status", "")).strip()
            message = str(response_json.get("message", "")).strip()
            success = response.status in (200, 201) and (
                status in {"200", "OK", "0"}
                or "token refreshed" in message.lower()
            )
            if not success:
                return False

            simple_cookie = SimpleCookie(response.cookies)
            for key, morsel in simple_cookie.items():
                self.tokens[key] = morsel.value

            if self.tokens.get("XSRF-TOKEN"):
                self.headers["x-xsrf-token"] = self.tokens["XSRF-TOKEN"]

            if self.login_response:
                self.login_response["tokens"] = dict(self.tokens)
                save_tokens(self.client_id, self.login_response, self.broker_no, update_login_time=False)
            return True

    async def _refresh_authentication(self, reason: str = "access token expired") -> None:
        now = monotonic_time.monotonic()
        if self._auth_refresh_failed_at and now - self._auth_refresh_failed_at < self.AUTH_REFRESH_COOLDOWN_SECONDS:
            raise LoginFailedException("Session refresh is temporarily blocked after a recent failure")
        async with self._auth_refresh_lock:
            now = monotonic_time.monotonic()
            if self._auth_refresh_failed_at and now - self._auth_refresh_failed_at < self.AUTH_REFRESH_COOLDOWN_SECONDS:
                raise LoginFailedException("Session refresh is temporarily blocked after a recent failure")
            self.updates.append({
                "status": "warn",
                "message": "Session expired — refreshing login token and retrying…",
            })
            self.clear_security_cache(str(self.broker_no))
            await self._load_password_from_db()

            if not self.tokens or not self.headers:
                await self._load_session_from_store()

            if await self.refresh_auth_token():
                try:
                    await self._validate_session()
                    await self._persist_logged_in_session(
                        "token refreshed without captcha",
                        update_login_time=False,
                    )
                    self._auth_refresh_failed_at = 0.0
                    return
                except Exception:
                    pass

            if not self._allow_full_login_on_refresh:
                self._auth_refresh_failed_at = monotonic_time.monotonic()
                logout_user(self.client_id, summarize_login_message(reason))
                raise LoginFailedException("TMS token refresh failed; full captcha login skipped")

            try:
                result = await self._full_login_and_persist()
                self._auth_refresh_failed_at = 0.0
                return result
            except Exception as exc:
                self._auth_refresh_failed_at = monotonic_time.monotonic()
                logout_user(self.client_id, summarize_login_message(str(exc) or reason))
                raise

    async def _authenticated_request(
        self,
        method: str,
        url: str,
        *,
        expected_statuses: Optional[set[int]] = None,
        parse_json: bool = True,
        retry_on_unauthorized: bool = True,
        max_connection_retries: int = 3,
        bypass_non_live_cache: bool = False,
        **kwargs,
    ) -> tuple[int, object]:
        explicit_headers = kwargs.pop("headers", None)
        explicit_cookies = kwargs.pop("cookies", None)
        last_error: Optional[Exception] = None
        response = None
        normalized_method = method.upper()
        use_non_live_cache = (
            not bypass_non_live_cache
            and
            normalized_method == "GET"
            and parse_json
            and self.is_non_live_tms_cache_enabled()
        )
        cache_key = self._non_live_request_cache_key(normalized_method, url, kwargs) if use_non_live_cache else None
        if cache_key:
            cached_response = self._get_non_live_cached_request(cache_key)
            if cached_response is not None:
                return cached_response

        for connection_attempt in range(max_connection_retries):
            unauthorized_retried = False
            while True:
                await self._ensure_session()
                request_kwargs = dict(kwargs)
                request_kwargs["headers"] = explicit_headers or self.headers
                request_kwargs["cookies"] = explicit_cookies or self.tokens

                try:
                    async with self._session_lock:
                        await self._ensure_session()
                        response = await self.session.request(normalized_method, url, **request_kwargs)
                        async with response:
                            if response.status == 401 and retry_on_unauthorized and not unauthorized_retried:
                                await response.read()
                                unauthorized_retried = True
                                await self._refresh_authentication(reason=f"{normalized_method} {url} returned 401")
                                break
                            elif expected_statuses and response.status not in expected_statuses:
                                response.raise_for_status()
                            else:
                                if parse_json:
                                    payload = await response.json(content_type=None)
                                else:
                                    payload = await response.text()
                                if cache_key:
                                    self._set_non_live_cached_request(cache_key, response.status, payload)
                                return response.status, payload
                except Exception as exc:
                    if not self._is_transient_request_error(exc):
                        raise
                    last_error = exc
                    if connection_attempt < max_connection_retries - 1:
                        await self._recreate_session()
                        await asyncio.sleep(min(0.25 * (connection_attempt + 1), 1.0))
                        break
                    raise

                break

        if last_error:
            raise last_error
        if response is not None:
            raise aiohttp.ClientResponseError(
                request_info=response.request_info,
                history=response.history,
                status=response.status,
                message=response.reason,
                headers=response.headers,
            )
        raise RuntimeError("authenticated request failed")

    async def get_stock_details_async(
        self,
        id: str,
        max_retries: int = 1,
        *,
        retry_backoff: bool = False,
        force_refresh: bool = False,
    ) -> Optional[Dict]:
        security_id = str(id)
        cache_key = f"{self.broker_no}:{security_id}"
        url = f'https://tms{self.broker_no}.nepsetms.com.np/tmsapi/rtApi/ws/stockQuote/{id}'
        last_error = None
        if not force_refresh:
            cached_quote = self._get_cached_quote(cache_key, self._quote_cache_ttl)
            if cached_quote is not None:
                return cached_quote

        circuit_remaining = self._quote_circuit_open_seconds(cache_key)
        if circuit_remaining > 0:
            if not force_refresh:
                stale_quote = self._get_cached_quote(cache_key, self._quote_stale_ttl)
                if stale_quote is not None:
                    return stale_quote
            self.updates.append({
                "status": "warn",
                "message": f"Price fetch paused for {int(circuit_remaining)}s after repeated TMS quote timeouts.",
            })
            return None

        for attempt in range(max_retries):
            try:
                _, response_data = await self._authenticated_request(
                    "GET",
                    url,
                    expected_statuses={200},
                    timeout=self.QUOTE_TIMEOUT,
                    max_connection_retries=1,
                    bypass_non_live_cache=force_refresh,
                )
                quote = response_data['payload']['data'][0]
                self._record_quote_success(cache_key, quote)
                return quote

            except (aiohttp.ClientError, asyncio.TimeoutError, ConnectionError) as exc:
                last_error = str(exc)
                print(f"Error fetching stock details (attempt {attempt + 1}): {exc}, url={url}")
                self._record_quote_failure(cache_key)

            except Exception as exc:
                last_error = str(exc)
                print(f"Unexpected error fetching stock details: {exc}, url={url}")

            if retry_backoff and attempt < max_retries - 1:
                backoff = min(0.2 * (2 ** attempt), 1.0)
                await asyncio.sleep(backoff)

        if last_error:
            if not force_refresh:
                stale_quote = self._get_cached_quote(cache_key, self._quote_stale_ttl)
                if stale_quote is not None:
                    return stale_quote
            self.updates.append({
                "status": "warn",
                "message": f"Price fetch failed after {max_retries} retries — retrying scan…",
            })
        return None

    async def price_scanner(self, id: str, previous_ltp: float, session_id: str) -> Dict:
        fetch_count = 0
        start_time = asyncio.get_event_loop().time()
        reset_time = 4
        fetch_rate = 0
        consecutive_failures = 0
        max_consecutive_failures = 5
        max_delay = 10.0

        await self._ensure_session()
        last_quote_signature = ""
        socket_fallback_logged = False
        socket_miss_count = 0
        next_socket_restart_at = 0.0
        if self.scan_mode == "socket":
            await live_quote_manager.ensure_stream(
                self,
                self.stock_symbol,
                str(id),
                force_restart=True,
            )

        while True:
            try:
                elapsed_time = asyncio.get_event_loop().time() - start_time
                fetch_rate = fetch_count / elapsed_time if elapsed_time > 0 else 0
                if elapsed_time >= reset_time:
                    start_time = asyncio.get_event_loop().time()
                    fetch_count = 0

                if self.scan_mode == "fixed":
                    response = await self.get_stock_details_async(
                        str(id),
                        max_retries=1,
                        force_refresh=True,
                    )
                    live_snapshot = live_quote_manager.get_snapshot(self.stock_symbol)
                    quote_source = "fixed"
                else:
                    loop_now = asyncio.get_event_loop().time()
                    live_snapshot = await live_quote_manager.wait_for_next_distinct_quote(
                        self.stock_symbol,
                        after_signature=last_quote_signature,
                        timeout=self._stock_grabber_socket_wait_seconds,
                    )
                    socket_state = live_snapshot or live_quote_manager.get_snapshot(self.stock_symbol)
                    if is_live_socket_snapshot(socket_state):
                        response = (socket_state or {}).get("quote")
                        live_snapshot = socket_state
                        quote_source = "socket"
                        socket_miss_count = 0
                        socket_fallback_logged = False
                    else:
                        socket_miss_count += 1
                        if loop_now >= next_socket_restart_at:
                            status = (socket_state or {}).get("status")
                            if status in {"failed", "closed", "auth_failed"}:
                                await live_quote_manager.close_symbol(self.stock_symbol)
                            await live_quote_manager.ensure_stream(
                                self,
                                self.stock_symbol,
                                str(id),
                                force_restart=status in {"failed", "closed"},
                            )
                            next_socket_restart_at = loop_now + 5.0

                        response = await self.get_stock_details_async(
                            str(id),
                            max_retries=1,
                            force_refresh=True,
                        )
                        live_snapshot = socket_state
                        quote_source = "http"
                        if not socket_fallback_logged:
                            socket_status = (socket_state or {}).get("status") or "not_ready"
                            self.updates.append({
                                "status": "warn",
                                "message": (
                                    f"Live socket {socket_status}; using stock quote polling "
                                    "while reconnecting."
                                ),
                                "quote_source": "http",
                                "socket_status": socket_status,
                                "socket_last_received_at": (socket_state or {}).get("last_received_at"),
                                "socket_message_count": (socket_state or {}).get("message_count"),
                            })
                            socket_fallback_logged = True
                self.total_requests += 1
                self.trial_requests += 1

                if response is None:
                    await asyncio.sleep(0.05 if self.scan_mode == "fixed" else 0.1)
                    continue

                if response.get('status') == '401' and response.get('message') == 'ACCESS_TOKEN_EXPIRED':
                    print("Access token expired")
                    self.updates.append(response)
                    return response

                self.success_count += 1
                consecutive_failures = 0
                fetch_count += 1
                self.scan_count += 1
                total_fetch_count = self.scan_count
                last_quote_signature = str((live_snapshot or {}).get("quote_signature") or last_quote_signature)

                ltp = float(response['ltp'])
                percentage_change = float(response['changePercentage'])
                update = {
                    "status": "update",
                    "symbol": response['security']['symbol'],
                    "fetch_rate": fetch_rate,
                    "total_fetch_count": total_fetch_count,
                    "ltp": ltp,
                    "change_percentage": percentage_change,
                    "quote_source": quote_source,
                    "socket_status": (live_snapshot or {}).get("status"),
                    "socket_last_received_at": (live_snapshot or {}).get("last_received_at"),
                    "socket_message_count": (live_snapshot or {}).get("message_count"),
                    "topBuy": response.get("topBuy") or [],
                    "topSell": response.get("topSell") or [],
                    "volume": response.get("volume"),
                    "lastTradedTime": response.get("lastTradedTime"),
                }
                print(f"Symbol: {update['symbol']}, Fetch per second: {fetch_rate}, LTP: {ltp}, Change {percentage_change}")
                self.updates.append(update)

                if total_fetch_count % 15 == 0:
                    self.updates.append({
                        "status": "scanning",
                        "message": f"Still scanning — {total_fetch_count} price checks @ Rs. {ltp}",
                        "ltp": ltp,
                        "total_fetch_count": total_fetch_count,
                        "quote_source": quote_source,
                        "socket_status": (live_snapshot or {}).get("status"),
                        "socket_last_received_at": (live_snapshot or {}).get("last_received_at"),
                    })

                if self.stable_rate is None and self.total_requests >= 10:
                    success_rate = self.success_count / self.total_requests
                    if success_rate >= 0.8:
                        self.request_per_sec = min(self.max_request_per_sec, self.request_per_sec + 0.5)
                        print(f"Fetch rate increased to {self.request_per_sec} due to high success rate")
                        self.stable_cycles += 1
                    else:
                        self.request_per_sec = max(self.min_request_per_sec, self.request_per_sec - 1.0)
                        print(f"Fetch rate decreased to {self.request_per_sec} due to low success rate")
                        self.stable_cycles = 0
                    self.success_count = 0
                    self.total_requests = 0

                    if self.stable_cycles >= 3:
                        self.stable_rate = self.request_per_sec
                        print(f"Stable fetch rate fixed at {self.stable_rate}")
                        self.updates.append({"status": "stable", "rate": self.stable_rate})

                if self.stable_rate is None and self.trial_requests >= 50:
                    self.stable_rate = max(self.min_request_per_sec, self.request_per_sec)
                    print(f"Trial period ended, fixing fetch rate at {self.stable_rate}")
                    self.updates.append({"status": "stable", "rate": self.stable_rate})

                # Only grab when price moves UP from an established baseline (not first tick from 0)
                if previous_ltp > 0 and previous_ltp < ltp:
                    response['fetchDetails'] = {
                        "fetchRate": fetch_rate,
                        "totalFetchCount": total_fetch_count,
                        "ltp": ltp,
                        "script": response['security']['symbol']
                    }
                    two_percent_high = await asyncio.to_thread(calculate_high_price, ltp, percentage_change)
                    print(f"The high price after calculation is {two_percent_high}")
                    response['twoPercentHigh'] = two_percent_high
                    response['ltp'] = ltp
                    response['changePercentage'] = percentage_change
                    response['quote_source'] = quote_source
                    if self.scan_mode == "fixed":
                        response['socket_status'] = (live_snapshot or {}).get("status")
                        response['socket_last_received_at'] = (live_snapshot or {}).get("last_received_at")
                        response['socket_message_count'] = (live_snapshot or {}).get("message_count")
                    self.updates.append(response)
                    return response

                if self.scan_mode == "fixed":
                    await asyncio.sleep(1.0 / max(0.5, float(self.request_per_sec or self.min_request_per_sec)))
                elif quote_source == "http":
                    await asyncio.sleep(1.0 / max(0.5, float(self.request_per_sec or self.min_request_per_sec)))

            except asyncio.CancelledError:
                print(f"Price scanner for session {session_id} cancelled")
                self.updates.append({"status": "stopped", "message": "Price scanner stopped"})
                raise
            except Exception as e:
                print(f"Error in price_scanner: {e}")
                consecutive_failures += 1
                if consecutive_failures >= max_consecutive_failures:
                    consecutive_failures = 0
                    self.updates.append({
                        "status": "warn",
                        "message": f"Scan error ({e}) — retrying",
                    })
                if self.stable_rate is None:
                    self.request_per_sec = max(self.min_request_per_sec, self.request_per_sec - 1.0)
                    print(f"Fetch rate decreased to {self.request_per_sec} due to error")
                delay = min(0.5, max_delay)
                print(f"Request failed, backing off for {delay} seconds")
                self.updates.append({"status": "backoff", "delay": delay})
                await asyncio.sleep(delay)

    async def stock_grabber(
        self,
        order_quantity: int,
        session_id: str,
        max_order_limit: int = 4,
        stop_buy_after_percent: float = NEPSE_INTRADAY_LIMIT_PERCENT,
        stop_buy_after_volume: float = 5000.0,
    ) -> Dict:
        self.order_quantity = order_quantity
        max_order_limit = 4 if not max_order_limit or int(max_order_limit) < 1 else int(max_order_limit)
        configured_stop = (
            NEPSE_INTRADAY_LIMIT_PERCENT
            if stop_buy_after_percent is None
            else float(stop_buy_after_percent)
        )
        stop_buy_after_percent = min(
            NEPSE_INTRADAY_LIMIT_PERCENT,
            max(0, configured_stop),
        )
        self.stop_buy_after_percent = stop_buy_after_percent
        self.stop_buy_after_volume = max(0.0, float(stop_buy_after_volume or 0.0))

        await self._ensure_session()

        resuming = self.scan_count > 0 or self.resume_previous_ltp > 0
        self.updates.append({
            "status": "started",
            "message": (
                f"Resuming {self.stock_symbol} from scan #{self.scan_count}"
                if resuming
                else f"Scanning {self.stock_symbol} — will order at +3% high (max {max_order_limit} orders)"
            ),
        })
        total_orders = []
        order_limit = 0
        previous_ltp = self.resume_previous_ltp
        security_id: Optional[str] = None

        while order_limit < max_order_limit:
            try:
                if security_id is None:
                    self.security = await self.get_security_id(self.stock_symbol)
                    security_id = self.security.get('id') if self.security else None
                    if not security_id:
                        raise RuntimeError(f"Could not resolve security for {self.stock_symbol}")
                    if previous_ltp <= 0:
                        baseline = await self.get_stock_details_async(security_id)
                        if baseline and baseline.get('ltp'):
                            previous_ltp = float(baseline['ltp'])

                stock_details = await self.price_scanner(security_id, previous_ltp, session_id)

                if stock_details.get('message') == 'ACCESS_TOKEN_EXPIRED':
                    self.updates.append({"status": "failed", "message": "Access token expired — login again"})
                    return {"message": "ACCESS_TOKEN_EXPIRED", "totalOrders": []}

                if not stock_details.get('twoPercentHigh'):
                    if stock_details.get('ltp'):
                        previous_ltp = float(stock_details['ltp'])
                    continue

                change_percentage = float(stock_details.get('changePercentage', 0) or 0)
                volume_value_raw = stock_details.get('volume')
                try:
                    volume_value = float(volume_value_raw) if volume_value_raw is not None else None
                except (TypeError, ValueError):
                    volume_value = None

                if volume_value is not None and volume_value > self.stop_buy_after_volume:
                    message = (
                        f"Stopped buying {self.stock_symbol}: volume {volume_value:,.0f} "
                        f"exceeded stop threshold {self.stop_buy_after_volume:,.0f}"
                    )
                    self.updates.append({
                        "status": "completed",
                        "message": message,
                        "total_orders": len(total_orders),
                        "volume": volume_value,
                        "stop_reason": "stop_buy_after_volume",
                    })
                    return {
                        "message": message,
                        "totalOrders": total_orders,
                        "stop_reason": "stop_buy_after_volume",
                    }

                if is_stock_grabber_stop_reached(change_percentage, stop_buy_after_percent):
                    message = (
                        f"Stopped buying {self.stock_symbol}: change {change_percentage}% "
                        f"reached stop threshold {stop_buy_after_percent}%"
                    )
                    self.updates.append({
                        "status": "completed",
                        "message": message,
                        "total_orders": len(total_orders),
                        "change_percentage": change_percentage,
                    })
                    return {
                        "message": message,
                        "totalOrders": total_orders,
                        "stop_reason": "stop_buy_after_percent",
                    }

                order_quantity_to_use = (
                    self.order_quantity
                    if change_percentage <= 7.4
                    else self.final_order_quantity
                )
                target_price = stock_details['twoPercentHigh']
                try:
                    previous_order_ids = await self.get_open_order_ids_for_symbol(self.stock_symbol)
                except Exception as exc:
                    previous_order_ids = set()
                    self.updates.append({
                        "status": "warn",
                        "message": f"Could not read previous {self.stock_symbol} orders before placing: {exc}",
                    })
                await self._ensure_session()
                order_response = await self.order(target_price, order_quantity_to_use, 'buy')
                self.updates.append({
                    "status": "order",
                    "order_status": "success" if order_response.get('status') == 200 else "failed",
                    "order_response": order_response,
                    "order_quantity": order_quantity_to_use,
                    "price": target_price,
                })

                if order_response.get('status') == 200:
                    traded_at = stock_details.get('lastTradedTime')
                    if traded_at:
                        await asyncio.to_thread(log_time, traded_at, self.headers, order_response)
                    delay_details = await self.get_latest_order_timing_for_symbol(
                        self.stock_symbol,
                        order_type="buy",
                        order_price=target_price,
                        order_quantity=order_quantity_to_use,
                        market_last_traded_time=traded_at,
                    )
                    order_response["delay_details"] = delay_details
                    order_limit += 1
                    total_orders.append(order_response)
                    await self.refresh_client_collateral()
                    self.updates.append({
                        "status": "info",
                        "message": f"Order {order_limit}/{max_order_limit} placed at Rs. {target_price}",
                    })
                    self.updates.append({
                        "status": "order_delay",
                        "message": (
                            f"Delayed {delay_details['delay_display']}"
                            if delay_details.get("delay_display")
                            else "Order delay unavailable"
                        ),
                        "delay_details": delay_details,
                    })
                    if previous_order_ids:
                        try:
                            cancel_results = await self.cancel_open_orders_for_symbol(
                                self.stock_symbol,
                                previous_order_ids,
                            )
                        except Exception as exc:
                            cancel_results = []
                            self.updates.append({
                                "status": "warn",
                                "message": f"Could not cancel previous {self.stock_symbol} orders: {exc}",
                            })
                        if cancel_results:
                            cancelled_count = sum(1 for item in cancel_results if item.get("status") == "cancelled")
                            failed_count = len(cancel_results) - cancelled_count
                            self.updates.append({
                                "status": "info" if failed_count == 0 else "warn",
                                "message": (
                                    f"Cancelled {cancelled_count} previous {self.stock_symbol} order(s)"
                                    if failed_count == 0
                                    else (
                                        f"Cancelled {cancelled_count} previous {self.stock_symbol} order(s); "
                                        f"{failed_count} cancellation(s) failed"
                                    )
                                ),
                                "cancelled_orders": cancel_results,
                            })
                    else:
                        self.updates.append({
                            "status": "info",
                            "message": f"No previous open {self.stock_symbol} orders to cancel",
                        })
                else:
                    fail_msg = order_response.get('message', 'unknown error')
                    self.updates.append({
                        "status": "warn",
                        "message": f"Order failed at Rs. {target_price} — {fail_msg}. Resuming scan…",
                    })

                previous_ltp = float(stock_details.get('ltp', previous_ltp))

            except asyncio.CancelledError:
                self.updates.append({"status": "stopped", "message": "Stock grabber stopped"})
                raise
            except Exception as exc:
                print(f"Stock grabber loop error: {exc}")
                self.updates.append({
                    "status": "warn",
                    "message": f"Error during grab cycle ({exc}) — resuming scan…",
                })
                await asyncio.sleep(2)

        if len(total_orders) > 0:
            self.updates.append({
                "status": "completed",
                "message": f"Done — placed {len(total_orders)} order(s) at +3% high",
                "total_orders": len(total_orders),
            })
            return {"message": "successfully ordered shares", "totalOrders": total_orders}

        self.updates.append({
            "status": "scanning",
            "message": "Still scanning — waiting for price to move up",
        })
        return {"message": "scanning", "totalOrders": []}
