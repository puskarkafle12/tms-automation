
from datetime import datetime
import json
import sys
import requests
from time import sleep
import math
import os

from database import  get_db
from models.logged_in_user import LoggedInUsers
from sqlalchemy.exc import SQLAlchemyError

from functools import wraps
import time

def get_function_time(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        execution_time = end_time - start_time
        print(f"Function '{func.__name__}' executed in {execution_time:.6f} seconds")
        return result
    return wrapper
def truncate_to_one_decimal_place(number):
    return round(number, 1)
def logout_user(client_id: str,message):
    db=get_db()
    user = db.query(LoggedInUsers).filter(LoggedInUsers.client_id == client_id).first()
    if user:
        user.status = "logged_out"
        user.message = message
        db.commit()
        return True
    else:
        return False

def calculate_high_price(ltp, change_in_percentage):
    if change_in_percentage > 7.843:
        original_price = ltp*100/(change_in_percentage+100)
        ten_percent_change = (original_price * 10/ 100 )+ original_price
        high_price = math.floor(ten_percent_change * 10 ** 1) / 10 ** 1
        return high_price

    high_price = ltp + (2 / 100) * ltp
    # truncating the decimal e.g., 12.343 to 12.3
    high_price = math.floor(high_price * 10 ** 1) / 10 ** 1
    return high_price

# '2023-09-29 19:16:39.806085' to datetime obj


def format_time(time_str):
    # Split the time string into seconds and microseconds parts
    time_parts = time_str.split('.')

    # Handle the seconds part
    seconds = time_parts[0]
    microseconds = 0  # Default value for microseconds

    # If there is a microseconds part, truncate or round it to 6 decimal places
    if len(time_parts) > 1:
        microseconds_str = time_parts[1][:6]  # Limit to 6 decimal places
        microseconds = int(microseconds_str.ljust(6, '0')
                           )  # Ensure it's 6 digits

    # Combine the seconds and microseconds parts
    formatted_time_str = seconds + '.' + str(microseconds).zfill(6)

    # Format the combined time string into a datetime object
    formatted_time = datetime.strptime(
        formatted_time_str, '%Y-%m-%d %H:%M:%S.%f')
    return formatted_time


def log_time(last_traded_time, headers, response):
    time_server_response = requests.get(
        'https://tms35.nepsetms.com.np/tmsapi/metadata/serverTime', headers=headers)
    time = time_server_response.json()['message'][:26]
    server_time = format_time(time)
    last_traded_time = format_time(last_traded_time)
    f = open("traded_difference.txt", "a")
    f.write("\nserver time and last traded time difference is:" +
            str(server_time-last_traded_time)+' \n response'+str(response))
    f.close()
# Function to save tokens to a JSON file


# def save_tokens(username, login_response):
    # data = {}
    # data[username] = login_response
    # with open('tokens.json', 'w') as file:
    #     json.dump(data, file)

def is_within_time_range(start_time, end_time, current_time):
    return True
    return (start_time.hour, start_time.minute, start_time.second) <= (current_time.hour, current_time.minute, current_time.second) <= (end_time.hour, end_time.minute, end_time.second)

def save_tokens(client_id, tokens,broker_no):
    try:
        db=get_db()
        user = db.query(LoggedInUsers).filter_by(client_id=client_id).first()
        if user:
            user.tokens = tokens
            user.status="logged_in"
        else:
            user = LoggedInUsers(client_id=client_id, tokens=tokens,broker_no=broker_no,status="logged_in")
            db.add(user)
        db.commit()
        return True
    except Exception as e:
        print(f"Failed to save tokens: {e}")
        db.rollback()
        return False

# Function to get tokens for a user
def get_tokens(client_id):
    try:
        db=get_db()
        user = db.query(LoggedInUsers).filter_by(client_id=client_id).first()
        if user:
            return user.tokens,user.broker_no
        else:
            return None
    except SQLAlchemyError as e:
        print(f"Failed to get tokens: {e}")
        return None
# def get_token(username):
#     with open('tokens.json', 'r') as file:
#         data = json.load(file)
#         if username in data:
#             return data[username]
#         else:
#             raise KeyError(f"Token not found for username: {username}")


def load_users(filename):
    users = []
    current_user = {}

    with open(filename, 'r') as file:
        for line in file:
            line = line.strip()
            if not line:  # Skip empty lines
                continue

            if line == 'end':
                # End of user entry, save it and reset current_user
                if current_user:
                    users.append(current_user)
                    current_user = {}
            else:
                key, value = list(map(lambda x:x.strip(),line.split('=',1)))
                # Remove single quotes from values
                value = value.strip('\'')
                if key == 'broker_no' or key == 'previous_ltp' or key == 'request_per_sec' or key == 'order_quantity':
                    if '.' in value:
                        current_user[key] = float(value)
                    else:
                        current_user[key] = int(value)
                else:
                    current_user[key] = value

    return users


def find_file_in_directory(file_name):
    root_dir = os.path.dirname(os.path.abspath(__file__))
    for foldername, subfolders, filenames in os.walk(root_dir):
        for filename in filenames:
            if filename == file_name:
                return os.path.join(foldername, filename)
    return None  # File not found
