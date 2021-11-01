
headers = {
        'Connection': 'keep-alive',
        'sec-ch-ua': '" Not;A Brand";v="99", "Google Chrome";v="91", "Chromium";v="91"',
        'Accept': 'application/json, text/plain, */*',
        # 'X-XSRF-TOKEN': xsrf_token,
        # 'Request-Owner': request_owner,
        'Content-Type': 'application/json',
        'sec-ch-ua-mobile': '?0',
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.164 Safari/537.36',
        'Host-Session-Id': 'TWpRPS0yZjg4ZmIzNC1jZDQ4LTQwZTMtODdiNy0xNGFkNzMwZDEwYTk=',
        'Origin': 'https://tms35.nepsetms.com.np',
        'Sec-Fetch-Site': 'same-origin',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Dest': 'empty',
        # 'Referer': ref_url,
        'Accept-Language': 'en-US,en;q=0.9',
    }
import requests
from datetime import date, datetime




lastTradedTime='2021-10-31 14:51:11.988924000'
lastTradedTime=lastTradedTime[:26]
lastTradedTime= datetime.strptime(lastTradedTime,'%Y-%m-%d %H:%M:%S.%f')
now=datetime.now()
order_delay=(now-lastTradedTime).total_seconds()
if order_delay<25:
    print("delay is less lets order")

print(now-lastTradedTime)
time_server_response = requests.get('https://tms35.nepsetms.com.np/tmsapi/metadata/serverTime',headers=headers)
time=time_server_response.json()['message'][:26]
server_time = datetime.strptime(time,'%Y-%m-%d %H:%M:%S.%f')
print("server time",server_time-now)
# date_time_obj = datetime.strptime(time,'%y-%m-%d %H:%M:%S.%f')[:-3]

# print((current_dat_time-lastTradedTime).total_seconds())

                                                   
