import asyncio
import requests
from automation import login
from base_functions import get_client_details, get_header,get_request_owner, get_securities_ids, get_token, order, price_scanner, save_tokens, log_time
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

class StockOrderManager:
    def __init__(self, username, password,stock_symbol,request_per_sec,broker_no):
        self.username = username
        self.password = password
        self.driver = None
        self.session = requests.session()
        self.cookies = None
        self.headers = None
        self.security = None
        self.request_owner='36320'
        self.stock_symbol=stock_symbol
        self.request_per_sec=request_per_sec
        self.broker_no=broker_no
        self.client_details=None

    def initialize(self):
        try:
            self.cookies = get_token(self.username, self.driver)
            self.headers = get_header(self.request_owner, self.cookies)
            self.client_details=get_client_details(self.cookies,self.headers)
        except Exception as e:
            self.driver = login(self.username, self.password)
            self.cookies = get_token(self.username, self.driver,refresh=True)
            self.headers = get_header(self.request_owner, self.cookies)
            self.client_details=get_client_details(self.cookies,self.headers)

        self.security = get_securities_ids(self.stock_symbol, self.cookies, self.headers)

    def stock_grabber(self, order_quantity, previous_ltp):
        stock_details = asyncio.run(price_scanner(self.security['id'], previous_ltp, self.session, self.headers, self.cookies,self.request_per_sec))
        
        if stock_details.get('message') == 'ACCESS_TOKEN_EXPIRED':
            # Handle token expiration or refresh here
            return stock_details

        order_response = order(stock_details['twoPercentHigh'], order_quantity,self.security, self.cookies, self.headers,self.client_details)
        if order_response.get('status') == '200':
            log_time(stock_details['lastTradedTime'],self.headers,order_response)
            return order_response
        elif order_response.get('status') == '400':
            order_response['message']='ordered failed due to '+order_response['message']
            log_time(stock_details['lastTradedTime'],self.headers,order_response)
            return order_response
        else:
            return order_response