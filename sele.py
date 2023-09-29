import requests
from automation import login
from base_functions import get_header, get_token, order, price_scanner
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

#stock name lekne
orderPrice=440
orderQuantity=10
exchangeSecurityid=8021
id=2912
request_owner='36320'
stock_name='SAHAS'
starting_price=436
count=0
order_count=0
username='PK479690'
password='a%bQ7PonS6QYGS'
#browser exposes an executable file
#Through Selenium test we will invoke the executable file which will then #invoke actual browser
driver=None

def check_radio_button_isclicked():
    buy_radio_button=driver.find_element(By.XPATH,'/html/body/app-root/tms/main/div/div/app-member-client-order-entry/div/div/div[1]/div[2]/app-three-state-toggle/div/div/label[3]')

    # print('pkpk '+buy_radio_button.get_attribute('class'))
    if(buy_radio_button.get_attribute('class')=='xtoggler-btn-wrapper is-active'):
        print('buy radio button already clicked')
    if(buy_radio_button.get_attribute('class')=='xtoggler-btn-wrapper'):
        buy_radio_button.click()
        print('buy radio button is not clicked and now it is clicked ')


# # # wait until captcha come
# captcha aafile halne 
# driver.find_element(By.XPATH,'/html/body/app-root/app-login/div/div/div[2]/form/div[4]/input').click()#click login button
try:
    token=get_token(username,driver)
except:
    driver=login(username,password)
    token=get_token(username,driver)


token=get_token(username,driver)
session=requests.session()
header=get_header(request_owner,token)
stock_details=price_scanner(id,424,session,header,token)
print()
# order(msg['two_percent_high'],10,exchangeSecurityid=8021,id,token,headers,lastTradedTime)