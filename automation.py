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