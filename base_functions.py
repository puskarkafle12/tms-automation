    
import datetime
import json
import requests
from requests.exceptions import Timeout
from time import sleep
import math
from requests.exceptions import Timeout
def get_stock_details(session,headers,token,id):
    url=f'https://tms35.nepsetms.com.np/tmsapi/rtApi/ws/stockQuote/{id}'
    responsee = session.get(url, headers=headers, cookies=token,timeout=1)
    response=responsee.json()
    return response['payload']['data'][0]
def price_scanner(id,previous_ltp, session, headers, token):
    fetch_count = 0
    while True:
        sleep(0.5)
        try:
            response = get_stock_details(session, headers, token,id)
            fetch_count += 1
        except Exception as e:
            print(f"Error fetching stock details: {e}")
            continue

        ltp = float(response['ltp'])
        percentage_change = float(response['changePercentage'])
        print('Fetched count:', fetch_count)
        print('LTP:', ltp,'\n')

        if percentage_change > 9:
            print('Price already changed; you missed the chance. Try next day.')
            return None  # Return None to indicate that the condition was met

        if previous_ltp < ltp:
            two_percent_high=calculate_high_price(ltp)
            print('The high price after calculation is', two_percent_high)
            response['two_percent_high'] = two_percent_high
            return response  
        
def calculate_high_price(ltp):
    high_price = ltp + (2 / 100) * ltp
    high_price = math.floor(high_price * 10 ** 1) / 10 ** 1
    return high_price

 
def order(orderPrice,orderQuantity,exchangeSecurityid,id,cookies,headers,lastTradedTime):
    global order_flag
    global maxorder_limit

    orderPrice=str(orderPrice)
    orderQuantity=str(orderQuantity)
    exchangeSecurityid=str(exchangeSecurityid)
    id=str(id)

    data = '{"orderBook":{"orderBookExtensions":[{"orderTypes":{"id":1,"orderTypeCode":"LMT"},"disclosedQuantity":0,"orderValidity":{"id":1,"orderValidityCode":"DAY"},"triggerPrice":0,"orderPrice":'+orderPrice+',"orderQuantity":'+orderQuantity+',"remainingOrderQuantity":10,"marketType":{"id":2,"marketType":"Continuous"}}],"exchange":{"id":1},"dnaConnection":{},"dealer":{},"member":{},"productType":{"id":1,"productCode":"CNC"},"instrumentType":{"id":1,"code":"EQ"},"client":{"activeStatus":"A","id":1974509,"accountType":"CLI","allowedToTrade":"Y","clientMemberCode":"PK479690","clientOrDealer":"C","contactNumber":null,"emailId":null,"notsUniqueClientCode":"201811021236758","clientDealerType":null,"clientGroup":{"activeStatus":"A","id":101,"clientGroupCode":null,"clientGroupName":null},"memberBranch":{"activeStatus":"A","id":1,"branchLocation":null,"branchName":null,"hidden":null,"branchProvince":null,"branchDistrict":null,"branchMunicipality":null,"branchHead":null,"branchPhoneNumber":null},"clientDealerAddressDetails":null,"clientDealerBankDetail":null,"clientDealerIndividual":null,"clientDealerPerTradeLimits":null,"clientDealerProductMappings":null,"clientDealerOrderTypeMappings":null,"clientDealerTradingLimits":null,"clientDepositoryDetail":null,"corporateDetail":null,"corporateOwnershipDetails":null,"displayName":"PUSKAR KAFLE","blockedDate":null,"remarks":null,"parentId":null,"recordType":null,"collateralByEntities":null,"shortSellMode":0,"onlineOrOffline":1,"panNumber":null,"onlineFundTransfer":null,"collateralCalculationMode":1,"isMarginLendingClient":null,"clientRiskType":null,"userAgreementChecked":null,"referredBy":null,"marginLendingClient":null},"security":{"id":'+id+',"exchangeSecurityId":'+exchangeSecurityid+',"marketProtectionPercentage":0,"divisor":100,"boardLotQuantity":1,"tickSize":0.1},"accountType":1,"cpMemberId":0,"buyOrSell":1},"orderPlacedBy":2,"exchangeOrderId":null}'
    # print(data)
    response = requests.post('https://tms35.nepsetms.com.np/tmsapi/orderApi/orderbook-v2/', headers=headers, cookies=cookies, data=data)

    time_server_response = requests.get('https://tms35.nepsetms.com.np/tmsapi/metadata/serverTime',headers=headers)
    time=time_server_response.json()['message'][:26]
    server_time = datetime.strptime(time,'%Y-%m-%d %H:%M:%S.%f')
    f = open("traded_difference.txt", "a")
    print("server time and last traded time difference is:"+str(server_time-lastTradedTime))
    f.write("server time and last traded time difference is:"+str(server_time-lastTradedTime)+' \n response'+json.dumps(response.json()))
    f.close()
    order_flag=1

    if response.status_code==200:
        maxorder_limit=maxorder_limit-1
        print(response.status_code)
        print(response.status_code,response.json())
        return response.status_code

         
    else:
        print('post failed')
        print(response.status_code,response.json())
        return response.status_code
    
# Function to save tokens to a JSON file
def save_tokens(username, tokens):
    data={}
    data[username] = tokens

    with open('tokens.json', 'a') as file:
        json.dump(data, file)

# Function to get tokens for a user
def get_token(username, driver):
    try:
        with open('tokens.json', 'r') as file:
            data = json.load(file)
            if username in data:
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