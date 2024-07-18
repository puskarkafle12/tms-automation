import sys
from utils.base_functions import load_users
from utils.tms import TmsUser

def run_stock_order_manager(username, password, stock_symbol, request_per_sec, broker_no, order_quantity, previous_ltp):
    user_tms = TmsUser(username=username, password=password, stock_symbol=stock_symbol, request_per_sec=request_per_sec, broker_no=broker_no)
    user_tms.try_cached_login()
    stock_grab_response = user_tms.stock_grabber(order_quantity)
    print(stock_grab_response)

if __name__ == "__main__":
    
    user_file_path='/Users/pkafle/tms-automation/users.txt'
    if not user_file_path:
        print("user credintial file not found,\nexiting... ")
        sys.exit()
    user =load_users(user_file_path)[0]
    run_stock_order_manager(
    user['username'], user['password'], user['stock_symbol'],
    user['request_per_sec'], user['broker_no'],
    user['order_quantity'], user['previous_ltp']
    )