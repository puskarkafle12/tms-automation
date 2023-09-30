    
from datetime import datetime
import json
import requests
from requests.exceptions import Timeout
from time import sleep
import math
from requests.exceptions import Timeout
def get_stock_details(session,headers,token,id):
    url=f'https://tms35.nepsetms.com.np/tmsapi/rtApi/ws/stockQuote/{id}'
    responsee = session.get(url, headers=headers, cookies=token,timeout=5)
    response=responsee.json()
    try:
        return response['payload']['data'][0]
    except KeyError:
        if response['message']=='ACCESS_TOKEN_EXPIRED':
            return response
import time

def price_scanner(id, previous_ltp, session, headers, token, request_per_sec):
    fetch_count = 0
    total_fetch_count=0
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
            response = get_stock_details(session, headers, token, id)
            if response.get('status'):
                if response['status'] == '401':
                    if response['message'] == 'ACCESS_TOKEN_EXPIRED':
                        return response
                    continue
            fetch_count += 1
            total_fetch_count+=1
        except Exception as e:
            print(f"Error fetching stock details: {e}")
            continue

        ltp = float(response['ltp'])
        percentage_change = float(response['changePercentage'])
        print('Fetch per second:', fetch_rate)
        print('Fetched count:', total_fetch_count)
        print('LTP:', ltp,'\n')

        if percentage_change > 9:
            print('Price already changed; you missed the chance. Try next day.')
            return {'message': 'exit'}  # Return None to indicate that the condition was met

        if previous_ltp < ltp:
            two_percent_high = calculate_high_price(ltp)
            print('The high price after calculation is', two_percent_high)
            response['twoPercentHigh'] = two_percent_high
            return response
   
def calculate_high_price(ltp):
    high_price = ltp + (2 / 100) * ltp
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
        microseconds = int(microseconds_str.ljust(6, '0'))  # Ensure it's 6 digits
    
    # Combine the seconds and microseconds parts
    formatted_time_str = seconds + '.' + str(microseconds).zfill(6)
    
    # Format the combined time string into a datetime object
    formatted_time = datetime.strptime(formatted_time_str, '%Y-%m-%d %H:%M:%S.%f')
    
    return formatted_time
def order(orderPrice,orderQuantity,exchangeSecurityid,id,cookies,headers):
    global order_flag
    global maxorder_limit

    orderPrice=str(orderPrice)
    orderQuantity=str(orderQuantity)
    exchangeSecurityid=str(exchangeSecurityid)
    id=str(id)
    data = '{"orderBook":{"orderBookExtensions":[{"orderTypes":{"id":1,"orderTypeCode":"LMT"},"disclosedQuantity":0,"orderValidity":{"id":1,"orderValidityCode":"DAY"},"triggerPrice":0,"orderPrice":'+orderPrice+',"orderQuantity":'+orderQuantity+',"remainingOrderQuantity":10,"marketType":{"id":2,"marketType":"Continuous"}}],"exchange":{"id":1},"dnaConnection":{},"dealer":{},"member":{},"productType":{"id":1,"productCode":"CNC"},"instrumentType":{"id":1,"code":"EQ"},"client":{"activeStatus":"A","id":1974509,"accountType":"CLI","allowedToTrade":"Y","clientMemberCode":"PK479690","clientOrDealer":"C","contactNumber":null,"emailId":null,"notsUniqueClientCode":"201811021236758","clientDealerType":null,"clientGroup":{"activeStatus":"A","id":101,"clientGroupCode":null,"clientGroupName":null},"memberBranch":{"activeStatus":"A","id":1,"branchLocation":null,"branchName":null,"hidden":null,"branchProvince":null,"branchDistrict":null,"branchMunicipality":null,"branchHead":null,"branchPhoneNumber":null},"clientDealerAddressDetails":null,"clientDealerBankDetail":null,"clientDealerIndividual":null,"clientDealerPerTradeLimits":null,"clientDealerProductMappings":null,"clientDealerOrderTypeMappings":null,"clientDealerTradingLimits":null,"clientDepositoryDetail":null,"corporateDetail":null,"corporateOwnershipDetails":null,"displayName":"PUSKAR KAFLE","blockedDate":null,"remarks":null,"parentId":null,"recordType":null,"collateralByEntities":null,"shortSellMode":0,"onlineOrOffline":1,"panNumber":null,"onlineFundTransfer":null,"collateralCalculationMode":1,"isMarginLendingClient":null,"clientRiskType":null,"userAgreementChecked":null,"referredBy":null,"marginLendingClient":null},"security":{"id":'+id+',"exchangeSecurityId":'+exchangeSecurityid+',"marketProtectionPercentage":0,"divisor":100,"boardLotQuantity":1,"tickSize":0.1},"accountType":1,"cpMemberId":0,"buyOrSell":1},"orderPlacedBy":2,"exchangeOrderId":null}'
    response = requests.post('https://tms35.nepsetms.com.np/tmsapi/orderApi/orderbook-v2/', headers=headers, cookies=cookies, data=data)
    order_flag=1
    if response.status_code==200:
        return json.loads(response.content)
    else:
        return json.loads(response.content)
def time_logger(lastTradedTime,headers,):
    time_server_response = requests.get('https://tms35.nepsetms.com.np/tmsapi/metadata/serverTime',headers=headers)
    time=time_server_response.json()['message'][:26]
    server_time = format_time(time)
    lastTradedTime = format_time(lastTradedTime)
    f = open("traded_difference.txt", "a")
    f.write("\n\nserver time and last traded time difference is:"+str(server_time-lastTradedTime)+' \n response'+json.dumps(response.json()))
    f.close()
# Function to save tokens to a JSON file
def save_tokens(username, tokens):
    data={}
    data[username] = tokens

    with open('tokens.json', 'w') as file:
        json.dump(data, file)

# Function to get tokens for a user
def get_token(username, driver,refresh=False):
    try:
        with open('tokens.json', 'r') as file:
            data = json.load(file)
            if username in data and not refresh:
                return data[username]
    except FileNotFoundError:
        pass
    except json.JSONDecodeError:
        pass

    # If tokens are not found, generate them and save them
    cookies = driver.get_cookies()
    tokens = {
        'XSRF-TOKEN': cookies[1]['value'],
        '_aid': cookies[0]['value'],
        '_rid': cookies[2]['value']
    }
    save_tokens(username, tokens)
    return tokens

def get_header(request_owner,token):
    header = {
        'authority': 'tms35.nepsetms.com.np',
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'en-US,en;q=0.9',
        # Requests sorts cookies= alphabetically
        # 'cookie': '_rid='+rid+'; _aid='+aid+'; XSRF-TOKEN='+xsrf_token,
        'host-session-id': 'TVRJPS1lYWU2MTU0ZS0xODkyLTQxNDEtYTczZS1kMGI1YmM5N2I1YzQ=',
        'referer': 'https://tms35.nepsetms.com.np/tms/me/memberclientorderentry',
        'request-owner': request_owner,
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

def get_request_owner(cookies,headers):
    response = requests.get(
    'https://tms35.nepsetms.com.np/tmsapi/exchangeIndex/getExchangeIndexForCurrentUser',
    cookies=cookies,
    headers=headers,
)
    return json.loads(response.content)['data'][0]['userId']
def get_securities_ids(symbol,cookies,headers):
    symbol=symbol.upper()
    response = requests.get('https://tms35.nepsetms.com.np/tmsapi/stock/securities', cookies=cookies, headers=headers)
    import json
    stocks=json.loads(response.content)
    for stock in stocks:
        if stock['symbol'] ==symbol:
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

    response = requests.post('https://tms35.nepsetms.com.np/tmsapi/authApi/authenticate', headers=headers, json=json_data)
