import requests
import base64
import json

from get_tokens import get_tokens
image_path='/Users/pkafle/tms-automation/tms_captcha_solver/img.png'
def encode_image_to_base64(image_path):
    try:
        with open(image_path, "rb") as image_file:
            image_binary_data = image_file.read()
            base64_image_data = base64.b64encode(image_binary_data).decode("utf-8")
            return base64_image_data
    except FileNotFoundError:
        print(f"Error: File not found at path: {image_path}")
        return None
    except Exception as e:
        print(f"An error occurred: {e}")
        return None
def get_captcha(tokens):
    cookies = {
        'XSRF-TOKEN': tokens.get('XSRF-TOKEN'),
        'image_to_text_session': tokens.get('image_to_text_session'),
    }

    headers = {
        'authority': 'www.imagetotext.info',
        'accept': '*/*',
        'accept-language': 'en-US,en;q=0.7',
        'content-type': 'application/json',  # Set the content type to JSON
        'origin': 'https://www.imagetotext.info',
        'referer': 'https://www.imagetotext.info/',
        'sec-ch-ua': '"Brave";v="119", "Chromium";v="119", "Not?A_Brand";v="24"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"macOS"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'sec-gpc': '1',
        'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'x-requested-with': 'XMLHttpRequest',
    }

    payload = {
        "base64": f'data:image/png;base64,{encode_image_to_base64(image_path)}',
        "imgname": "cap.png",
        "tool": "",
        "count": 0,
        "_token": tokens.get('token'),
    }

    response = requests.post('https://www.imagetotext.info/image-to-text', cookies=cookies, headers=headers, json=payload)
    return json.loads(response.text).get('text').split('\r\n')[-1]

cookies=get_tokens()
print(get_captcha(tokens=cookies))
