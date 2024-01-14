
from datetime import datetime
import json
import sys
import requests
from requests.exceptions import Timeout
from time import sleep
import math
from requests.exceptions import Timeout
import aiohttp
import asyncio
import time
import os


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


async def price_scanner(id, previous_ltp, session, headers, token, request_per_sec):
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
        time.sleep(1/request_per_sec)
        elapsed_time = time.time() - start_time
        fetch_rate = fetch_count / elapsed_time
        if elapsed_time >= reset_time:
            # Reset the fetch rate counter every 4 seconds
            start_time = time.time()
            fetch_count = 0

        try:
            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(keepalive_timeout=30)) as session:
                response = await get_stock_details(session, headers, token, id)

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


def calculate_high_price(ltp, change_in_percentage):
    if change_in_percentage > 7.843:
        original_price = ltp*100/(change_in_percentage+100)
        ten_percent_change = (original_price * 10/ 100 )+ original_price
        high_price = math.floor(ten_percent_change * 10 ** 1) / 10 ** 1
        return high_price

    high_price = ltp + (2 / 100) * ltp
    # truncating the decimal e.g., 12.343 to 12.3
    high_price = math.floor(high_price * 10 ** 1) / 10 ** 1
    return high_price

# '2023-09-29 19:16:39.806085' to datetime obj


def format_time(time_str):
    # Split the time string into seconds and microseconds parts
    time_parts = time_str.split('.')

    # Handle the seconds part
    seconds = time_parts[0]
    microseconds = 0  # Default value for microseconds

    # If there is a microseconds part, truncate or round it to 6 decimal places
    if len(time_parts) > 1:
        microseconds_str = time_parts[1][:6]  # Limit to 6 decimal places
        microseconds = int(microseconds_str.ljust(6, '0')
                           )  # Ensure it's 6 digits

    # Combine the seconds and microseconds parts
    formatted_time_str = seconds + '.' + str(microseconds).zfill(6)

    # Format the combined time string into a datetime object
    formatted_time = datetime.strptime(
        formatted_time_str, '%Y-%m-%d %H:%M:%S.%f')
    return formatted_time


def get_client_details(cookies, headers, client_dealer_id):
    response = requests.get(
        f'https://tms35.nepsetms.com.np/tmsapi/clientApi/clientDealer/info/{client_dealer_id}',
        cookies=cookies,
        headers=headers,
    )
    if response.status_code != 200:
        response.raise_for_status()
    return json.loads(response.content)


def order(orderPrice, orderQuantity, security, cookies, headers, client_details):
    orderPrice = str(orderPrice)
    # orderPrice = 157
    # data = '{"orderBook":{"orderBookExtensions":[{"orderTypes":{"id":1,"orderTypeCode":"LMT"},"disclosedQuantity":0,"orderValidity":{"id":1,"orderValidityCode":"DAY"},"triggerPrice":0,"orderPrice":'+orderPrice+',"orderQuantity":'+orderQuantity+',"remainingOrderQuantity":10,"marketType":{"id":2,"marketType":"Continuous"}}],"exchange":{"id":1},"dnaConnection":{},"dealer":{},"member":{},"productType":{"id":1,"productCode":"CNC"},"instrumentType":{"id":1,"code":"EQ"},"client":{"activeStatus":"A","id":1974509,"accountType":"CLI","allowedToTrade":"Y","clientMemberCode":"PK479690","clientOrDealer":"C","contactNumber":null,"emailId":null,"notsUniqueClientCode":"201811021236758","clientDealerType":null,"clientGroup":{"activeStatus":"A","id":101,"clientGroupCode":null,"clientGroupName":null},"memberBranch":{"activeStatus":"A","id":1,"branchLocation":null,"branchName":null,"hidden":null,"branchProvince":null,"branchDistrict":null,"branchMunicipality":null,"branchHead":null,"branchPhoneNumber":null},"clientDealerAddressDetails":null,"clientDealerBankDetail":null,"clientDealerIndividual":null,"clientDealerPerTradeLimits":null,"clientDealerProductMappings":null,"clientDealerOrderTypeMappings":null,"clientDealerTradingLimits":null,"clientDepositoryDetail":null,"corporateDetail":null,"corporateOwnershipDetails":null,"displayName":"PUSKAR KAFLE","blockedDate":null,"remarks":null,"parentId":null,"recordType":null,"collateralByEntities":null,"shortSellMode":0,"onlineOrOffline":1,"panNumber":null,"onlineFundTransfer":null,"collateralCalculationMode":1,"isMarginLendingClient":null,"clientRiskType":null,"userAgreementChecked":null,"referredBy":null,"marginLendingClient":null},"security":{"id":'+id+',"exchangeSecurityId":'+exchangeSecurityid+',"marketProtectionPercentage":0,"divisor":100,"boardLotQuantity":1,"tickSize":0.1},"accountType":1,"cpMemberId":0,"buyOrSell":1},"orderPlacedBy":2,"exchangeOrderId":null}'

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
                'activeStatus': client_details['activeStatus'],
                # client id
                'id': client_details['id'],
                'accountType': client_details['accountType'],
                'allowedToTrade': client_details['allowedToTrade'],
                'clientMemberCode': client_details['clientMemberCode'],
                'clientOrDealer': client_details['clientOrDealer'],
                'contactNumber': client_details['contactNumber'],
                'emailId': None,
                'notsUniqueClientCode': client_details['notsUniqueClientCode'],
                'clientDealerType': None,
                'clientGroup': {
                    'activeStatus': client_details['clientGroup']['activeStatus'],
                    'id': client_details['clientGroup']['id'],
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
                'displayName': client_details['displayName'],
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
                             headers=headers, cookies=cookies, json=json_data)
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


def log_time(last_traded_time, headers, response):
    time_server_response = requests.get(
        'https://tms35.nepsetms.com.np/tmsapi/metadata/serverTime', headers=headers)
    time = time_server_response.json()['message'][:26]
    server_time = format_time(time)
    last_traded_time = format_time(last_traded_time)
    f = open("traded_difference.txt", "a")
    f.write("\nserver time and last traded time difference is:" +
            str(server_time-last_traded_time)+' \n response'+str(response))
    f.close()
# Function to save tokens to a JSON file


def save_tokens(username, login_response):
    data = {}
    data[username] = login_response
    with open('tokens.json', 'w') as file:
        json.dump(data, file)

# Function to get tokens for a user


def get_token(username):
    with open('tokens.json', 'r') as file:
        data = json.load(file)
        if username in data:
            return data[username]
        else:
            raise KeyError(f"Token not found for username: {username}")


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


def get_request_owner(cookies, headers):
    response = requests.get(
        'https://tms35.nepsetms.com.np/tmsapi/exchangeIndex/getExchangeIndexForCurrentUser',
        cookies=cookies,
        headers=headers,
    )
    return json.loads(response.content)['data'][0]['userId']


def get_securities_ids(symbol, cookies, headers):
    symbol = symbol.upper()
    response = requests.get(
        'https://tms35.nepsetms.com.np/tmsapi/stock/securities', cookies=cookies, headers=headers)
    import json
    stocks = json.loads(response.content)
    for stock in stocks:
        if stock['symbol'] == symbol:
            return stock
    return {}


def login():
    import requests

    headers = {
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

    json_data = {
        'userName': 'PK479690',
        'password': 'YSViUTdQb25TNlFZR1M=',
        'jwt': '',
        'otp': '',
        'captchaIdentifier': '935779b8-65c5-41ca-9f9a-0facff3bf0d3',
        'userCaptcha': 'v5y8pm',
    }

    response = requests.post(
        'https://tms35.nepsetms.com.np/tmsapi/authApi/authenticate', headers=headers, json=json_data)


def load_users(filename):
    users = []
    current_user = {}

    with open(filename, 'r') as file:
        for line in file:
            line = line.strip()
            if not line:  # Skip empty lines
                continue

            if line == 'end':
                # End of user entry, save it and reset current_user
                if current_user:
                    users.append(current_user)
                    current_user = {}
            else:
                key, value = list(map(lambda x:x.strip(),line.split('=',1)))
                # Remove single quotes from values
                value = value.strip('\'')
                if key == 'broker_no' or key == 'previous_ltp' or key == 'request_per_sec' or key == 'order_quantity':
                    if '.' in value:
                        current_user[key] = float(value)
                    else:
                        current_user[key] = int(value)
                else:
                    current_user[key] = value

    return users


def find_file_in_directory(file_name):
    root_dir = os.path.dirname(os.path.abspath(__file__))
    for foldername, subfolders, filenames in os.walk(root_dir):
        for filename in filenames:
            if filename == file_name:
                return os.path.join(foldername, filename)
    return None  # File not found
