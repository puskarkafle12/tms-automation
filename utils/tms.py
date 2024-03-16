import asyncio
import json
import time
import aiohttp
import requests

from tms_captcha_solver.imgto_txt import solve_captcha
from utils.base_functions import calculate_high_price, get_tokens, log_time, save_tokens
class LoginFailedException(Exception):
    def __init__(self, message="Login failed. Invalid credentials."):
        self.message = message
        super().__init__(self.message)

class Tms:
    def __init__(self, username, password,stock_symbol,request_per_sec,broker_no):
        self.headers = {
                'authority': 'tms35.nepsetms.com.np',
                'accept': 'application/json, text/plain, */*',
                'accept-language': 'en-US,en;q=0.7',
                'content-type': 'application/json',
                'origin': 'https://tms35.nepsetms.com.np',
                'referer': 'https://tms35.nepsetms.com.np/login',
                'sec-ch-ua': '"Not.A/Brand";v="8", "Chromium";v="114", "Brave";v="114"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"macOS"',
                'sec-fetch-dest': 'empty',
                'sec-fetch-mode': 'cors',
                'sec-fetch-site': 'same-origin',
                'sec-gpc': '1',
                'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
            }
        self.final_order_quantity=100
        self.username = username
        self.password = password
        self.driver = None
        self.session = requests.session()
        self.tokens = None
        self.security = None
        self.stock_symbol=stock_symbol
        self.request_per_sec=request_per_sec
        self.broker_no=broker_no
        self.client_details=None
        self.initialize()
    def initialize(self):
        try:
            # login success from saved tokens  
            self.login_response = get_tokens(self.username)
            self.tokens=self.login_response['tokens']
            self.headers = self.get_header(self.login_response['request_owner'], self.tokens)
            self.client_details=self.get_client_details(self.tokens,self.headers,self.login_response['client_dealer_id'])
            print("token sucessfully loaded from the cache file")
        except Exception as e:
            # retry login from the post request 
            self.login_response = self.login(self.username, self.password)
            self.tokens = self.login_response['tokens']
            save_tokens(self.username,self.login_response)
            self.headers = self.get_header(self.login_response['request_owner'], self.tokens)
            self.client_details=self.get_client_details(self.tokens,self.headers,self.login_response['client_dealer_id'])
        # yesma error huna sakkxa order ma yehi security id jannxa
        self.security = self.get_securities_ids(self.stock_symbol)


    @staticmethod
    def get_captcha_id(headers):
        response = requests.get('https://tms35.nepsetms.com.np/tmsapi/authApi/captcha/id', headers=headers)
        return json.loads(response.content)['id']
    @staticmethod
    def get_captcha_image(headers,captcha_id):
        response = requests.get(f'https://tms35.nepsetms.com.np/tmsapi/authApi/captcha/image/{captcha_id}', headers=headers)
        return response.content
        
    @staticmethod
    async def get_stock_details(session, headers, token, id):
        for attempt in range(3):  # Retry up to 3 times
            try:
                url = f'https://tms35.nepsetms.com.np/tmsapi/rtApi/ws/stockQuote/{id}'
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
                url = f'https://tms35.nepsetms.com.np/tmsapi/rtApi/ws/stockQuote/{id}'
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

    @staticmethod
    def get_header(request_owner, token):
        header = {
            'authority': 'tms35.nepsetms.com.np',
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'en-US,en;q=0.9',
            # Requests sorts cookies= alphabetically
            # 'cookie': '_rid='+rid+'; _aid='+aid+'; XSRF-TOKEN='+xsrf_token,
            'host-session-id': 'TVRJPS1lYWU2MTU0ZS0xODkyLTQxNDEtYTczZS1kMGI1YmM5N2I1YzQ=',
            'referer': 'https://tms35.nepsetms.com.np/tms/me/memberclientorderentry',
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

    @staticmethod
    def get_request_owner(cookies, headers):
        response = requests.get(
            'https://tms35.nepsetms.com.np/tmsapi/exchangeIndex/getExchangeIndexForCurrentUser',
            cookies=cookies,
            headers=headers,
        )
        return json.loads(response.content)['data'][0]['userId']

    
    def get_securities_ids(self,symbol):
        symbol = symbol.upper()
        response = requests.get(
            'https://tms35.nepsetms.com.np/tmsapi/stock/securities', cookies=self.tokens, headers=self.headers)
        import json
        stocks = json.loads(response.content)
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
            'https://tms35.nepsetms.com.np/tmsapi/authApi/authenticate',
            # cookies=cookies,
            headers=self.headers,
            json=json_data,
        )
        return response
    
    @staticmethod
    def get_client_details(cookies, headers, client_dealer_id):
        response = requests.get(
            f'https://tms35.nepsetms.com.np/tmsapi/clientApi/clientDealer/info/{client_dealer_id}',
            cookies=cookies,
            headers=headers,
        )
        if response.status_code != 200:
            response.raise_for_status()
        return json.loads(response.content)

    def login(self,username,password):
        captcha_id=self.get_captcha_id(self.headers)
        binary_captcha_image=self.get_captcha_image(self.headers,captcha_id)
        captcha=solve_captcha(binary_captcha_image)
        login_data={
            "captcha_id":captcha_id,
            "captcha":captcha,
            "username":username,
            "password":password
        }
        response=self.login_request(login_data)
        if json.loads(response.content)['status']=='108':
            max_retries = 5
            for _ in range(max_retries):
                login_data["captcha_id"]=self.get_captcha_id(self.headers)
                binary_captcha_image=self.get_captcha_image(self.headers,login_data["captcha_id"])
                login_data["captcha"]=solve_captcha(binary_captcha_image)
                response = self.login_request(login_data)
                if response.status_code == 200:
                    return {
                                "client_dealer_id":json.loads(response.content)['data']['clientDealerMember']['client']['id'],
                                "login_response":json.loads(response.content)['data'],
                                "password_expiry":json.loads(response.content)['data']['user'].get('passwordExpirationDate'),
                                "request_owner":json.loads(response.content)['data']['user'].get('id'),
                                "tokens":requests.utils.dict_from_cookiejar(response.cookies)
                            }  # Break out of the loop if the status is not '108'
            else:
                print("Maximum number of retries reached.Captcha cannot be solved")

        elif json.loads(response.content)['status']!='202':
            raise LoginFailedException()
        else:
            return {
                "client_dealer_id":json.loads(response.content)['data']['clientDealerMember']['client']['id'],
                "login_response":json.loads(response.content)['data'],
                "password_expiry":json.loads(response.content)['data']['user'].get('passwordExpirationDate'),
                "request_owner":json.loads(response.content)['data']['user'].get('id'),
                "tokens":requests.utils.dict_from_cookiejar(response.cookies)
            }

    def order(self,orderPrice, orderQuantity,security=None):
        if not security:
            security=self.security
        orderPrice = str(orderPrice)
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
                'buyOrSell': 1,
            },
            'orderPlacedBy': 2,
            'exchangeOrderId': None,
        }
        response = requests.post('https://tms35.nepsetms.com.np/tmsapi/orderApi/order/',
                                headers=self.headers, cookies=self.tokens, json=json_data)
        if response.status_code == 200:

            return {
                "status":response.status_code,
                "message":str(response.content)}
        else:
            try:
                return {
                    "status":response.status_code,
                    "message": json.loads(response.content)}
            except:
                return {
                    "status":500 ,
                    "message":"exception occured while loading json"+str(response.content)
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
                    response = await self.get_stock_details(session, self.headers, self.tokens, id)

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
    def stock_grabber(self, order_quantity, previous_ltp,order_limit=0):
        stock_details={}
        total_orders=[]
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
            elif order_response.get('status') == 400:
                order_response['message']='ordered failed due to '+str(order_response['message'])
                log_time(stock_details['lastTradedTime'],self.headers,order_response)
                return order_response
            else:
                return order_response
        if len(total_orders)>0:
            return {
                "message":"sucessfully ordered shares",
                "totalOrders":total_orders
            }