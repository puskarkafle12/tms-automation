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
        # 'cookie': '_rid=eyJlbmMiOiJBMTI4R0NNIiwiYWxnIjoiZGlyIn0..cKeimqTAvFcjG13t.U-butMD41gqo1cWvo3hlNW7gXgoz8AkTiQLg6AsjXGp6vSX6MkSi9byQDsaxWFXB4JyekYXrHrKVoQGDvRQSQYHIsK7Mjmn2RO-Jx1aVl_OTuAVtDYt3jDpbvHNWYqACndCrC0X2P5WA_r5ngJyKN-sCH6dSAvM2akglYUx2Ij1mo7t0ejVXEvqYEWZPuJnU8u5YgexCYxjSpgP1sLmbQj9Uf0rCa0blRDoQdXTVP12ARFa_SWo3RDDrXKzEXpX3GcIxHCzW22lbnwgW_SMDXxlji4nsGEozA6loxu7DPEXdnVi3x3Ka7AFtOx1scv-duW2MJdPtTECmH5JnpYMN7v3FteQn4RhFr82yvlCvaCqKFprNl1Qxu7oSMBMRCn_gALUT2Y8a-6jWiMzaV-pengW1eMJkVwXmiALkjaKbvMps6sXfiS37U26hU1OEt4a5Be4JG_x24KnSTr0RPJBGlnBVPI0NFgWSJSNECgfkm8gClsr4a47NayznFn582qAAnKOoHBnph5_COVhASD57MpiM0GnGqgNulHejv7wVLDTamVq8YF4dHjc_W5XuxLUA6cw.Is1IlyveSowS_TGEu8wmzQ; _aid=eyJlbmMiOiJBMTI4R0NNIiwiYWxnIjoiZGlyIn0..TXu42iyuDDZIvkyR.pcBg9tfutMq8TlfEK-Ai3CBAJ-QFazJD7RNYsnoCXAfyglMJLXh4rkj_ONti7FKu9bAsUQMOb_-utIqups3HHJ9LGV5eUjtKN2kGmU7Yd7HHUOkjbmibdoxk8e-w8temjFy8U5R_vI083cHkPBpduXwaRWRBxp46QQb9wH4GND7ljJ3vJ_-R51T8SX5JrHuwAHrH8HmVxYnRr92d46s7PixpghGqweuejZUMaGU9JD8H1zxC0fWOtOzJt9n3M_7HcxQDqy2nlpE7tRmEmULffMqvXy8_IQMm7YkpfwdgNqbYUJXZNY4wbaunpiq6RPkMHI9W5H8Pcn3_Voyahcqzw7MxYi4iHjjoDuAUrnZPD1YGRGaZc8j8LcusmqX7oDHty8jGkf8gr_03JhxNo20KP7QI26Oe_nJTFYIivjnMer2MUcQ-iRdF8iGGF8HV5FGbAroQwgLKlaavKK7BuKRj4RUkS4LWuieZ2ikp7sxSnfakmZ0RWxROS8Qg5PXBBU6r3D2laUwAWcbAO8wQv1UGeyQuqmtJIJZ1A4O2c9u2Urf9vUOdTj3rnMRisym5HchDKlw.cVsTTkcySwulavoAs2HYGg; XSRF-TOKEN=1b53ca43-aa93-412f-8c7b-f6d1b6b4fd78; pdfcc=1',
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
    # 'cookie': '_rid=eyJlbmMiOiJBMTI4R0NNIiwiYWxnIjoiZGlyIn0..cKeimqTAvFcjG13t.U-butMD41gqo1cWvo3hlNW7gXgoz8AkTiQLg6AsjXGp6vSX6MkSi9byQDsaxWFXB4JyekYXrHrKVoQGDvRQSQYHIsK7Mjmn2RO-Jx1aVl_OTuAVtDYt3jDpbvHNWYqACndCrC0X2P5WA_r5ngJyKN-sCH6dSAvM2akglYUx2Ij1mo7t0ejVXEvqYEWZPuJnU8u5YgexCYxjSpgP1sLmbQj9Uf0rCa0blRDoQdXTVP12ARFa_SWo3RDDrXKzEXpX3GcIxHCzW22lbnwgW_SMDXxlji4nsGEozA6loxu7DPEXdnVi3x3Ka7AFtOx1scv-duW2MJdPtTECmH5JnpYMN7v3FteQn4RhFr82yvlCvaCqKFprNl1Qxu7oSMBMRCn_gALUT2Y8a-6jWiMzaV-pengW1eMJkVwXmiALkjaKbvMps6sXfiS37U26hU1OEt4a5Be4JG_x24KnSTr0RPJBGlnBVPI0NFgWSJSNECgfkm8gClsr4a47NayznFn582qAAnKOoHBnph5_COVhASD57MpiM0GnGqgNulHejv7wVLDTamVq8YF4dHjc_W5XuxLUA6cw.Is1IlyveSowS_TGEu8wmzQ; _aid=eyJlbmMiOiJBMTI4R0NNIiwiYWxnIjoiZGlyIn0..TXu42iyuDDZIvkyR.pcBg9tfutMq8TlfEK-Ai3CBAJ-QFazJD7RNYsnoCXAfyglMJLXh4rkj_ONti7FKu9bAsUQMOb_-utIqups3HHJ9LGV5eUjtKN2kGmU7Yd7HHUOkjbmibdoxk8e-w8temjFy8U5R_vI083cHkPBpduXwaRWRBxp46QQb9wH4GND7ljJ3vJ_-R51T8SX5JrHuwAHrH8HmVxYnRr92d46s7PixpghGqweuejZUMaGU9JD8H1zxC0fWOtOzJt9n3M_7HcxQDqy2nlpE7tRmEmULffMqvXy8_IQMm7YkpfwdgNqbYUJXZNY4wbaunpiq6RPkMHI9W5H8Pcn3_Voyahcqzw7MxYi4iHjjoDuAUrnZPD1YGRGaZc8j8LcusmqX7oDHty8jGkf8gr_03JhxNo20KP7QI26Oe_nJTFYIivjnMer2MUcQ-iRdF8iGGF8HV5FGbAroQwgLKlaavKK7BuKRj4RUkS4LWuieZ2ikp7sxSnfakmZ0RWxROS8Qg5PXBBU6r3D2laUwAWcbAO8wQv1UGeyQuqmtJIJZ1A4O2c9u2Urf9vUOdTj3rnMRisym5HchDKlw.cVsTTkcySwulavoAs2HYGg; XSRF-TOKEN=1b53ca43-aa93-412f-8c7b-f6d1b6b4fd78; pdfcc=1',
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