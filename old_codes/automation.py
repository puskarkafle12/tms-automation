from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait

def login(username,password):
    driver = webdriver.Chrome()
    driver.maximize_window()
    driver.get("https://tms35.nepsetms.com.np/login")
    driver.find_element(By.XPATH,'/html/body/app-root/app-login/div/div/div[2]/form/div[1]/input').send_keys(username) #user name
    driver.find_element(By.XPATH,'//*[@id="password-field"]').send_keys(password)  #password
    driver.find_element(By.XPATH,'//*[@id="captchaEnter"]').click()
    WebDriverWait(driver, 50).until(
    EC.element_to_be_clickable((By.XPATH,'/html/body/app-root/tms/app-menubar/aside/nav/ul/li[10]/a/span/span'))
)
    return driver


def check_radio_button_isclicked(driver):
    buy_radio_button=driver.find_element(By.XPATH,'/html/body/app-root/tms/main/div/div/app-member-client-order-entry/div/div/div[1]/div[2]/app-three-state-toggle/div/div/label[3]')

    # print('pkpk '+buy_radio_button.get_attribute('class'))
    if(buy_radio_button.get_attribute('class')=='xtoggler-btn-wrapper is-active'):
        print('buy radio button already clicked')
    if(buy_radio_button.get_attribute('class')=='xtoggler-btn-wrapper'):
        buy_radio_button.click()
        print('buy radio button is not clicked and now it is clicked ')

