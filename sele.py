from selenium import webdriver
import apitms
import datetime, time
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
import math

#stock name lekne
stock_name='SAHAS'
starting_price=436
count=0
order_count=0
#browser exposes an executable file
#Through Selenium test we will invoke the executable file which will then #invoke actual browser
driver = webdriver.Chrome()
# to maximize the browser window
driver.maximize_window()
def check_radio_button_isclicked():
    buy_radio_button=driver.find_element(By.XPATH,'/html/body/app-root/tms/main/div/div/app-member-client-order-entry/div/div/div[1]/div[2]/app-three-state-toggle/div/div/label[3]')

    # print('pkpk '+buy_radio_button.get_attribute('class'))
    if(buy_radio_button.get_attribute('class')=='xtoggler-btn-wrapper is-active'):
        print('buy radio button already clicked')
    if(buy_radio_button.get_attribute('class')=='xtoggler-btn-wrapper'):
        buy_radio_button.click()
        print('buy radio button is not clicked and now it is clicked ')
#order function
def order(quantity):
    global high_price
    # global previous_high
    # global previous_ltp
    # global ltp_price
    symbol_input_box=driver.find_element(By.XPATH,'/html/body/app-root/tms/main/div/div/app-member-client-order-entry/div/div/div[3]/form/div[2]/div[2]/input')


    symbol_box=symbol_input_box.get_attribute('value')
    if symbol_box==stock_name:
        # try:
        #     check_radio_button_isclicked()
        # except Exception as e:
        #     print(e)
        #     print("radio button cannot be clicked")
        # dropdown_element.click() yesma click garnu pardaina drop down confirm garna matrai ho
        qty.send_keys(quantity)
        # driver.find_element(By.XPATH,'').send_keys("")
        
        driver.find_element(By.XPATH,'/html/body/app-root/tms/main/div/div/app-member-client-order-entry/div/div/div[3]/form/div[2]/div[4]/input').send_keys(str(low_price))
        # driver.execute_script('document.getElementsByClassName("btn btn-sm ng-star-inserted")[0].removeAttribute("disabled");')
        
        order_button.click()
        
        print("Current Time =", datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3])
        print('the buy button clicked at: '+(tms_time.text).split()[3]+'\n')

        # try to click radio button
        try:
            check_radio_button_isclicked()
        except Exception as e:
            print(e)
            print("radio button cannot be clicked")
        # previous_high=high_price
        # previous_ltp=ltp_price
        
        # print('previous high',previous_high,'previous ltp',previous_ltp,'current high',high_price,'previous_ltp',previous_ltp)

    else:
        symbol_input_box.clear()
        symbol_input_box.send_keys(stock_name)
        # high_price=previous_high
        ltp_price=previous_ltp
        print(stock_name+' '+ symbol_box + ' stock name is not matching')
        # print('previous high',previous_high,'previous ltp',previous_ltp,'current high',high_price,'previous_ltp',previous_ltp)
#get method to launch the URL
# MN336760
# Puskar123@@@
# 2020094191
# KAFLESP1@
# dummy login
# username='20210609326'
# password='PUSkar123@@'
# driver.get("https://tms56.nepsetms.com.np/login")
# driver.find_element(By.XPATH,'/html/body/app-root/app-login/div/div/div[2]/form/div[1]/input').send_keys(username) #user name
# driver.find_element(By.XPATH,'//*[@id="password-field"]').send_keys(password)  #password
# driver.find_element(By.XPATH,'//*[@id="captchaEnter"]').click()
###puskar login sys
driver.get("https://tms35.nepsetms.com.np/login")
driver.find_element(By.XPATH,'/html/body/app-root/app-login/div/div/div[2]/form/div[1]/input').send_keys("PK479690") #user name
driver.find_element(By.XPATH,'//*[@id="password-field"]').send_keys("a%bQ7PonS6QYGS")  #password
driver.find_element(By.XPATH,'//*[@id="captchaEnter"]').click()
# # # wait until captcha come
# captcha aafile halne 

# driver.find_element(By.XPATH,'/html/body/app-root/app-login/div/div/div[2]/form/div[4]/input').click()#click login button


# wait until order management button appears

order_management_button = WebDriverWait(driver, 50).until(
    EC.element_to_be_clickable((By.XPATH,'/html/body/app-root/tms/app-menubar/aside/nav/ul/li[10]/a/span/span'))
)
# element.click()


#click order management button
order_management_button.click()
#click buy and sell button


buysell_button=driver.find_element(By.XPATH,'/html/body/app-root/tms/app-menubar/aside/nav/ul/li[10]/ul/li[1]/a')
try:
    buysell_button.click()
except:
    # print('buy button is not interactable exception raised and javascript is executed')
    # driver.execute_script("arguments[0].click();", order_management_button)
    time.sleep(4)
    order_management_button.click()
    buysell_button.click()



#wait until input text box appears stock name halne thau load nahunn jhel samma 
symbol_input_box = WebDriverWait(driver, 20).until(
    EC.presence_of_element_located((By.XPATH, '/html/body/app-root/tms/main/div/div/app-member-client-order-entry/div/div/div[3]/form/div[2]/div[2]/input'))#dropdown container lai wait garxa
)

symbol_input_box.click()

try:
    
  driver.find_element(By.CLASS_NAME,'box-order-entry box-indeterminate')
except:
    try:
        driver.execute_script('try {document.getElementsByClassName("box-order-entry blur__options box-buy")[0].removeAttribute("class");} catch(err) { document.getElementsByClassName("box-order-entry blur__options box-indeterminate")[0].removeAttribute("class");}')
    except Exception :
        print(Exception())

symbol_input_box.send_keys(stock_name)
# wait until drop down appears
dropdown_wait=WebDriverWait(driver,10)#10 bhaneko maximum wait time 10 sec ho
dropdown_element = WebDriverWait(driver, 10).until(
    EC.presence_of_element_located((By.XPATH, '/html/body/app-root/tms/main/div/div/app-member-client-order-entry/div/div/div[3]/form/div[2]/div[2]/typeahead-container'))#dropdown container lai wait garxa
)
# dropdown_element.click() yesma click garnu pardaina drop down confirm garna matrai ho
symbol_input_box.send_keys(Keys.RETURN)#pressing enter button 
buy_radio_button=driver.find_element(By.XPATH,'/html/body/app-root/tms/main/div/div/app-member-client-order-entry/div/div/div[1]/div[2]/app-three-state-toggle/div/div/label[3]')

buy_radio_button.click()#click buy radio



qty=driver.find_element(By.XPATH,'/html/body/app-root/tms/main/div/div/app-member-client-order-entry/div/div/div[3]/form/div[2]/div[3]/input')
qty.send_keys("10")

# driver.find_element(By.XPATH,'').send_keys("")
highprice=driver.find_element(By.XPATH,'/html/body/app-root/tms/main/div/div/app-member-client-order-entry/div/div/div[3]/form/div[3]/div[1]/div[3]/b')

high_price = float(highprice.text.replace(',', ''))
lowprice=driver.find_element(By.XPATH,'/html/body/app-root/tms/main/div/div/app-member-client-order-entry/div/div/div[3]/form/div[3]/div[1]/div[2]/b')
low_price=float(lowprice.text)
ltpprice=driver.find_element(By.XPATH,"//div[@class='order__form--prodtype price-display ng-star-inserted'][1]")
ltp_price=ltpprice.text

ltp_price = ltp_price.split()[1]
print("ltp price ",ltp_price," high price ",high_price," low price",low_price)
ltp_price = float(ltp_price.replace(',', ''))
tms_time=driver.find_element(By.XPATH,"/html/body/app-root/tms/app-menubar/aside/div[2]/div[1]/span")
driver.find_element(By.XPATH,'/html/body/app-root/tms/main/div/div/app-member-client-order-entry/div/div/div[3]/form/div[2]/div[4]/input').send_keys(str(low_price))
driver.execute_script('document.getElementsByClassName("btn btn-sm ng-star-inserted")[0].removeAttribute("disabled");')

order_button=driver.find_element(By.XPATH,"//button[@class='btn btn-sm ng-star-inserted btn-primary']")
# waiting 
tmstime=(tms_time.text).split()[3]
today = datetime.datetime.strptime(tmstime,"%H:%M:%S")
sleep = (datetime.datetime(today.year, today.month, today.day, 10,59,58) - today).seconds
sleep=900
if sleep<600:
    print('Waiting for ' + str(datetime.timedelta(seconds=sleep)))
    time.sleep(sleep)
    #buy button clicked
    check_radio_button_isclicked()
    order_button.click()#class="btn btn-sm ng-star-inserted btn-primary"
    #print tms time
    time.sleep(1)
    print('the buy button clicked at: '+(tms_time.text).split()[3]+'\n')
    print("Current Time =", datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3])
    try:
            check_radio_button_isclicked()
    except Exception as e:
            print(e)
            print("radio button cannot be clicked")
    # //button[@class='btn btn-sm ng-star-inserted']
else:
    print('runs without waiting')
    

previous_ltp=ltp_price


# driver.find_element(By.XPATH,'/html/body/app-root/tms/main/div/div/app-member-client-order-entry/div/div/div[3]/form/div[2]/div[2]/input').send_keys(Keys.RETURN)#pressing enter button 
while(1):
    try:
        symbol_input_box=driver.find_element(By.XPATH,'/html/body/app-root/tms/main/div/div/app-member-client-order-entry/div/div/div[3]/form/div[2]/div[2]/input')

   
        symbol_input_box.clear()
        symbol_input_box.clear()
        symbol_input_box.send_keys(stock_name)
        # wait until drop down appears
        dropdown_element = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.XPATH, '/html/body/app-root/tms/main/div/div/app-member-client-order-entry/div/div/div[3]/form/div[2]/div[2]/typeahead-container'))#dropdown container lai wait garxa
        )
        
        
            


        cookies = driver.get_cookies()
        # print('csrf token')
        # print(cookies)
        # print(cookies[0]['name'])
        aid=cookies[0]['value']
        xsrf_token=cookies[1]['value']
        rid=cookies[2]['value']
        # print(xsrf_token,aid,rid)
        price=apitms.fetchprice(xsrf_token,aid,rid,previous_ltp)
        if price=='end':
            break
        # print('this is fetched price ',price)
        # # high_price=price+2/100*price
        # # high_price=math.floor(high_price * 10 ** 1) / 10 ** 1
        # print('the high price after calc is ',high_price)
        # ltp_price=price
        # inc_percentage=(ltp_price-starting_price)/starting_price*100
        # print('increase percent is :',inc_percentage)
       
        symbol_input_box.send_keys(Keys.RETURN)
        # if inc_percentage<9:
        #     order(10)
        # previous_ltp=price
        # try:
        #     check_radio_button_isclicked()
        # except Exception as e:
        #     print(e)
        #     print('buy radio button cannot be clicked :',e)
    except Exception as e:
        print(e)
        print('exception in while 1 in main program',e)

  # global ltp_price
        # global high_price
        # global previous_high
        # global previous_ltp
        # global low_price
        # global count
        # a=1
        
#         while a==1:
#         # previous_ltp >= int(ltp_price):
#             # if symbol_input_box.get_attribute('value')!=stock_name:
                    
                
#             # else:
#             # check_radio_button_isclicked()
#             symbol_input_box.send_keys(Keys.BACKSPACE)
#             # symbol_input_box.clear()
#             # symbol_input_box.clear()
#             # symbol_input_box.send_keys(stock_name)
#             # wait until drop down appears
#             dropdown_element = WebDriverWait(driver, 20).until(
#                 EC.presence_of_element_located((By.XPATH, '/html/body/app-root/tms/main/div/div/app-member-client-order-entry/div/div/div[3]/form/div[2]/div[2]/typeahead-container'))#dropdown container lai wait garxa
#             )
#             # dropdown_element.click() yesma click garnu pardaina drop down confirm garna matrai ho
#             symbol_input_box.send_keys(Keys.RETURN)

        
#             high_price=driver.find_element(By.XPATH,'/html/body/app-root/tms/main/div/div/app-member-client-order-entry/div/div/div[3]/form/div[3]/div[1]/div[3]/b').text
#             high_price = float(high_price.replace(',', ''))
#             tms_time=driver.find_element(By.XPATH,"/html/body/app-root/tms/app-menubar/aside/div[2]/div[1]/span")
#             print("ltp price ",ltp_price," high price ",high_price," low price",low_price)
#             print('tms_time: '+(tms_time.text).split()[3]+'\n')
#             inc_percentage=(ltp_price-starting_price)/starting_price*100
#             print('increase percent is :',inc_percentage)

#             if inc_percentage>7:
#                 if count==0:
#                     order(50)
#                     count=count+1

#             if previous_high<float(high_price):
#                 order(10)
            
#                 low_price=driver.find_element(By.XPATH,'/html/body/app-root/tms/main/div/div/app-member-client-order-entry/div/div/div[3]/form/div[3]/div[1]/div[2]/b').text
#                 ltp_price=driver.find_element(By.XPATH,"//div[@class='order__form--prodtype price-display ng-star-inserted'][1]").text
#                 ltp_price = ltp_price.split()[1]
#                 ltp_price = float(ltp_price.replace(',', ''))
#                 print("ltp price ",ltp_price," high price ",high_price," low price",low_price)


   
# reload()

# highprice=driver.find_element(By.XPATH,'/html/body/app-root/tms/main/div/div/app-member-client-order-entry/div/div/div[3]/form/div[3]/div[1]/div[3]/b')
# lowprice=driver.find_element(By.XPATH,'/html/body/app-root/tms/main/div/div/app-member-client-order-entry/div/div/div[3]/form/div[3]/div[1]/div[2]/b')
# ltpprice=driver.find_element(By.XPATH,"//div[@class='order__form--prodtype price-display ng-star-inserted'][1]")
# tms_time=driver.find_element(By.XPATH,"/html/body/app-root/tms/app-menubar/aside/div[2]/div[1]/span")
    

# #waiting 

# tmstime=tms_time.text
# today = datetime.datetime.strptime(tmstime,"%H:%M:%S"
# sleep = (datetime.datetime(today.year, today.month, today.day, 21,52,58) - today).seconds
# print('Waiting for ' + str(datetime.timedelta(seconds=sleep)))
# time.sleep(sleep)
# driver.execute_script('document.getElementsByClassName("btn btn-sm ng-star-inserted")[0]").removeAttribute("disable");')
# driver.find_element(By.XPATH,"//button[@class='btn btn-sm ng-star-inserted']").click()
#to close the browser

# document.querySelector("body > app-root > tms > main > div > div > app-member-client-order-entry > div > div > div:nth-child(3) > form > div.d-flex.flex-wrap.flex-lg-nowrap.row.mt-3 > div.order__form--btngrp.ml-auto > button.btn.btn-sm.ng-star-inserted.btn-primary").click()
#element.removeAttribute("disabled");

# box blur walal
#element.removeAttribute("_ngcontent-nsd-c11");
# document.querySelector("body > app-root > tms > main > div > div > app-member-client-order-entry > div > div > div.box-order-entry.blur__options.box-buy")
# document.getElementsByClassName('box-order-entry blur__options box-buy')[0]
# implicit wait
# driver.execute_script('document.getElementsByClassName("btn btn-sm ng-star-inserted")[0]").removeAttribute("disabled");')

# driver.implicitly_wait(time_to_wait)


#explict wait
# wait=WebDriverWait(driver,10)
# buy_sell_button=wait.until(EC.element_to_be_clickable(By.XPATH,''))
# buy_sell_button.click()
