import requests
import base64
import json
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
def get_captcha():
    cookies = {
        'XSRF-TOKEN': 'eyJpdiI6IkVrOVduMzZ3QzEwV2s3QmVUYkdrSXc9PSIsInZhbHVlIjoiZU9BQlVvaHFmVTg0WFY1bVJzS014RisvMnBxMG1CU2dCK2hsa0RjR3RzeXpxUVFMZEJNWm1ORklqKytNTjhaMGdQSjMyaXpsTWU3YjU3NE1jOFA4aHJwanYxbXVlSy9aRE5XQmlvQVY5bGVySkNuTGo2Q2xSem9YUHg4Wk5odUgiLCJtYWMiOiIzOThkMzliM2JhODBiMzUzZjk1NzM2Y2Q3MjA1MTYyYzU0OGZiMjA5NWNhMDIxN2E1MTBiMTUyNDI1Y2JiYTliIiwidGFnIjoiIn0%3D',
        'image_to_text_session': 'eyJpdiI6IkNaQXdLT0xFdDZucTlIK0x5WWJMenc9PSIsInZhbHVlIjoiUkRjTUlabjhLejNTQ3BjTmNSZVZab3NudFpkU0JGQlNIWC9ET2xKdWQrc0c3K1dLOERTNDVmNGZFTTdEWGI0enlJNWRab3lJbTUwRkk5STVaN2pWdlkwdG1MR1d3N2taWm5JaXJGN1BZeGI2NDhhbDlKMmd5c0o0dllmMVcxdnMiLCJtYWMiOiJmMWJiOThhODM3ZDljNDE1ODhhZTQ0YjdhYTk1M2M0M2UxMDg0NzdkODY3ODBiYzg1ZWZiYzg5YzU2MTY4MGRmIiwidGFnIjoiIn0%3D',
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
        "_token": "BRWkDSZmg1CmVutEytV7mMb8uc1ktyTE9gzVsXdR",
    }

    response = requests.post('https://www.imagetotext.info/image-to-text', cookies=cookies, headers=headers, json=payload)
    return json.loads(response.text).get('text').split('\r\n')[-1]

print(get_captcha())