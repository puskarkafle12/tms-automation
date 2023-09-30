import requests
from automation import login
from base_functions import get_header,get_request_owner, get_securities_ids, get_token, order, price_scanner, save_tokens
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

class StockOrderManager:
    def __init__(self, username, password,stock_name,request_per_sec):
        self.username = username
        self.password = password
        self.driver = None
        self.session = requests.session()
        self.cookie = None
        self.header = None
        self.security = None
        self.id = None
        self.request_owner='36320'
        self.stock_name=stock_name
        self.request_per_sec=request_per_sec

    def initialize(self):
        try:
            self.cookie = get_token(self.username, self.driver)
        except:
            self.driver = login(self.username, self.password)
            self.cookie = get_token(self.username, self.driver)

        self.cookie = get_token(self.username, self.driver)
        self.header = get_header(self.request_owner, self.cookie)
        self.security = get_securities_ids(self.stock_name, self.cookie, self.header)
        self.id = self.security['id']

    def stock_grabber(self, order_quantity, previous_ltp):
        stock_details = price_scanner(self.id, previous_ltp, self.session, self.header, self.cookie,self.request_per_sec)
        
        if stock_details.get('message') == 'ACCESS_TOKEN_EXPIRED':
            # Handle token expiration or refresh here
            pass

        order_response = order(stock_details['twoPercentHigh'], order_quantity,self.security['exchangeSecurityId'], self.id, self.cookie, self.header, stock_details['lastTradedTime'])
        if order_response.get('status') == '200':
            pass
        elif order_response.get('status') == '400':
            pass

if __name__ == "__main__":
    # Define your order parameters and credentials here
    username = 'PK479690'
    password = 'a%bQ7PonS6QYGS'
    stock_name='sahas'
    stock_order_manager = StockOrderManager(username, password,stock_name=stock_name,request_per_sec=1)
    stock_order_manager.initialize()
    stock_order_manager.stock_grabber(order_quantity=10,previous_ltp=234)
