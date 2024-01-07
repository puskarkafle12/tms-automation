import json
import requests

from tms_captcha_solver.imgto_txt import solve_captcha
class LoginFailedException(Exception):
    def __init__(self, message="Login failed. Invalid credentials."):
        self.message = message
        super().__init__(self.message)

headers = {
    'authority': 'tms35.nepsetms.com.np',
    'accept': 'application/json, text/plain, */*',
    'accept-language': 'en-US,en;q=0.9',
    'content-type': 'application/json',
    'origin': 'https://tms35.nepsetms.com.np',
    'referer': 'https://tms35.nepsetms.com.np/login',
    'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"macOS"',
    'sec-fetch-dest': 'empty',
    'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'same-origin',
    'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
}
def get_captcha_id(headers):
    response = requests.get('https://tms35.nepsetms.com.np/tmsapi/authApi/captcha/id', headers=headers)
    return json.loads(response.content)['id']


def get_captcha_image(headers,captcha_id):
    response = requests.get(f'https://tms35.nepsetms.com.np/tmsapi/authApi/captcha/image/{captcha_id}', headers=headers)
    return response.content
def login_request(logindata):
     
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
        headers=headers,
        json=json_data,
    )
    return response
def login(username,password):
    captcha_id=get_captcha_id(headers)
    binary_captcha_image=get_captcha_image(headers,captcha_id)
    captcha=solve_captcha(binary_captcha_image)
    login_data={
        "captcha_id":captcha_id,
        "captcha":captcha,
        "username":username,
        "password":password
    }
    response=login_request(login_data)
    if json.loads(response.content)['status']=='108':
        max_retries = 3
        for _ in range(max_retries):
            response = login_request(login_data)
            if json.loads(response.content)['status'] != '108':
                break  # Break out of the loop if the status is not '108'
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

if __name__=="__main__":
    print(login('PK479690','alRvXnlHNXJuNlAqYiQ='))
# import requests

# cookies = {
#     'amp_adc4c4': 'BgqCccMfDnBNTdudn7Irvl.VDh1TldmUnROc2RJS1pjMjU2UVJNWGNwQ2dBMw==..1hhbmiijs.1hhbncods.0.4.4',
# }
