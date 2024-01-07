import multiprocessing
import sys

from utils.base_functions import find_file_in_directory, load_users

from stock_order_manager.stock_order_manager import StockOrderManager

def run_stock_order_manager(username, password, stock_symbol, request_per_sec, broker_no, order_quantity, previous_ltp):
    stock_order_manager = StockOrderManager(username, password, stock_symbol, request_per_sec, broker_no)
    stock_grab_response = stock_order_manager.stock_grabber(order_quantity, previous_ltp)
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
    
    
    
    
    # multithreading code 
    # Define the parameters for the first user
    # user_file_path=find_file_in_directory('users.txt')
    # if not user_file_path:
    #     print("user credintial file not found,\nexiting... ")
    #     sys.exit()
    # users =load_users(user_file_path)
    # # Create two processes to run the code for both users concurrently
    # processes = []

    # for user in users:  # Use values() to get the dictionary values
    #     process = multiprocessing.Process(target=run_stock_order_manager, args=(user['username'], user['password'], user['stock_symbol'], user['request_per_sec'], user['broker_no'], user['request_owner'], user['order_quantity'], user['previous_ltp']))
    #     processes.append(process)
    #     process.start()

    # for process in processes:
    #     process.join()