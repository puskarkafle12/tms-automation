import requests
import json
from PIL import Image
import io
out_path='/Users/pkafle/tms-automation/tms_captcha_solver/img.png'
def save_png(png_data,out_path):
    with open(out_path, 'wb') as output_file:
        # Write the binary data to the file
        output_file.write(png_data)
def get_captcha_image(captcha_id):
    import requests
    headers = {
        'authority': 'tms35.nepsetms.com.np',
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'en-US,en;q=0.6',
        # 'cookie': 'REDACTED_CREDENTIAL',
        'referer': 'https://tms35.nepsetms.com.np/login',
        'sec-ch-ua': '"Brave";v="119", "Chromium";v="119", "Not?A_Brand";v="24"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"macOS"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'sec-gpc': '1',
        'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    }
    response = requests.get(
        f'https://tms35.nepsetms.com.np/tmsapi/authApi/captcha/image/{captcha_id}',
        headers=headers
    )
    return response.content
    
    
headers = {
    'authority': 'tms35.nepsetms.com.np',
    'accept': 'application/json, text/plain, */*',
    'accept-language': 'en-US,en;q=0.6',
    # 'cookie': 'REDACTED_CREDENTIAL',
    'referer': 'https://tms35.nepsetms.com.np/login',
    'sec-ch-ua': '"Brave";v="119", "Chromium";v="119", "Not?A_Brand";v="24"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"macOS"',
    'sec-fetch-dest': 'empty',
    'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'same-origin',
    'sec-gpc': '1',
    'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
}

response = requests.get('https://tms35.nepsetms.com.np/tmsapi/authApi/captcha/id', headers=headers)
raw_image=get_captcha_image(json.loads(response.text).get('id'))
save_png(raw_image,out_path)