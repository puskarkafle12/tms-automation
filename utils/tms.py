import asyncio
import base64
from datetime import date, datetime, time
from http.cookies import SimpleCookie
import json
import time as monotonic_time
from typing import Dict, List, Optional
import aiohttp
from database import get_db_session
from exceptions.login_exceptions import LoginFailedException
from models.logged_in_user import LoggedInUsers
from models.tms_password_backup import TmsPasswordBackup
from models.user import User
from utils.tms_captcha_solver.imgto_txt import solve_captcha
from utils.base_functions import calculate_high_price, get_tokens, log_time, logout_user, save_tokens

class TmsUser:
    DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=12, connect=4, sock_read=8)
    QUOTE_TIMEOUT = aiohttp.ClientTimeout(total=3, connect=1, sock_read=2)
    _security_cache: Dict[str, tuple[float, List[Dict]]] = {}
    _security_cache_ttl = 300.0

    def __init__(
        self,
        broker_no,
        username=None,
        password=None,
        tokens=None,
        stock_symbol=None,
        request_per_sec=2,
        resume_scan_count=0,
        resume_previous_ltp=0.0,
        resume_stable_rate=None,
    ):
        self.final_order_quantity = 20
        self.order_quantity=10
        self.client_id = username
        self.password = password
        self.tokens = tokens
        self.driver = None
        self.session: Optional[aiohttp.ClientSession] = None
        self._auth_refresh_lock = asyncio.Lock()
        self.security = None
        self.stock_symbol = stock_symbol
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

    async def try_cached_login(self):
        try:
            self.login_response, self.broker_no = get_tokens(self.client_id)  # Assumes get_tokens is async-compatible
            if not self.login_response:
                raise LoginFailedException("No cached TMS session found")
            self.tokens = self.login_response['tokens']
            self.headers = self.get_header(self.login_response['request_owner'], self.tokens)
            rotation_result = await self.rotate_password_if_expired()
            self.client_details = await self.get_client_details(
                self.tokens, self.headers, self.login_response['client_dealer_id']
            )
            if rotation_result.get("rotated"):
                save_tokens(self.client_id, self.login_response, self.broker_no)
                await self.save_login_info()
            return {
                "status": "success",
                "message": rotation_result["message"]
                if rotation_result.get("rotated")
                else "token successfully loaded from the cache file",
                "password_expiry": self.login_response.get("password_expiry"),
                "password_rotated": rotation_result.get("rotated", False),
                "new_password_plain": rotation_result.get("new_password_plain"),
            }
        except Exception as e:
            try:
                self.login_response = await self.login()
                self.tokens = self.login_response['tokens']
                self.headers = self.get_header(self.login_response['request_owner'], self.tokens)
                rotation_result = await self.rotate_password_if_expired()
                save_tokens(self.client_id, self.login_response, self.broker_no)
                self.client_details = await self.get_client_details(
                    self.tokens, self.headers, self.login_response['client_dealer_id']
                )
                await self.save_login_info()
                if rotation_result.get("rotated"):
                    message = rotation_result["message"]
                else:
                    message = "token refreshed and stored in the database"
                return {
                    "status": "success",
                    "message": message,
                    "password_expiry": self.login_response.get("password_expiry"),
                    "password_rotated": rotation_result.get("rotated", False),
                    "new_password_plain": rotation_result.get("new_password_plain"),
                }
            except LoginFailedException:
                raise
            except Exception as e:
                if isinstance(e, LoginFailedException):
                    raise
                raise LoginFailedException(f"Unexpected TMS login error: {e}")

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
        await self._ensure_session()
        async with self.session.get(
            f'https://tms{self.broker_no}.nepsetms.com.np/tmsapi/clientApi/clientDealer/info/{client_dealer_id}',
            cookies=cookies,
            headers=headers,
        ) as response:
            if response.status != 200:
                response.raise_for_status()
            return await response.json()

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
        return payload

    async def get_order_book(self):
        url = f"https://tms{self.broker_no}.nepsetms.com.np/tmsapi/orderTradeApi/orderbook-v2/client/{self.client_details['id']}?&activeStatus=OPEN&activeStatus=PARTIALLY_TRADED&activeStatus=MODIFIED&activeStatus=PENDING"
        _, payload = await self._authenticated_request("GET", url, expected_statuses={200})
        return payload

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

    async def get_order_history(self):
        url = f'https://tms{self.broker_no}.nepsetms.com.np/tmsapi/orderTradeApi/orderbook-v2/client/{self.client_details["id"]}?&activeStatus=COMPLETED&activeStatus=CANCELLED&activeStatus=REJECTED&activeStatus=TMS_REJECTED&activeStatus=PARTIALLY_CANCELLED&activeStatus=MODIFIED_CANCELLED'
        _, payload = await self._authenticated_request("GET", url, expected_statuses={200})
        return payload

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
        if self.session and not self.session.closed:
            await self.session.close()
        self.session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(keepalive_timeout=60, limit=20),
            timeout=self.DEFAULT_TIMEOUT,
        )

    async def _refresh_authentication(self, reason: str = "access token expired") -> None:
        async with self._auth_refresh_lock:
            self.updates.append({
                "status": "warn",
                "message": "Session expired — refreshing login token and retrying…",
            })
            self.clear_security_cache(str(self.broker_no))
            await self.try_cached_login()

    async def _authenticated_request(
        self,
        method: str,
        url: str,
        *,
        expected_statuses: Optional[set[int]] = None,
        parse_json: bool = True,
        retry_on_unauthorized: bool = True,
        **kwargs,
    ) -> tuple[int, object]:
        await self._ensure_session()
        explicit_headers = kwargs.pop("headers", None)
        explicit_cookies = kwargs.pop("cookies", None)

        for attempt in range(2):
            request_kwargs = dict(kwargs)
            request_kwargs["headers"] = explicit_headers or self.headers
            request_kwargs["cookies"] = explicit_cookies or self.tokens

            async with self.session.request(method.upper(), url, **request_kwargs) as response:
                if response.status == 401 and retry_on_unauthorized and attempt == 0:
                    await response.read()
                    await self._refresh_authentication()
                    continue

                if expected_statuses and response.status not in expected_statuses:
                    response.raise_for_status()

                if parse_json:
                    return response.status, await response.json(content_type=None)
                return response.status, await response.text()

        raise aiohttp.ClientResponseError(
            request_info=response.request_info,
            history=response.history,
            status=response.status,
            message=response.reason,
            headers=response.headers,
        )

    async def get_stock_details_async(
        self,
        id: str,
        max_retries: int = 1,
        *,
        retry_backoff: bool = False,
    ) -> Optional[Dict]:
        url = f'https://tms{self.broker_no}.nepsetms.com.np/tmsapi/rtApi/ws/stockQuote/{id}'
        last_error = None

        for attempt in range(max_retries):
            try:
                _, response_data = await self._authenticated_request(
                    "GET",
                    url,
                    expected_statuses={200},
                    timeout=self.QUOTE_TIMEOUT,
                )
                return response_data['payload']['data'][0]

            except (aiohttp.ClientError, asyncio.TimeoutError, ConnectionError) as exc:
                last_error = str(exc)
                print(f"Error fetching stock details (attempt {attempt + 1}): {exc}, url={url}")
                await self._recreate_session()

            except Exception as exc:
                last_error = str(exc)
                print(f"Unexpected error fetching stock details: {exc}, url={url}")

            if retry_backoff and attempt < max_retries - 1:
                backoff = min(0.2 * (2 ** attempt), 1.0)
                await asyncio.sleep(backoff)

        if last_error:
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

        while True:
            try:
                await asyncio.sleep(1 / self.request_per_sec)
                elapsed_time = asyncio.get_event_loop().time() - start_time
                fetch_rate = fetch_count / elapsed_time if elapsed_time > 0 else 0
                if elapsed_time >= reset_time:
                    start_time = asyncio.get_event_loop().time()
                    fetch_count = 0

                response = await self.get_stock_details_async(id, max_retries=1)
                self.total_requests += 1
                self.trial_requests += 1

                if response is None:
                    consecutive_failures += 1
                    if consecutive_failures >= max_consecutive_failures:
                        consecutive_failures = 0
                        self.updates.append({
                            "status": "warn",
                            "message": "Fetch failures — retrying scan",
                        })
                    if self.stable_rate is None:
                        self.request_per_sec = max(self.min_request_per_sec, self.request_per_sec - 1.0)
                        print(f"Fetch rate decreased to {self.request_per_sec} due to failure")
                    delay = min(0.2, max_delay)
                    print(f"Request failed, backing off for {delay} seconds")
                    self.updates.append({"status": "backoff", "delay": delay})
                    await asyncio.sleep(delay)
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

                ltp = float(response['ltp'])
                percentage_change = float(response['changePercentage'])
                update = {
                    "status": "update",
                    "symbol": response['security']['symbol'],
                    "fetch_rate": fetch_rate,
                    "total_fetch_count": total_fetch_count,
                    "ltp": ltp,
                    "change_percentage": percentage_change
                }
                print(f"Symbol: {update['symbol']}, Fetch per second: {fetch_rate}, LTP: {ltp}, Change {percentage_change}")
                self.updates.append(update)

                if total_fetch_count % 15 == 0:
                    self.updates.append({
                        "status": "scanning",
                        "message": f"Still scanning — {total_fetch_count} price checks @ Rs. {ltp}",
                        "ltp": ltp,
                        "total_fetch_count": total_fetch_count,
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
                    self.updates.append(response)
                    return response

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

    async def stock_grabber(self, order_quantity: int, session_id: str, max_order_limit: int = 4) -> Dict:
        self.order_quantity = order_quantity
        max_order_limit = 4 if not max_order_limit or int(max_order_limit) < 1 else int(max_order_limit)

        await self._ensure_session()

        resuming = self.scan_count > 0 or self.resume_previous_ltp > 0
        self.updates.append({
            "status": "started",
            "message": (
                f"Resuming {self.stock_symbol} from scan #{self.scan_count}"
                if resuming
                else f"Scanning {self.stock_symbol} — will order at +2% high (max {max_order_limit} orders)"
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

                order_quantity_to_use = (
                    self.order_quantity
                    if stock_details.get('changePercentage', 0) <= 7.4
                    else self.final_order_quantity
                )
                target_price = stock_details['twoPercentHigh']
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
                    order_limit += 1
                    total_orders.append(order_response)
                    self.updates.append({
                        "status": "info",
                        "message": f"Order {order_limit}/{max_order_limit} placed at Rs. {target_price}",
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
                "message": f"Done — placed {len(total_orders)} order(s) at +2% high",
                "total_orders": len(total_orders),
            })
            return {"message": "successfully ordered shares", "totalOrders": total_orders}

        self.updates.append({
            "status": "scanning",
            "message": "Still scanning — waiting for price to move up",
        })
        return {"message": "scanning", "totalOrders": []}
