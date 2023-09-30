
from stock_order_manager import StockOrderManager


if __name__ == "__main__":
    # Define your order parameters and credentials here
    username = 'PK479690'
    password = 'a%bQ7PonS6QYGS'
    stock_name='sahas'
    stock_order_manager = StockOrderManager(username, password,stock_symbol=stock_name,request_per_sec=6)
    stock_order_manager.initialize()
    stock_grab=stock_order_manager.stock_grabber(order_quantity=10,previous_ltp=600)
    print(stock_grab)
