import json
from time import sleep, time
import math
from base_functions import get_header, price_scanner
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
request_owner='36320'
url=f'https://tms35.nepsetms.com.np/tmsapi/rtApi/ws/stockQuote/{id}'



        #         global order_flag

        #         if order_flag==1:
        #             f = open("traded_difference.txt", "a")
        #             f.write("\nlast traded time after buy order is : "+lastTradedTime+'\n\n\n')
        #             f.close()
        #             order_flag=0

        #         now = datetime.now()
        #         if changePercentage>9:
        #             print('price already changed you miss the chance try next day')
        #             return 'end'
                    
                

        #         current_time = now.strftime("%H:%M:%S.%f")[:-3]
        #         print("Current Time =", current_time)
        #         stop=datetime.now()
        #         time_taken=stop-start
        #         global fetch_time_taken
        #         fetch_time_taken=stop-fetch_start
        #         print('time taken is:',time_taken)
                

                   
                    
        #         print('fetch per second is ',round(fetch_count/fetch_time_taken.total_seconds(),2),'\n')
        #         print('maxorder limit left',maxorder_limit)
                # if previous_ltp<ltp:
                #     print(f'previous ltp price is : {previous_ltp} new ltp price is : {ltp}')
                #     print('ltp price:',ltp)
                #     previous_ltp=ltp
                #     if maxorder_limit<0:
                #         print('maximum order count limit reached')
                #     else:
                #         lastTradedTime=lastTradedTime[:26]
                #         lastTradedTime= datetime.strptime(lastTradedTime,'%Y-%m-%d %H:%M:%S.%f')
                #         now=datetime.now()
                #         order_delay=(now-lastTradedTime).total_seconds()
                        # if order_delay<25:
                        #     print("delay is less lets order")
                        #     if changePercentage>7.9:
                        #     # server time and last order time left to be substracted
                        #         print("last order is executed with 50 kitta")
                        #         order(high_price,50,exchangeSecurityid,id,token,headers,lastTradedTime)
                        #         break
                        #     else:
                        #         order(high_price,orderQuantity,exchangeSecurityid,id,token,headers,lastTradedTime)
        

                        # else:
                        #     print('delay limit reached order hat ma xaina')


        # except Exception as e:
        #     errorcount=errorcount+1
            
        #     if (responsee.status_code==401):
        #         print('while loop of api broked')
        #         break
        #     print('error exception occured',e)
        #     print('error count:',errorcount)
        # if fetch_time_taken.total_seconds()>=3:
        #     fetch_start=datetime.now()
        #     fetch_count=0
