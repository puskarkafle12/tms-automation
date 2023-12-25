import requests
from bs4 import BeautifulSoup

url = "https://www.imagetotext.info/"
def get_tokens():
    response = requests.get(url)

    if response.status_code == 200:
        # Print the HTML content of the page
        soup = BeautifulSoup(response.content, 'html.parser')
        meta_tag = soup.find('meta', {'name': '_token'})
        if meta_tag:
            token_value = meta_tag.get('content')
            print(f"The value of _token is: {token_value}")
        else:
            print("No meta tag with name='_token' found.")
        print(response.text)
        cookies=requests.utils.dict_from_cookiejar(response.cookies)
        cookies['token']=token_value
        return cookies
    else:
        print(f"Error: {response.status_code}")
