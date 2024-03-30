import sys
from typing import Dict

from fastapi import Depends
from database import get_db
from models.logged_in_user import LoggedInUsers
from utils.base_functions import load_users
from utils.tms import TmsUser
from sqlalchemy.orm import Session


user_file_path = '/Users/pkafle/tms-automation/users.txt'
if not user_file_path:
    print("User credential file not found, exiting... ")
    sys.exit()
user = load_users(user_file_path)[0]

# Create an instance of Tms

def load_tms_users_instances(client_ids,tms_instances:Dict):
    db = get_db()
    tms_users = db.query(LoggedInUsers).filter(LoggedInUsers.client_id.in_(client_ids)).all()
    for tms_user in tms_users:
        if tms_user.client_id not in tms_instances.keys():
            tms_user_instance = TmsUser(
                broker_no=tms_user.broker_no,
                username=tms_user.client_id,
                expires=tms_user.expires,
                tokens=tms_user.tokens
            )
            try:
                tms_user_instance.try_token_login()
            except:
                try:
                    tms_instances.pop(tms_user.client_id)
                except:
                    pass
            tms_instances[tms_user.client_id] = tms_user_instance
    return tms_instances

        
#     tms = TmsUser(
# username=user['username'], password=user['password'], stock_symbol=user['stock_symbol'],
#     request_per_sec=user['request_per_sec'],broker_no= user['broker_no']
# )