import requests
import base64
import json


def decode_binary_data_to_utf(binary_data):
    return base64.b64encode(binary_data).decode("utf-8")
def get_tokens():
    from bs4 import BeautifulSoup
    
    url = "https://www.imagetotext.info/"
    response = requests.get(url)

    if response.status_code == 200:
        # Print the HTML content of the page
        soup = BeautifulSoup(response.content, 'html.parser')
        meta_tag = soup.find('meta', {'name': '_token'})
        if meta_tag:
            token_value = meta_tag.get('content')
        else:
            print("No meta tag with name='_token' found.")
        cookies=requests.utils.dict_from_cookiejar(response.cookies)
        cookies['token']=token_value
        return cookies
    else:
        print(f"Error: {response.status_code}")
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
def get_captcha(tokens,byte_image):
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
        "base64": f'data:image/png;base64,{byte_image}',
        "imgname": "cap.png",
        "tool": "",
        "count": 0,
        "_token": tokens.get('token'),
    }

    response = requests.post('https://www.imagetotext.info/image-to-text', cookies=cookies, headers=headers, json=payload)
    return json.loads(response.text).get('text').split('\r\n')[-1]

def solve_captcha (binary_byte_image):
    cookies=get_tokens()
    decoded_image=decode_binary_data_to_utf(binary_byte_image)
    return get_captcha(tokens=cookies,byte_image=decoded_image)

if __name__=="__main__":
    cookies=get_tokens()
    print(get_captcha(tokens=cookies))
