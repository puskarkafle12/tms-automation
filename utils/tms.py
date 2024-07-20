import asyncio
import json
import time
from typing import Dict
import aiohttp
import requests

from database import get_db
from exceptions.login_exceptions import LoginFailedException
from models.logged_in_user import LoggedInUsers
from models.user import User
from utils.tms_captcha_solver.imgto_txt import solve_captcha
from utils.base_functions import calculate_high_price, get_tokens, log_time, logout_user, save_tokens

class TmsUser:
    """
    Here's a concise summary of each function in the `TmsUser` class:

1. `__init__`: Initializes a TmsUser instance with provided credentials and configuration.
2. `try_token_login`: Attempts login using stored tokens, falls back to cached login if tokens are invalid.
3. `try_cached_login`: Attempts to login using cached tokens; if unsuccessful, retries with new credentials.
4. `get_captcha_id`: Fetches the captcha ID required for login.
5. `get_captcha_image`: Retrieves the captcha image using the captcha ID.
6. `get_stock_details_async`: Asynchronously fetches stock details, retrying up to three times if necessary.
7. `get_stock_details`: Synchronously fetches stock details, retrying up to three times if necessary.
8. `get_header`: Constructs and returns headers for requests using provided tokens.
9. `get_request_owner`: Retrieves the request owner ID from the server.
10. `get_security_id`: Fetches security details for a given stock symbol.
11. `login_request`: Sends a login request with provided credentials and captcha solution.
12. `get_client_details`: Retrieves client details using cookies, headers, and client dealer ID.
13. `login`: Attempts to login by solving captcha and sending credentials; retries with new captcha if necessary.
14. `order`: Places an order with given price and quantity, including extensive client and security details.
15. `price_scanner`: Continuously scans stock prices, calculates high price, and fetches stock details asynchronously.
16. `stock_grabber`: Manages stock orders, checking price changes, and placing orders based on certain conditions.
17 . get_order_book
"""
    def __init__(self,broker_no, username=None, password=None, tokens=None, expires=None, stock_symbol=None, request_per_sec=2):
       
        self.final_order_quantity = 100
        self.client_id = username
        self.password = password
        self.tokens = tokens
        self.expires = expires
        self.driver = None
        self.session = requests.session()
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

            # self.security = self.get_securities_ids(self.stock_symbol)
    def try_token_login(self):
        if self.tokens and self.expires:
            try:
                self.login_response=self.tokens
                request_owner=self.tokens['request_owner']
                self.tokens=self.tokens['tokens']
                self.headers = self.get_header(request_owner, self.tokens)
                self.client_details = self.get_client_details(self.tokens, self.headers, self.login_response['client_dealer_id'])
            except Exception as e:
                db=get_db()
                user=db.query(User).filter(User.client_id == self.client_id).first()
                if not user:
                    print()
                if user.auto_login:
                    self.password=user.password
                    self.broker_no=user.broker_no
                    try:
                        self.try_cached_login()
                    except Exception as e :
                        logged_in_user=db.query(LoggedInUsers).filter(LoggedInUsers.client_id == self.client_id).first()
                        logged_in_user.status="logged_out"
                        logged_in_user.message="exception while login error message ::"+str(e)
                        db.commit()
                        raise LoginFailedException("login failed "+str(e))
                else:
                    logged_in_user=db.query(LoggedInUsers).filter(LoggedInUsers.client_id == self.client_id).first()
                    logged_in_user.status="logged_out"
                    logged_in_user.message="auto login disabled user token expire re-login again::"+str(e)
                    db.commit()
                    raise LoginFailedException("login failed "+str(e))

    # def cancel_order(self):
    #     json_data = {
    #             'orderBook': None,
    #             'orderPlacedBy': 2,
    #             'exchangeOrderId': '2024031901053235',
    #         }

    #     response = requests.post(
    #                             'https://tms35.nepsetms.com.np/tmsapi/orderApi/order/cancel/',
    #                             cookies=self.tokens,
    #                             headers=self.headers,
    #                             json=json_data
    #                     )
    #     return json.loads(response.content)
    def try_cached_login(self):
        try:
            self.login_response, self.expires ,self.broker_no = get_tokens(self.client_id)
            self.tokens = self.login_response['tokens']
            self.headers = self.get_header(self.login_response['request_owner'], self.tokens)
            self.client_details = self.get_client_details(self.tokens, self.headers, self.login_response['client_dealer_id'])
            return {
                "status": "success",
                "message": "token successfully loaded from the cache file"
            }
        except Exception as e:
            try:
                # retry login from the post request 
                self.login_response = self.login()
                self.tokens = self.login_response['tokens']
                self.expires = self.login_response['expires']
                save_tokens(self.client_id, self.login_response, self.expires,self.broker_no)
                self.headers = self.get_header(self.login_response['request_owner'], self.tokens)
                self.client_details = self.get_client_details(self.tokens, self.headers, self.login_response['client_dealer_id'])
                self.save_login_info()
                return {
                    "status": "success",
                    "message": "token refreshed and stored in the database"
                }
                
            except Exception as e:
                raise LoginFailedException("cannot login "+str(e))

                
    def get_captcha_id(self,headers):
        response = requests.get(f'https://tms{self.broker_no}.nepsetms.com.np/tmsapi/authApi/captcha/id', headers=headers)
        return json.loads(response.content)['id']
    def get_captcha_image(self,headers,captcha_id):
        response = requests.get(f'https://tms{self.broker_no}.nepsetms.com.np/tmsapi/authApi/captcha/image/{captcha_id}', headers=headers)
        return response.content
        
    async def get_stock_details_async(self,session, headers, token, id):
        for attempt in range(3):  # Retry up to 3 times
            try:
                url = f'https://tms{self.broker_no}.nepsetms.com.np/tmsapi/rtApi/ws/stockQuote/{id}'
                async with session.get(url, headers=headers, cookies=token, timeout=5) as responsee:
                    responsee.raise_for_status()
                    response = await responsee.json()
                    return response['payload']['data'][0]
            except aiohttp.ClientError as e:
                print(f"Attempt {attempt + 1} failed: {e}")
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
            except KeyError as e:
                print(f"KeyError: {e}")
                if response.get('message') == 'ACCESS_TOKEN_EXPIRED':
                    return response

        print("Max retries reached, unable to fetch data.")
        return None
    
    def get_stock_details(self, id):
        for attempt in range(3):  # Retry up to 3 times
            try:
                url = f'https://tms{self.broker_no}.nepsetms.com.np/tmsapi/rtApi/ws/stockQuote/{id}'
                with requests.get(url, headers=self.headers, cookies=self.tokens, timeout=5) as response:
                    response.raise_for_status()
                    data = response.json()
                    return data['payload']['data'][0]
            except requests.RequestException as e:
                print(f"Attempt {attempt + 1} failed: {e}")
                time.sleep(2 ** attempt)  # Exponential backoff
            except KeyError as e:
                print(f"KeyError: {e}")
                if data.get('message') == 'ACCESS_TOKEN_EXPIRED':
                    return data

    def get_header(self,request_owner, token):
        header = {
            'authority': f'tms{self.broker_no}.nepsetms.com.np',
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'en-US,en;q=0.9',
            # Requests sorts cookies= alphabetically
            # 'cookie': '_rid='+rid+'; _aid='+aid+'; XSRF-TOKEN='+xsrf_token,
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

    def get_request_owner(self,cookies, headers):
        response = requests.get(
        f'https://tms{self.broker_no}.nepsetms.com.np/tmsapi/exchangeIndex/getExchangeIndexForCurrentUser',
            cookies=cookies,
            headers=headers,
        )
        return json.loads(response.content)['data'][0]['userId']

    
    def get_security_id(self,symbol)->Dict:
        symbol = symbol.upper().strip()
        response = requests.get(
           f'https://tms{self.broker_no}.nepsetms.com.np/tmsapi/stock/securities', cookies=self.tokens, headers=self.headers)
        import json
        stocks = json.loads(response.content)
        if response.status_code==401:
            """
            access token expired
            """
            logout_user(self.client_id,"access token expired")
        for stock in stocks:
            if stock['symbol'] == symbol:
                return stock
        return {}


    def login_request(self,logindata):
        json_data = {
            'userName':logindata['username'] ,
            'password': logindata['password'],
            'jwt': '',
            'otp': '',
            'captchaIdentifier': logindata['captcha_id'],
            'userCaptcha':logindata['captcha'] ,
        }

        response = requests.post(
            f'https://tms{self.broker_no}.nepsetms.com.np/tmsapi/authApi/authenticate',
            # cookies=cookies,
            headers=self.headers,
            json=json_data,
        )
        return response
    def fetch_securities_details(self):
        url = f'https://tms{self.broker_no}.nepsetms.com.np/tmsapi/rtApi/ws/top25securities'
        try:
            response = requests.get(url, headers=self.headers,cookies=self.tokens)
            response.raise_for_status()  # Raise an error for bad status codes
            return response.json()  # Return the response as a JSON object
        except requests.exceptions.RequestException as e:
            return {"error": str(e)}
    def get_client_details(self,cookies, headers, client_dealer_id):
        response = requests.get(
            f'https://tms{self.broker_no}.nepsetms.com.np/tmsapi/clientApi/clientDealer/info/{client_dealer_id}',
            cookies=cookies,
            headers=headers,
        )
        if response.status_code != 200:
            response.raise_for_status()
        return json.loads(response.content)
    def save_login_info(self):
        db=get_db()
        user = db.query(User).filter(User.client_id == self.client_id, User.broker_no ==self.broker_no).first()
        if user:
            if user.password != self.password:
                user.password = self.password
                db.commit()
        else:
            new_user = User(client_id=self.client_id, password=self.password, broker_no=self.broker_no)
            db.add(new_user)
            db.commit()
    def login(self):
        captcha_id=self.get_captcha_id(self.headers)
        binary_captcha_image=self.get_captcha_image(self.headers,captcha_id)
        captcha=solve_captcha(binary_captcha_image)
        login_data={
            "captcha_id":captcha_id,
            "captcha":captcha,
            "username":self.client_id,
            "password":self.password
        }
        response=self.login_request(login_data)
        if json.loads(response.content)['status']=='108':
            max_retries = 5
            for _ in range(max_retries):
                login_data["captcha_id"]=self.get_captcha_id(self.headers)
                binary_captcha_image=self.get_captcha_image(self.headers,login_data["captcha_id"])
                login_data["captcha"]=solve_captcha(binary_captcha_image)
                response = self.login_request(login_data)
                if 'Credentials Not Found' in response.json().get('message'):
                    print('Login failed : invalid username or password', self.client_id)
                    break
                if response.status_code == 200:
                    selected_cookie = next(iter(response.cookies), None)
                    tokens_dict=requests.utils.dict_from_cookiejar(response.cookies)
                    return {
                                        "client_dealer_id":json.loads(response.content)['data']['clientDealerMember']['client']['id'],
                                        "login_response":json.loads(response.content)['data'],
                                        "password_expiry":json.loads(response.content)['data']['user'].get('passwordExpirationDate'),
                                        "request_owner":json.loads(response.content)['data']['user'].get('id'),
                                        "tokens":tokens_dict,
                                        "expires": selected_cookie.expires

                                    }  # Break out of the loop if the status is not '108'
            else:
                print("Maximum number of retries reached.Captcha cannot be solved")
                raise LoginFailedException()

        elif json.loads(response.content)['status']!='202':
            raise LoginFailedException()
        else:
            selected_cookie = next(iter(response.cookies), None)
            tokens_dict=requests.utils.dict_from_cookiejar(response.cookies)
            return {
                                "client_dealer_id":json.loads(response.content)['data']['clientDealerMember']['client']['id'],
                                "login_response":json.loads(response.content)['data'],
                                "password_expiry":json.loads(response.content)['data']['user'].get('passwordExpirationDate'),
                                "request_owner":json.loads(response.content)['data']['user'].get('id'),
                                "tokens":tokens_dict,
                                "expires": selected_cookie.expires

                            }  # Break out of the loop if the status is not '108'
    def get_order_book(self):
        url = f"https://tms{self.broker_no}.nepsetms.com.np/tmsapi/orderTradeApi/orderbook-v2/client/{self.client_details['id']}?&activeStatus=OPEN&activeStatus=PARTIALLY_TRADED&activeStatus=MODIFIED&activeStatus=PENDING"
        
        response = requests.get(url, headers=self.headers, cookies=self.tokens)
        
        if response.status_code == 200:
            return response.json()
        else:
            response.raise_for_status()
    def get_user_stock_details(self):
        response = requests.get(
                                f'https://tms{self.broker_no}.nepsetms.com.np/tmsapi/dp-holding/client/freebalance/{self.client_details["id"]}/CLI',
                                cookies=self.tokens,
                                headers=self.headers,
                            )
        if response.status_code == 200:
            return response.json()
        else:
            response.raise_for_status()

    def get_order_history(self):
        url = f'https://tms{self.broker_no}.nepsetms.com.np/tmsapi/orderTradeApi/orderbook-v2/client/{self.client_details["id"]}?&activeStatus=COMPLETED&activeStatus=CANCELLED&activeStatus=REJECTED&activeStatus=TMS_REJECTED&activeStatus=PARTIALLY_CANCELLED&activeStatus=MODIFIED_CANCELLED'
        
        response = requests.get(url, headers=self.headers, cookies=self.tokens)
        
        if response.status_code == 200:
            return response.json()
        else:
            response.raise_for_status()
    def cancel_order(self, exchange_order_id):
        json_data = {
            'orderBook': None,
            'orderPlacedBy': self.client_details['clientDealerType']['id'],
            'exchangeOrderId': exchange_order_id,
        }

        response = requests.post(
                                f'https://tms{self.broker_no}.nepsetms.com.np/tmsapi/orderApi/order/cancel/',
                                cookies=self.tokens,
                                headers=self.headers,
                                json=json_data
                        )
        return json.loads(response.content)

    def order(self, orderPrice, orderQuantity,order_type, security=None):
        if not security:
            security = self.security
        orderPrice = str(orderPrice)
        # Determine buy or sell based on order_type
        if order_type.lower() == 'buy':
            buyOrSell = 1  # 1 for buy
        elif order_type.lower() == 'sell':
            buyOrSell = 2  # 2 for sell
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
                    # client id
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
                'buyOrSell': buyOrSell,  # Adjusted for buy or sell
            },
            'orderPlacedBy': 2,
            'exchangeOrderId': None,
        }
        response = requests.post(f'https://tms{self.broker_no}.nepsetms.com.np/tmsapi/orderApi/order/',
                                headers=self.headers, cookies=self.tokens, json=json_data)
        if response.status_code == 200:
            return {
                "status": response.status_code,
                "message": str(response.content)}
        else:
            try:
                return {
                    "status": response.status_code,
                    "message": json.loads(response.content)}
            except:
                return {
                    "status": 500,
                    "message": "exception occurred while loading json" + str(response.content)
                }

    async def price_scanner(self,id,previous_ltp):
        """_Returns the stock details along with twoPercentHigh calculated field in dict return by server 

        Args:
            id (_type_): _description_
            previous_ltp (_type_): _description_
            session (_type_): _description_
            headers (_type_): _description_
            token (_type_): _description_
            request_per_sec (_type_): _description_

        Returns:
            DICT: response received from get_stock_details function and add twoPercentHigh key to dict 
        """
        fetch_count = 0
        total_fetch_count = 0
        start_time = time.time()
        reset_time = 4  # Reset the fetch rate counter every 4 seconds
        fetch_rate = 0

        while True:
            time.sleep(1/self.request_per_sec)
            elapsed_time = time.time() - start_time
            fetch_rate = fetch_count / elapsed_time
            if elapsed_time >= reset_time:
                # Reset the fetch rate counter every 4 seconds
                start_time = time.time()
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
            print('LTP:', ltp,'\n')

            # if percentage_change > 9:
            #     print('Price already changed; you missed the chance. Try next day.')
            #     return {'message': 'exit'}
            if previous_ltp < ltp:
                response['fetchDetails'] = {
                    "fetchRate": fetch_rate,
                    "totalFetchCount": total_fetch_count,
                    "ltp": ltp,
                    "script":response['security']['symbol']
                }
                
                two_percent_high = calculate_high_price(ltp,percentage_change)
                print('The high price after calculation is', two_percent_high)
                response['twoPercentHigh'] = two_percent_high
                return response
    def stock_grabber(self, order_quantity,order_limit=0):
        stock_details={}
        total_orders=[]
        self.security=self.get_security_id(self.stock_symbol)
        previous_ltp=previous_ltp=self.get_stock_details(self.security.get('id')).get('ltp')
        while stock_details.get('message') !='exit' and order_limit<4:
            stock_details = asyncio.run(self.price_scanner(self.security['id'], previous_ltp))
            if stock_details.get('message') == 'exit':
                return {"message":"exit"}
            elif stock_details.get('message') == 'ACCESS_TOKEN_EXPIRED':
                # Handle token expiration or refresh here
                return {"message":"ACCESS_TOKEN_EXPIRED"}
            if stock_details['changePercentage']>7.4:
                order_response = self.order(stock_details['twoPercentHigh'], self.final_order_quantity)
            else:
                order_response = self.order(stock_details['twoPercentHigh'], order_quantity)
            if order_response.get('status') == 200:
                log_time(stock_details['lastTradedTime'],self.headers,order_response)
                order_limit+=1
                total_orders.append(order_response)
            else :
                order_response['message']='ordered failed due to '+str(order_response['message'])
                log_time(stock_details['lastTradedTime'],self.headers,order_response)
            # this can make slow change this code 
            previous_ltp=stock_details.get('ltp')
        if len(total_orders)>0:
            return {
                "message":"sucessfully ordered shares",
                "totalOrders":total_orders
            }
            
        