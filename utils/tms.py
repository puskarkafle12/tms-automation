import asyncio
import base64
from datetime import time
from http.cookies import SimpleCookie
import json
from typing import Dict
import aiohttp
from database import get_db
from exceptions.login_exceptions import LoginFailedException
from models.logged_in_user import LoggedInUsers
from models.user import User
from utils.tms_captcha_solver.imgto_txt import solve_captcha
from utils.base_functions import calculate_high_price, get_tokens, log_time, logout_user, save_tokens

class TmsUser:
    def __init__(self, broker_no, username=None, password=None, tokens=None, stock_symbol=None, request_per_sec=2):
        self.final_order_quantity = 100
        self.client_id = username
        self.password = password
        self.tokens = tokens
        self.driver = None
        self.session = aiohttp.ClientSession()
        self.security = None
        self.stock_symbol = stock_symbol
        self.request_per_sec = request_per_sec
        self.broker_no = broker_no
        self.client_details = None
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

    async def close(self):
        if self.session:
            await self.session.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    async def try_token_login(self):
        if self.tokens:
            try:
                self.login_response = self.tokens
                request_owner = self.tokens['request_owner']
                self.tokens = self.tokens['tokens']
                self.headers = self.get_header(request_owner, self.tokens)
                self.client_details = await self.get_client_details(self.tokens, self.headers, self.login_response['client_dealer_id'])
            except Exception as e:
                db = get_db()  # Assumes get_db is async-compatible
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

    async def try_cached_login(self):
        try:
            self.login_response, self.broker_no = get_tokens(self.client_id)  # Assumes get_tokens is async-compatible
            self.tokens = self.login_response['tokens']
            self.headers = self.get_header(self.login_response['request_owner'], self.tokens)
            self.client_details = await self.get_client_details(self.tokens, self.headers, self.login_response['client_dealer_id'])
            return {
                "status": "success",
                "message": "token successfully loaded from the cache file"
            }
        except Exception as e:
            try:
                self.login_response = await self.login()
                self.tokens = self.login_response['tokens']
                save_tokens(self.client_id, self.login_response, self.broker_no)  # Assumes save_tokens is async-compatible
                self.headers = self.get_header(self.login_response['request_owner'], self.tokens)
                self.client_details = await self.get_client_details(self.tokens, self.headers, self.login_response['client_dealer_id'])
                await self.save_login_info()
                return {
                    "status": "success",
                    "message": "token refreshed and stored in the database"
                }
            except Exception as e:
                raise LoginFailedException("cannot login " + str(e))

    async def get_captcha_id(self, headers):
        async with self.session.get(f'https://tms{self.broker_no}.nepsetms.com.np/tmsapi/authApi/captcha/id', headers=headers) as response:
            return (await response.json())['id']

    async def get_captcha_image(self, headers, captcha_id):
        async with self.session.get(f'https://tms{self.broker_no}.nepsetms.com.np/tmsapi/authApi/captcha/image/{captcha_id}', headers=headers) as response:
            return await response.read()

    async def get_stock_details_async(self, session, headers, token, id):
        for attempt in range(3):  # Retry up to 3 times
            try:
                url = f'https://tms{self.broker_no}.nepsetms.com.np/tmsapi/rtApi/ws/stockQuote/{id}'
                async with session.get(url, headers=headers, cookies=token, timeout=5) as response:
                    response.raise_for_status()
                    response_data = await response.json()
                    return response_data['payload']['data'][0]
            except aiohttp.ClientError as e:
                print(f"Attempt {attempt + 1} failed: {e}")
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
            except KeyError as e:
                print(f"KeyError: {e}")
                if response_data.get('message') == 'ACCESS_TOKEN_EXPIRED':
                    return response_data
        print("Max retries reached, unable to fetch data.")
        return None

    async def get_stock_details(self, id):
        for attempt in range(3):  # Retry up to 3 times
            try:
                url = f'https://tms{self.broker_no}.nepsetms.com.np/tmsapi/rtApi/ws/stockQuote/{id}'
                async with self.session.get(url, headers=self.headers, cookies=self.tokens, timeout=5) as response:
                    response.raise_for_status()
                    data = await response.json()
                    return data['payload']['data'][0]
            except aiohttp.ClientError as e:
                print(f"Attempt {attempt + 1} failed: {e}")
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
            except KeyError as e:
                print(f"KeyError: {e}")
                if data.get('message') == 'ACCESS_TOKEN_EXPIRED':
                    return data
        return None

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
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f'https://tms{self.broker_no}.nepsetms.com.np/tmsapi/exchangeIndex/getExchangeIndexForCurrentUser',
                cookies=cookies,
                headers=headers,
            ) as response:
                return json.loads(await response.text())['data'][0]['userId']

    async def get_security_id(self, symbol) -> Dict:
        symbol = symbol.upper().strip()
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f'https://tms{self.broker_no}.nepsetms.com.np/tmsapi/stock/securities',
                cookies=self.tokens,
                headers=self.headers
            ) as response:
                stocks = await response.json()
                if response.status == 401:
                    logout_user(self.client_id, "access token expired")  # Assumes logout_user is async-compatible
                for stock in stocks:
                    if stock['symbol'] == symbol:
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
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f'https://tms{self.broker_no}.nepsetms.com.np/tmsapi/authApi/authenticate',
                headers=self.headers,
                json=json_data,
            ) as response:
                simple_cookie = SimpleCookie(response.cookies)
                tokens_dict = {key: morsel.value for key, morsel in simple_cookie.items()}
                response_data = await response.json()
                return response_data, tokens_dict

    async def fetch_securities_details(self):
        url = f'https://tms{self.broker_no}.nepsetms.com.np/tmsapi/rtApi/ws/top25securities'
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=self.headers, cookies=self.tokens) as response:
                    response.raise_for_status()
                    return await response.json()
            except aiohttp.ClientError as e:
                return {"error": str(e)}

    async def get_client_details(self, cookies, headers, client_dealer_id):
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f'https://tms{self.broker_no}.nepsetms.com.np/tmsapi/clientApi/clientDealer/info/{client_dealer_id}',
                cookies=cookies,
                headers=headers,
            ) as response:
                if response.status != 200:
                    response.raise_for_status()
                return await response.json()

    async def save_login_info(self):
        try:
            db = get_db()  # Assumes get_db is async-compatible
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

        if response_json['status'] == '108':
            for _ in range(5):  # Max retries
                login_data["captcha_id"], login_data["captcha"] = await get_captcha_data()
                response_json, tokens_dict = await self.login_request(login_data)

                if 'Credentials Not Found' in response_json.get('message', ''):
                    print(f'Login failed: invalid username or password {self.client_id}')
                    break
                
                if response_json.get('status') == '202':
                    return self._create_response(response_json, tokens_dict)

            print("Maximum number of retries reached. Captcha cannot be solved")
            raise LoginFailedException()
        
        if response_json['status'] != '202':
            raise LoginFailedException()

        return self._create_response(response_json, tokens_dict)

    def _create_response(self, response_json, tokens_dict):
        return {
            "client_dealer_id": response_json['data']['clientDealerMember']['client']['id'],
            "login_response": response_json['data'],
            "password_expiry": response_json['data']['user'].get('passwordExpirationDate'),
            "request_owner": response_json['data']['user'].get('id'),
            "tokens": tokens_dict,
        }

    async def get_order_book(self):
        url = f"https://tms{self.broker_no}.nepsetms.com.np/tmsapi/orderTradeApi/orderbook-v2/client/{self.client_details['id']}?&activeStatus=OPEN&activeStatus=PARTIALLY_TRADED&activeStatus=MODIFIED&activeStatus=PENDING"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self.headers, cookies=self.tokens) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    response.raise_for_status()

    @staticmethod
    def encode_base64(input_string: str) -> str:
        input_bytes = input_string.encode('utf-8')
        base64_encoded_bytes = base64.b64encode(input_bytes)
        return base64_encoded_bytes.decode('utf-8')

    async def get_user_stock_details(self):
        url = f'https://tms{self.broker_no}.nepsetms.com.np/tmsapi/dp-holding/client/freebalance/{self.client_details["id"]}/CLI'
        async with aiohttp.ClientSession() as session:
            async with session.get(url, cookies=self.tokens, headers=self.headers) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    response.raise_for_status()

    async def get_order_history(self):
        url = f'https://tms{self.broker_no}.nepsetms.com.np/tmsapi/orderTradeApi/orderbook-v2/client/{self.client_details["id"]}?&activeStatus=COMPLETED&activeStatus=CANCELLED&activeStatus=REJECTED&activeStatus=TMS_REJECTED&activeStatus=PARTIALLY_CANCELLED&activeStatus=MODIFIED_CANCELLED'
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self.headers, cookies=self.tokens) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    response.raise_for_status()

    async def cancel_order(self, exchange_order_id):
        json_data = {
            'orderBook': None,
            'orderPlacedBy': self.client_details['clientDealerType']['id'],
            'exchangeOrderId': exchange_order_id,
        }
        url = f'https://tms{self.broker_no}.nepsetms.com.np/tmsapi/orderApi/order/cancel/'
        async with aiohttp.ClientSession() as session:
            async with session.post(url, cookies=self.tokens, headers=self.headers, json=json_data) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    response.raise_for_status()

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
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f'https://tms{self.broker_no}.nepsetms.com.np/tmsapi/orderApi/order/',
                headers=self.headers,
                cookies=self.tokens,
                json=json_data
            ) as response:
                if response.status == 200:
                    return {
                        "status": response.status,
                        "message": await response.text()
                    }
                else:
                    try:
                        content = await response.json()
                        return {
                            "status": response.status,
                            "message": content
                        }
                    except Exception as e:
                        return {
                            "status": 500,
                            "message": f"exception occurred while loading json: {str(e)} {await response.text()}"
                        }

    async def price_scanner(self, id, previous_ltp):
        fetch_count = 0
        total_fetch_count = 0
        start_time = asyncio.get_event_loop().time()
        reset_time = 4  # Reset the fetch rate counter every 4 seconds
        fetch_rate = 0

        while True:
            time.sleep(1 / self.request_per_sec)
            elapsed_time = asyncio.get_event_loop().time() - start_time
            fetch_rate = fetch_count / elapsed_time if elapsed_time > 0 else 0
            if elapsed_time >= reset_time:
                start_time = asyncio.get_event_loop().time()
                fetch_count = 0

            try:
                async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(keepalive_timeout=30)) as session:
                    response = await self.get_stock_details_async(session, self.headers, self.tokens, id)

                if response.get('status'):
                    if response['status'] == '401':
                        if response['message'] == 'ACCESS_TOKEN_EXPIRED':
                            return response
                        continue
                fetch_count += 1
                total_fetch_count += 1
            except Exception as e:
                print(f"Error fetching stock details: {e}")
                continue

            ltp = float(response['ltp'])
            percentage_change = float(response['changePercentage'])
            print(response['security']['symbol'])
            print('Fetch per second:', fetch_rate)
            print('Fetched count:', str(total_fetch_count))
            print('LTP:', ltp, '\n')

            if previous_ltp < ltp:
                response['fetchDetails'] = {
                    "fetchRate": fetch_rate,
                    "totalFetchCount": total_fetch_count,
                    "ltp": ltp,
                    "script": response['security']['symbol']
                }
                two_percent_high = calculate_high_price(ltp, percentage_change)  # Assumes calculate_high_price is async-compatible
                print('The high price after calculation is', two_percent_high)
                response['twoPercentHigh'] = two_percent_high
                return response

    async def stock_grabber(self, order_quantity, order_limit=0):
        stock_details = {}
        total_orders = []
        self.security = await self.get_security_id(self.stock_symbol)
        previous_ltp = (await self.get_stock_details(self.security.get('id'))).get('ltp')
        
        while stock_details.get('message') != 'exit' and order_limit < 4:
            stock_details = await self.price_scanner(self.security['id'], previous_ltp)
            if stock_details.get('message') == 'exit':
                return {"message": "exit"}
            elif stock_details.get('message') == 'ACCESS_TOKEN_EXPIRED':
                return {"message": "ACCESS_TOKEN_EXPIRED"}
            
            if stock_details['changePercentage'] > 7.4:
                order_response = await self.order(stock_details['twoPercentHigh'], self.final_order_quantity, 'buy')
            else:
                order_response = await self.order(stock_details['twoPercentHigh'], order_quantity, 'buy')
            
            if order_response.get('status') == 200:
                log_time(stock_details['lastTradedTime'], self.headers, order_response)  # Assumes log_time is async-compatible
                order_limit += 1
                total_orders.append(order_response)
            else:
                order_response['message'] = f'order failed due to {str(order_response["message"])}'
                log_time(stock_details['lastTradedTime'], self.headers, order_response)
            
            previous_ltp = stock_details.get('ltp')
        
        if len(total_orders) > 0:
            return {
                "message": "successfully ordered shares",
                "totalOrders": total_orders
            }
        return {"message": "no orders placed"}