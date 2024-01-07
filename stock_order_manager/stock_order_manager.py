import asyncio
import requests
from utils.base_functions import get_client_details,get_header,get_request_owner, get_securities_ids, get_token, order, price_scanner, save_tokens, log_time
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

from utils.login import login

class StockOrderManager:
    def __init__(self, username, password,stock_symbol,request_per_sec,broker_no):
        self.username = username
        self.password = password
        self.driver = None
        self.session = requests.session()
        self.tokens = None
        self.headers = None
        self.security = None
        self.stock_symbol=stock_symbol
        self.request_per_sec=request_per_sec
        self.broker_no=broker_no
        self.client_details=None
        self.initialize()
    def initialize(self):
        try:
            # login success from saved tokens  
            self.login_response = get_token(self.username)
            self.tokens=self.login_response['tokens']
            self.headers = get_header(self.login_response['request_owner'], self.tokens)
            self.client_details=get_client_details(self.tokens,self.headers,self.login_response['client_dealer_id'])
        except Exception as e:
            # retry login from the post request 
            self.login_response = login(self.username, self.password)
            self.tokens = self.login_response['tokens']
            save_tokens(self.username,self.login_response)
            self.headers = get_header(self.login_response['request_owner'], self.tokens)
            self.client_details=get_client_details(self.tokens,self.headers,self.login_response['client_dealer_id'])

        self.security = get_securities_ids(self.stock_symbol, self.tokens, self.headers)

    def stock_grabber(self, order_quantity, previous_ltp,order_limit=0):
        stock_details={}
        while stock_details.get('message') !='exit' and order_limit<3:
            stock_details = asyncio.run(price_scanner(self.security['id'], previous_ltp, self.session, self.headers, self.tokens,self.request_per_sec))
            if stock_details.get('message') == 'ACCESS_TOKEN_EXPIRED':
                # Handle token expiration or refresh here
                return stock_details

            order_response = order(stock_details['twoPercentHigh'], order_quantity,self.security, self.tokens, self.headers,self.client_details)
            if order_response.get('status') == '200':
                log_time(stock_details['lastTradedTime'],self.headers,order_response)
                order_limit+=1
                return order_response
            elif order_response.get('status') == '400':
                order_response['message']='ordered failed due to '+order_response['message']
                log_time(stock_details['lastTradedTime'],self.headers,order_response)
                return order_response
            else:
                return order_response