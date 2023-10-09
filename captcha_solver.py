import requests
from PIL import Image
import pytesseract
from io import BytesIO

# URL of the image
image_url = "https://tms35.nepsetms.com.np/tmsapi/authApi/captcha/reload/da6fb449-af2b-4731-9b67-7f1f51e84fe6"

# Define headers
headers = {
    'authority': 'tms35.nepsetms.com.np',
    'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'accept-language': 'en-US,en;q=0.9',
    'cache-control': 'max-age=0',
    'sec-ch-ua': '"Google Chrome";v="117", "Not;A=Brand";v="8", "Chromium";v="117"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"macOS"',
    'sec-fetch-dest': 'document',
    'sec-fetch-mode': 'navigate',
    'sec-fetch-site': 'none',
    'sec-fetch-user': '?1',
    'upgrade-insecure-requests': '1',
    'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36'
}

# Function to recognize text from an image
def recognize_text_from_url(url, headers):
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        image_data = response.content
        image = Image.open(BytesIO(image_data))
        text = pytesseract.image_to_string(image)
        return text
    else:
        print(f"Failed to download image. Status code: {response.status_code}")
        return None

# Main function
def main():
    text = recognize_text_from_url(image_url, headers)
    if text:
        print("Recognized Text:")
        print(text)

if __name__ == "__main__":
    main()
