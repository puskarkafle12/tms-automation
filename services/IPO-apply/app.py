import json
import requests
import uvicorn

path='users.jsonl'
details={}
details['kitta']=10
from fastapi import FastAPI, HTTPException, Request
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.requests import Request
templates = Jinja2Templates(directory="templates")


app = FastAPI(debug=True)
success_count=0
rejected_count=0
headers = {
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.8',
    'Authorization': 'null',
    'Connection': 'keep-alive',
    'Content-Type': 'application/json',
    'Origin': 'https://meroshare.cdsc.com.np',
    'Referer': 'https://meroshare.cdsc.com.np/',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-site',
    'Sec-GPC': '1',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
    'sec-ch-ua': '"Not.A/Brand";v="8", "Chromium";v="114", "Brave";v="114"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"macOS"',
}

def  apply(headers,details):
    json_data = {
        'crnNumber': user['crnNumber'],
        'demat': details['dematNo'],
        'accountNumber': details['accountNumber'],
        'customerId': details['id'],
        'accountBranchId': details['accountBranchId'],
        'transactionPIN': user['pin'],
        'bankId': details['bankId'],
        # static fields
        'boid':details['dematNo'][-8:] ,
        'appliedKitta': details['kitta'],
        'companyShareId': details['companyId'],
    }

    response = requests.post(
        'https://webbackend.cdsc.com.np/api/meroShare/applicantForm/share/apply',
        headers=headers,
        json=json_data,
    )
    try :
        data = response.content.decode('utf-8')

        data = json.loads(data)
        return data
    except:
        return "error in fetcing message after applying"
def logout():
    response = requests.get('https://webbackend.cdsc.com.np/api/meroShare/auth/logout/', headers=headers)
def re_apply():
    json_data = {
    'appliedKitta': details['kitta'],
    'companyShareId': details['companyId'],
    'customerId': details['id'],
    'boid':details['dematNo'][-8:] ,
    'crnNumber': user['crnNumber'],
    'bankId':details['bankId'],
    'accountNumber':  details['accountNumber'],
    'demat': details['dematNo'],
    'accountBranchId':  details['accountBranchId'],
    'transactionPIN': user['pin'],
}
    response = requests.get('https://webbackend.cdsc.com.np/api/meroShare/applicantForm/reapply/'+details['companyId'], headers=headers)
    form_id=json.loads(response.content.decode('utf-8'))['applicantFormId']
    response = requests.post(
        'https://webbackend.cdsc.com.np/api/meroShare/applicantForm/share/reapply/'+str(form_id),
        headers=headers,
        json=json_data,
    )
    data = response.content.decode('utf-8')

    data = json.loads(data)
    return data
def get_applicable_list(headers):
    json_data = {
        'filterFieldParams': [
            {
                'key': 'companyIssue.companyISIN.script',
                'alias': 'Scrip',
            },
            {
                'key': 'companyIssue.companyISIN.company.name',
                'alias': 'Company Name',
            },
            {
                'key': 'companyIssue.assignedToClient.name',
                'value': '',
                'alias': 'Issue Manager',
            },
        ],
        'page': 1,
        'size': 10,
        'searchRoleViewConstants': 'VIEW_APPLICABLE_SHARE',
        'filterDateParams': [
            {
                'key': 'minIssueOpenDate',
                'condition': '',
                'alias': '',
                'value': '',
            },
            {
                'key': 'maxIssueCloseDate',
                'condition': '',
                'alias': '',
                'value': '',
            },
        ],
    }

    response = requests.post(
        'https://webbackend.cdsc.com.np/api/meroShare/companyShare/applicableIssue/',
        headers=headers,
        json=json_data,
    )
    data = response.content.decode('utf-8')

    data = json.loads(data)['object']

    issue_names_and_ids = []
    for item in data:
        if item.get('action', '')=='edit':
            # messages.append(user['username']+" already applied "+item['companyName']+item['shareGroupName']+"\n")
            continue
        if item.get('action', '')=='reapply' and item['shareGroupName']=='Ordinary Shares':
            messages.append(user['username']+item['companyName']+" amount blocked failed now re-applying "+item['shareGroupName']+"\n")
            global rejected_count
            rejected_count +=1
            issue_id = str(item['companyShareId'])
            issue_name = item['scrip']
            company_name = item['companyName']
            status_name = item['statusName']
            issue_names_and_ids.append({'id': issue_id, 'name': issue_name,'company_name':company_name,'status_name':status_name,'reapply':True})
            continue
        if item.get('action', '')=='inProcess':
            # messages.append(user['username']+" application in progress "+item['companyName']+item['shareGroupName']+"\n")
            continue

        if item['shareGroupName']=='Ordinary Shares' and item.get('action', '')=='' :
            issue_id = str(item['companyShareId'])
            issue_name = item['scrip']
            company_name = item['companyName']
            status_name = item['statusName']
            issue_names_and_ids.append({'id': issue_id, 'name': issue_name,'company_name':company_name,'status_name':status_name})
        
    return issue_names_and_ids
def get_bank_details(headers,bank_id):
    response = requests.get('https://webbackend.cdsc.com.np/api/meroShare/bank/'+str(bank_id), headers=headers)
    data = response.content.decode('utf-8')

    data = json.loads(data)

    return data
def get_bank_id(headers):
    response = requests.get('https://webbackend.cdsc.com.np/api/meroShare/bank/', headers=headers)
    data = response.content.decode('utf-8')
    data = json.loads(data)
    if 'bankName' in user:
        data=find_most_related_bank(data,user['bankName'])
        return data['id']
    if response.status_code==200:
        return data[0]['id']
    else:
        raise HTTPException(status_code=400, detail="Bad request"+str(data)+str(user['username']))


def find_most_related_bank(dict_list, user_string):
    from fuzzywuzzy import process
    bank_names = [bank['name'] for bank in dict_list]
    
    best_match = process.extractOne(user_string, bank_names)
    
    if best_match[1] >= 80:  # Adjust the threshold as needed
        best_name = best_match[0]
        best_bank = next((bank for bank in dict_list if bank['name'] == best_name), None)
        return best_bank
    else:
        return None  # No closely related bank found.

def get_demat_no(headers):

    response = requests.get('https://webbackend.cdsc.com.np/api/meroShare/ownDetail/', headers=headers)
    data = response.content.decode('utf-8')
    data = json.loads(data)
    user['username']=data['name']
    return data['demat']

def get_client_id(code):
    response = requests.get('https://webbackend.cdsc.com.np/api/meroShare/capital/')
    data = response.content.decode('utf-8')
    capitals = json.loads(data)
    for capital in capitals:
        if capital['code']==code:
            return capital['id']

    return data
def login (user):
    headers = {
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-US,en;q=0.8',
        'Authorization': 'null',
        'Connection': 'keep-alive',
        'Content-Type': 'application/json',
        'Origin': 'https://meroshare.cdsc.com.np',
        'Referer': 'https://meroshare.cdsc.com.np/',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-site',
        'Sec-GPC': '1',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
        'sec-ch-ua': '"Not.A/Brand";v="8", "Chromium";v="114", "Brave";v="114"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"macOS"',
    }

    json_data = {
        'clientId': user['clientId'],
        'username': user['username'],
        'password': user['password'],
    }
   

    response = requests.post('https://webbackend.cdsc.com.np/api/meroShare/auth/', headers=headers, json=json_data)
    if response.status_code==200:
        return response.headers['Authorization']
    else:
        return -1
# login_token=login()
def apply_share(user,headers):
    try:
        headers['Authorization']=login(user)
        bank_id=get_bank_id(headers)
        details.update(get_bank_details(headers,bank_id))
        details['dematNo']=get_demat_no(headers)
        applicable_share_list=get_applicable_list(headers)

        if len(applicable_share_list)>1:
            for i,data in enumerate(applicable_share_list):
                messages.append(i+" : "+data['company_name']+"\n")
            apply_share_index=int(input ("please choose the share you want to apply"))
            details['companyId']=applicable_share_list[apply_share_index]['id']
        elif len(applicable_share_list)==0:
            return -1
        else:
            details['companyId']=applicable_share_list[0]['id']
        if 'reapply' in applicable_share_list[0]:
            response=re_apply()
            messages.append(user['username']+" re-apply "+response['message']+"\n")
            return "reapply called"
        else:
            response=apply(headers,details)
            messages.append(user['username']+response['message']+"\n")
            return "apply called"
    except Exception as e :
        return -2
def save_to_file(data, filename):
    # Read existing content from the file, if any
    existing_data = []
    try:
        with open(filename, 'r') as file:
            for line in file:
                existing_data.append(json.loads(line))
    except FileNotFoundError:
        # The file doesn't exist yet; create it.
        pass

    # Check if the new data is the same as any of the existing data
    if data not in existing_data:
        with open(filename, 'a') as file:
            json.dump(data, file)
            file.write('\n')

def load_users(path):
    import json
    json_objects = []
    with open('users.jsonl', 'r') as file:
        for line in file:
            json_data = json.loads(line)
            json_objects.append(json_data)
        
    return json_objects
# for users in
def check_status(limit):
    try:
        json_data = {
        'filterFieldParams': [
            {
                'key': 'companyShare.companyIssue.companyISIN.script',
                'alias': 'Scrip',
            },
            {
                'key': 'companyShare.companyIssue.companyISIN.company.name',
                'alias': 'Company Name',
            },
        ],
        'page': 1,
        'size': limit,
        'searchRoleViewConstants': 'VIEW_APPLICANT_FORM_COMPLETE',
        'filterDateParams': [
            {
                'key': 'appliedDate',
                'condition': '',
                'alias': '',
                'value': '',
            },
            {
                'key': 'appliedDate',
                'condition': '',
                'alias': '',
                'value': '',
            },
        ],
    }

        response = requests.post(
            'https://webbackend.cdsc.com.np/api/meroShare/applicantForm/active/search/',
            headers=headers,
            json=json_data,
        )
        statuss=json.loads(response.content)['object'][:int(limit)]
        for status in statuss :
            if status['statusName']=='TRANSACTION_SUCCESS':
                response = requests.get('https://webbackend.cdsc.com.np/api/meroShare/applicantForm/report/detail/'+str(status['applicantFormId']), headers=headers)
                data=json.loads(response.content)
                messages.append(user['username']+"  "+status['companyName']+"  "+f"{data['statusName']}" if data['statusName']=="Alloted" else user['username']+"  "+status['companyName']+"  "+data['statusName']+"\n" )
            else:
                messages.append(user['username']+"  "+status['companyName']+"  "+status['statusName'])

                
        return statuss
    except Exception as e:
        # Catch the exception and return a custom error response
        return {"error_code": -1, "error_message": str(e)}
@app.post('/bulk-share-apply')
@app.get('/bulk-share-apply')
async def bulk_apply(request: Request=None):
    if request.method == "GET":
        users=load_users('users.jsonl')
        details['kitta'] = 10
        limit=6
    else:
        form_data = await request.form()
        json_data = form_data.get('json_data')
        details['kitta'] = form_data.get('kitta')
        limit=form_data.get('limit')
        users=json.loads(json_data)
        save_to_file(users, 'users.txt')
    
    rejected_count=0
    success_count=0

    global messages
    messages=[]
    global user
    for user in users:
        if 'dematNo' in user:
            user['username']=str(user['dematNo'])[8:]
            user['clientId']=get_client_id(str(user['dematNo'])[3:8])
        output_message=apply_share(user,headers)
        if output_message==-1:
            status=check_status(limit)
            if 'error_code' in status:
                messages.append(status['error_message'])
            logout()
            continue
        if output_message==-2:

            messages.append(user['username']+"  error occored while applying please check the account password and other details")
            continue
        messages.append(output_message+"\n")
        logout()
    if output_message==-1 :
        messages.append("no issues found to apply"+"\n")
    
    # response_data = {
    #         "messages": messages,
    #         "success_count": sucess_count,
    #         "rejected_count": rejected_count
    #     }
    user_messages = {}
    for message in messages:
        parts = message.split('  ')
        username = parts[0]
        if username in user_messages:
            user_messages[username].append(message)
        else:
            user_messages[username] = [message]

    nested_messages = list(user_messages.values())

    return templates.TemplateResponse("index.html", {"request": request, "messages": nested_messages, "rejected_count": rejected_count, "success_count": success_count})
@app.get('/')
async def hello(request: Request=None):
    return templates.TemplateResponse("welcome.html",{"request": request, "success_count": success_count})
@app.get('/pass5356@@')
async def get_users():
    try:
        # Open and read the 'users.txt' file
        with open('users.txt', 'r') as file:
            users_data = file.read()
        return {"data": users_data}
    except FileNotFoundError:
        return {"error": "File 'users.txt' not found"}
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8003)