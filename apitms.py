import json
from time import sleep, time
import math
import requests
from requests.api import head
from requests.exceptions import Timeout
from datetime import datetime

orderPrice=440
orderQuantity=10
exchangeSecurityid=8021
id=2912
# set maximum order limit 
maxorder_limit=4
# 8021 sahas


errorcount=0
timeout_count=0
timeout_count1=0
count=0
order_flag=0


url=f'https://tms35.nepsetms.com.np/tmsapi/rtApi/ws/stockQuote/{id}'
# print(url)
ref_url='https://tms35.nepsetms.com.np/tms/me/memberclientorderentry'
request_owner='36320'

# url='https://tms56.nepsetms.com.np/tmsapi/rtApi/ws/stockQuote/2888'
# ref_url='https://tms56.nepsetms.com.np/tms/me/memberclientorderentry'
# request_owner='65884'

def fetchprice(xsrf_token,aid,rid,previous_ltp):
    global order_flag
    global ordercount
    start=datetime.now()
    global orderPrice,orderQuantity,exchangeSecurityid,id
    global errorcount
    global timeout_count
    global timeout_count1
    cookies = {
        'XSRF-TOKEN': xsrf_token,
        '_aid': aid,
        '_rid': rid
        }

    headers = {
        'Connection': 'keep-alive',
        'sec-ch-ua': '" Not;A Brand";v="99", "Google Chrome";v="91", "Chromium";v="91"',
        'Accept': 'application/json, text/plain, */*',
        'X-XSRF-TOKEN': xsrf_token,
        'Request-Owner': request_owner,
        'Content-Type': 'application/json',
        'sec-ch-ua-mobile': '?0',
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.164 Safari/537.36',
        'Host-Session-Id': 'TWpRPS0yZjg4ZmIzNC1jZDQ4LTQwZTMtODdiNy0xNGFkNzMwZDEwYTk=',
        'Origin': 'https://tms35.nepsetms.com.np',
        'Sec-Fetch-Site': 'same-origin',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Dest': 'empty',
        'Referer': ref_url,
        'Accept-Language': 'en-US,en;q=0.9',
    }



    # ZFc1a1pXWnBibVZrLTg3MzEwNmYzLTIzZmItNDk3OC1iZGMwLWQwODlhZGYyM2M4Yg==
    # Host-Session-Id: TVRJPS1jNjk2NDE5Ni1lMDcyLTQ1NzgtYmY4Ny0yZjUzOGY3NGJjZTc=

    # response = requests.get('https://tms56.nepsetms.com.np/tmsapi/rtApi/ws/stockQuote/2888', headers=headers, cookies=cookies).json()
    # previous_ltp=int(response['payload']['data'][0]['ltp'])
    # print (response)
    # ltp=int(previous_ltp)
    
    session=requests.session()
    fetch_start=datetime.now()
    fetch_count=1
    while(1):
       
        
        sleep(1)
        
        
        try:
                try:
                    responsee = session.get(url, headers=headers, cookies=cookies,timeout=1)
                    try:
                        response=responsee.json()
                    except Exception as e:
                        print('exception occured ',e)
                except Timeout:
                    timeout_count=timeout_count+1
                    timeout_count1=timeout_count1+1
                    print('The request timeout:',timeout_count1)

                
                
                ltp=float(response['payload']['data'][0]['ltp'])
                
                high_price=ltp+2/100*ltp
                high_price=math.floor(high_price * 10 ** 1) / 10 ** 1
                print('the high price after calc is ',high_price)
                changePercentage=float(response['payload']['data'][0]['changePercentage'])
                lastTradedTime=response['payload']['data'][0]['lastTradedTime']
                id=int(response['payload']['data'][0]['security']['id'])
                print('ltp price :',ltp,"id: ",id)
                print("last traded time is",lastTradedTime)
                print("change in percent is",changePercentage)
                global count
                count=count+1-timeout_count
                fetch_count=fetch_count+1
                timeout_count=0
                print('fetched count:',count)


                if order_flag==1:
                    f = open("traded_difference.txt", "a")
                    f.write("\nlast traded time after buy order is : "+lastTradedTime+'\n\n\n')
                    f.close()
                    order_flag=0

                now = datetime.now()
                if changePercentage>9:
                    print('price already changed you miss the chance try next day')
                    return 'end'
                    
                

                current_time = now.strftime("%H:%M:%S.%f")[:-3]
                print("Current Time =", current_time)
                stop=datetime.now()
                time_taken=stop-start
                fetch_time_taken=stop-fetch_start
                print('time taken is:',time_taken)
                

                   
                    
                print('fetch per second is ',round(fetch_count/fetch_time_taken.total_seconds(),2),'\n')
                print('maxorder limit left',maxorder_limit)
                # if ordercount==0:
                #     ordercount=1
                if previous_ltp<ltp:
                    print(f'previous ltp price is : {previous_ltp} new ltp price is : {ltp}')
                    print('ltp price:',ltp)
                    previous_ltp=ltp
                    if maxorder_limit<0:
                        print('maximum order count limit reached')
                    else:
                        lastTradedTime=lastTradedTime[:26]
                        lastTradedTime= datetime.strptime(lastTradedTime,'%Y-%m-%d %H:%M:%S.%f')
                        now=datetime.now()
                        order_delay=(now-lastTradedTime).total_seconds()
                        if order_delay<25:
                            print("delay is less lets order")
                            if changePercentage>7.9:
                            # server time and last order time left to be substracted
                                print("last order is executed with 50 kitta")
                                order(high_price,50,exchangeSecurityid,id,cookies,headers,lastTradedTime)
                                break
                            else:
                                order(high_price,orderQuantity,exchangeSecurityid,id,cookies,headers,lastTradedTime)
        

                        else:
                            print('delay limit reached order hat ma xaina')


                    

                # this function should be called for ordering when price changes
                    # order(orderPrice,orderQuantity,exchangeSecurityid,id,cookies,headers)

                
                    
                
        except Exception as e:
            errorcount=errorcount+1
            
            if (responsee.status_code==401):
                print('while loop of api broked')
                break
            print('error exception occured',e)
            print('error count:',errorcount)
        if fetch_time_taken.total_seconds()>=3:
            fetch_start=datetime.now()
            fetch_count=0
            
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
    
        


# order(orderPrice,orderQuantity,exchangeSecurityid,id,cookies,headers)
# ,"userAgreementChecked":null,"referredBy":null,"marginLendingClient":null this added in post data client risk type null
# averageTradedPrice: 439.82
# change: 40.5
# changePercentage: 9.99259807549963
# closePrice: 405.3
# dayHigh: 445.8
# dayLow: 405.3
# lastTradedQty: 10
# lastTradedTime: "2021-10-31 14:10:11.302921000"
# ltp: 445.8
# openPrice: 405.3
