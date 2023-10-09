
from stock_order_manager import StockOrderManager


if __name__ == "__main__":
    # Define your order parameters and credentials here
    # self/requestowoner ni dynamic banauna xa 
    username = 'PK479690'
    password = 'a%bQ7PonS6QYGS'
    stock_symbol='prvu'
    broker_no=35
    previous_ltp=400
    request_per_sec=3
    order_quantity=10
    request_owner='36320'
    stock_order_manager = StockOrderManager(username, password,stock_symbol,request_per_sec,broker_no,request_owner)
    stock_order_manager.initialize()
    stock_grab_response=stock_order_manager.stock_grabber(order_quantity,previous_ltp)
    print(stock_grab_response)