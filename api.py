import requests
from time import time
count=0
# import logging

# import http.client
# http.client.HTTPConnection.debuglevel = 1


import requests

# headers = {
#     'Connection': 'keep-alive',
#     'sec-ch-ua': '" Not;A Brand";v="99", "Google Chrome";v="91", "Chromium";v="91"',
#     'Accept': 'application/json, text/plain, */*',
#     'Request-Owner': '36320',
#     'Authorization': 'Bearer eyJhbGciOiJIUzI1NiJ9.eyJqdGkiOiIzNjMyMCIsImlhdCI6MTYyOTE2NjY4Niwic3ViIjoiTUFELVJDVSxGTS1SQTJBM0NBMVVELE1JTkZPLVIsT00tUkNVLFNCSS1SQTJBM0NBMVVELExGLVJBMkEzQ0ExVUQsR0wtUixUQi1SQ1UsU1EtUixNVy1SLFBGLVJBMkEzQ0ExVUQsT0ItUkEyQTNDQTFVRCxESC1SQ1UsQ0NNLVJBMkEzQ0ExVUQsT0JILVIsQ1MtUkEyQTNDQTFVRCxUUi1SQ1UsU1NJLVJBMkEzQ0ExVUQsQ0ZULVJBMkEzQ0ExVUQsRlctUkEyQTNDQTFVRCxTVExCSS1SQ1UsV1MtUixNTE5XUy1SLE1MLVIsRE5BUy1SLE1XREMtUixDTFRTLVIsTUNPRS1SQTJBM0NBMVVELEROQUwtUixUQkgtUiIsImlzcyI6IlBLNDc5NjkwIiwiZXhwIjoxNjI5MjIwNjg2fQ.LP9LnouAaagzntGz-UyAxCt5f8yJnfhpMWNqYU_3F_g',
#     'sec-ch-ua-mobile': '?0',
#     'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.164 Safari/537.36',
#     'Host-Session-Id': 'ZFc1a1pXWnBibVZrLWU3OTRkZDZjLTMyYjgtNGViNS05ZTU3LTdhZmMwNmQ5ZWUxYg==',
#     'Sec-Fetch-Site': 'same-origin',
#     'Sec-Fetch-Mode': 'cors',
#     'Sec-Fetch-Dest': 'empty',
#     'Referer': 'https://tms35.nepsetms.com.np/tms/me/memberclientorderentry',
#     'Accept-Language': 'en-US,en;q=0.9',
# }




session = requests.Session()


while(1):
    
        
    # # You must initialize logging, otherwise you'll not see debug output.
    # logging.basicConfig()
    # logging.getLogger().setLevel(logging.DEBUG)
    # requests_log = logging.getLogger("requests.packages.urllib3")
    # requests_log.setLevel(logging.DEBUG)
    # requests_log.propagate = True
     

   

    response = requests.get('https://tms35.nepsetms.com.np/tmsapi/rtApi/ws/stockQuote/2888', headers=headers)
    

    try:
        print(response.json())
        count=count+1
        print(count)
    except:
        
        print('error')
    if(response.status_code==401):
        break
