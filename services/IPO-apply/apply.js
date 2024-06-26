var details = {};
details['kitta'] = 10;
let messages = [];
var users = [{ "clientId": 186, "username": "374749", "password": "Puskar123@@@@@", "crnNumber": "2946088TCL", "pin": "5356", "bankName": "siddhartha bank" },
{ "clientId": 178, "username": "205808", "password": "kH48mwSQbE%QQY", "crnNumber": "00884971", "pin": "5356" },
{ "clientId": 163, "username": "00358242", "password": "qqCPfLH^2^J@", "crnNumber": "O8-O89527708", "pin": "5356" },
{ "clientId": 137, "username": "251157", "password": "Dnudd!9Px*vEZW", "crnNumber": "CZP00377935", "pin": "5356" }
];
user = { "clientId": 186, "username": "374749", "password": "Puskar123@@@@@", "crnNumber": "2946088TCL", "pin": "5356", "bankName": "siddhartha bank" }

var headers = {
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
};
// tested
function login(user) {
    return new Promise((resolve, reject) => {
        // Define headers for the login request
        // Define the login request data
        var loginData = {
            'clientId': user.clientId,
            'username': user.username,
            'password': user.password,
        };

        // Send the login request
        fetch('https://webbackend.cdsc.com.np/api/meroShare/auth/', {
            method: 'POST',
            headers: headers,
            body: JSON.stringify(loginData),
        })
            .then((response) => {
                if (response.status === 200) {
                    // Successful login
                    headers['Authorization'] = response.headers.get('Authorization');
                    return response.headers.get('Authorization');
                } else {
                    // Failed login
                    reject('Login failed. Check the account credentials.');
                }
            })
            .then((authorization) => {
                resolve(authorization);
            })
            .catch((error) => {
                reject('Error in login: ' + error);
            });
    });
}
async function logout() {
    try {
        const response = await fetch('https://webbackend.cdsc.com.np/api/meroShare/auth/logout/', {
            method: 'GET',
            headers: headers,
        });

        if (response.status === 200 || response.status === 201) {
            console.log('Logout successful');
        } else {
            console.log('Logout failed with status: ' + response.status);
        }
    } catch (error) {
        console.error('Error during logout:', error);
    }
}
// tested
async function get_client_id(code) {
    const response = await fetch('https://webbackend.cdsc.com.np/api/meroShare/capital/');
    const data = await response.text();
    const capitals = JSON.parse(data);
    for (const capital of capitals) {
        if (capital['code'] === code) {
            return capital['id'];
        }
    }
}
// tested
async function get_bank_id(headers) {
    const response = await fetch('https://webbackend.cdsc.com.np/api/meroShare/bank/', {
        method: 'GET',
        headers: headers,
    });

    if (response.status !== 200) {
        throw new Error('Bad request: ' + response.status);
    }

    const data = await response.json();

    let details = {};  // Declare details as let



    return data[0]['id'];
}
// tested
async function get_bank_details(headers, bank_id) {
    const url = 'https://webbackend.cdsc.com.np/api/meroShare/bank/' + bank_id;

    const response = await fetch(url, {
        method: 'GET',
        headers: headers,
    });

    if (response.status !== 200) {
        throw new Error('Bad request: ' + response.status);
    }

    const data = await response.json();

    return data;
}
// tested
async function get_demat_no(headers) {
    const url = 'https://webbackend.cdsc.com.np/api/meroShare/ownDetail/';

    const response = await fetch(url, {
        method: 'GET',
        headers: headers,
    });

    if (response.status !== 200) {
        throw new Error('Bad request: ' + response.status);
    }

    const data = await response.json();

    // Assuming 'user' is a globally defined object
    if ('username' in data) {
        user['username'] = data['name'];
    }

    return data['demat'];
}
// tested
async function get_applicable_list(headers) {
    const json_data = {
        filterFieldParams: [
            {
                key: 'companyIssue.companyISIN.script',
                alias: 'Scrip',
            },
            {
                key: 'companyIssue.companyISIN.company.name',
                alias: 'Company Name',
            },
            {
                key: 'companyIssue.assignedToClient.name',
                value: '',
                alias: 'Issue Manager',
            },
        ],
        page: 1,
        size: 10,
        searchRoleViewConstants: 'VIEW_APPLICABLE_SHARE',
        filterDateParams: [
            {
                key: 'minIssueOpenDate',
                condition: '',
                alias: '',
                value: '',
            },
            {
                key: 'maxIssueCloseDate',
                condition: '',
                alias: '',
                value: '',
            },
        ],
    };

    const url = 'https://webbackend.cdsc.com.np/api/meroShare/companyShare/applicableIssue/';

    const response = await fetch(url, {
        method: 'POST',
        headers: headers,
        body: JSON.stringify(json_data),
    });

    if (response.status !== 200) {
        throw new Error('Bad request: ' + response.status);
    }

    const responseData = await response.json();

    const data = responseData.object;

    const issue_names_and_ids = [];

    for (const item of data) {
        if (item.action === 'edit') {
            // messages.push(user.username + " already applied " + item.companyName + item.shareGroupName + "\n");
            continue;
        }

        if (item.action === 'reapply' && item.shareGroupName === 'Ordinary Shares') {
            // messages.push(user.username + item.companyName + " amount blocked failed now re-applying " + item.shareGroupName + "\n");
            rejected_count++;
            const issue_id = String(item.companyShareId);
            const issue_name = item.scrip;
            const company_name = item.companyName;
            const status_name = item.statusName;
            issue_names_and_ids.push({
                id: issue_id,
                name: issue_name,
                company_name: company_name,
                status_name: status_name,
                reapply: true,
            });
            continue;
        }

        if (item.action === 'inProcess') {
            // messages.push(user.username + " application in progress " + item.companyName + item.shareGroupName + "\n");
            continue;
        }

        if (item.shareGroupName === 'Ordinary Shares' && item.action === '') {
            const issue_id = String(item.companyShareId);
            const issue_name = item.scrip;
            const company_name = item.companyName;
            const status_name = item.statusName;
            issue_names_and_ids.push({
                id: issue_id,
                name: issue_name,
                company_name: company_name,
                status_name: status_name,
            });
        }
    }

    return issue_names_and_ids;
}
async function re_apply() {
    const json_data = {
        appliedKitta: details.kitta,
        companyShareId: details.companyId,
        customerId: details.id,
        boid: details.dematNo.slice(-8),
        crnNumber: user.crnNumber,
        bankId: details.bankId,
        accountNumber: details.accountNumber,
        demat: details.dematNo,
        accountBranchId: details.accountBranchId,
        transactionPIN: user.pin,
    };

    const response1 = await fetch('https://webbackend.cdsc.com.np/api/meroShare/applicantForm/reapply/' + details.companyId, {
        method: 'GET',
        headers: headers,
    });

    if (response1.status !== 200) {
        throw new Error('Bad request: ' + response1.status);
    }

    const form_id = (await response1.json()).applicantFormId;

    const response2 = await fetch('https://webbackend.cdsc.com.np/api/meroShare/applicantForm/share/reapply/' + form_id, {
        method: 'POST',
        headers: headers,
        body: JSON.stringify(json_data),
    });

    if (response2.status !== 200) {
        throw new Error('Bad request: ' + response2.status);
    }

    const data = await response2.json();
    return data;
}

async function apply(headers, details) {
    const json_data = {
        crnNumber: user.crnNumber,
        demat: details.dematNo,
        accountNumber: details.accountNumber,
        customerId: details.id,
        accountBranchId: details.accountBranchId,
        transactionPIN: user.pin,
        bankId: details.bankId,
        // static fields
        boid: details.dematNo.slice(-8),
        appliedKitta: details.kitta,
        companyShareId: details.companyId,
    };

    const response = await fetch('https://webbackend.cdsc.com.np/api/meroShare/applicantForm/share/apply', {
        method: 'POST',
        headers: headers,
        body: JSON.stringify(json_data),
    });

    if (response.status !== 200) {
        return 'error in fetching message after applying';
    }

    const data = await response.json();
    return data;
}
// tested as object is passed as refrence in js 
function updateObject(target, source) {
    for (const key in source) {
        if (source.hasOwnProperty(key)) {
            target[key] = source[key];
        }
    }
}
async function apply_share(user, headers) {
    try {
        headers['Authorization'] = await login(user);
        const bank_id = await get_bank_id(headers);
        const bankDetails = await get_bank_details(headers, bank_id);
        updateObject(details, bankDetails);
        details['dematNo'] = await get_demat_no(headers);
        const applicable_share_list = await get_applicable_list(headers);

        if (applicable_share_list.length > 1) {
            for (let i = 0; i < applicable_share_list.length; i++) {
                messages.push(i + " : " + applicable_share_list[i]['company_name'] + "\n");
            }

            // Assuming you have a way to get user input in your environment
            const apply_share_index = parseInt(prompt("Please choose the share you want to apply"));
            details['companyId'] = applicable_share_list[apply_share_index]['id'];
        } else if (applicable_share_list.length === 0) {
            return -1;
        } else {
            details['companyId'] = applicable_share_list[0]['id'];
        }

        if ('reapply' in applicable_share_list[0]) {
            const response = await re_apply();
            messages.push(user['username'] + " re-apply " + response['message'] + "\n");
            return "reapply called";
        } else {
            const response = await apply(headers, details);
            messages.push(user['username'] + response['message'] + "\n");
            return "apply called";
        }
    } catch (e) {
        return -2;
    }
}

// tested ok
async function check_status(limit) {
    try {
        const json_data = {
            filterFieldParams: [
                {
                    key: 'companyShare.companyIssue.companyISIN.script',
                    alias: 'Scrip',
                },
                {
                    key: 'companyShare.companyIssue.companyISIN.company.name',
                    alias: 'Company Name',
                },
            ],
            page: 1,
            size: limit,
            searchRoleViewConstants: 'VIEW_APPLICANT_FORM_COMPLETE',
            filterDateParams: [
                {
                    key: 'appliedDate',
                    condition: '',
                    alias: '',
                    value: '',
                },
                {
                    key: 'appliedDate',
                    condition: '',
                    alias: '',
                    value: '',
                },
            ],
        };

        const response = await fetch('https://webbackend.cdsc.com.np/api/meroShare/applicantForm/active/search/', {
            method: 'POST',
            headers: headers,
            body: JSON.stringify(json_data),
        });

        if (response.status !== 200) {
            throw new Error('Bad request: ' + response.status);
        }

        const responseData = await response.json();
        const statuss = responseData.object.slice(0, limit);

        for (const status of statuss) {
            if (status.statusName === 'TRANSACTION_SUCCESS') {
                const detailResponse = await fetch('https://webbackend.cdsc.com.np/api/meroShare/applicantForm/report/detail/' + status.applicantFormId, {
                    method: 'GET',
                    headers: headers,
                });

                const data = await detailResponse.json();

                if (data.statusName === 'Alloted') {
                    messages.push(user.username + ' ' + status.companyName + ' ' + data.statusName);
                } else {
                    messages.push(user.username + ' ' + status.companyName + ' ' + data.statusName + '\n');
                }
            } else {
                messages.push(user.username + ' ' + status.companyName + ' ' + status.statusName);
            }
        }

        return statuss;
    } catch (error) {
        // Catch the exception and return a custom error response
        return { error_code: -1, error_message: error.toString() };
    }
}
async function bulk_apply() {
    // Assuming users is already defined or loaded in the JavaScript environment
    let rejected_count = 0;
    let success_count = 0;
    let output_message;
    const limit = 6;
    for (const user of users) {
        if ('dematNo' in user) {
            user['username'] = String(user['dematNo']).substring(8);
            user['clientId'] = await get_client_id(String(user['dematNo']).substring(3, 8));
        }

        output_message = await apply_share(user, headers); // Added await here

        if (output_message === -1) {
            const status = await check_status(limit); // Added await here
            if ('error_code' in status) {
                messages.push(status['error_message']);
            }
            await logout(); // Added await here
            continue;
        }

        if (output_message === -2) {
            messages.push(user['username'] + "  error occurred while applying, please check the account password and other details");
            continue;
        }

        messages.push(output_message + "\n");
        await logout(); // Added await here
    }

    if (output_message === -1) {
        messages.push("no issues found to apply" + "\n");
    }

    const user_messages = {};
    for (const message of messages) {
        const parts = message.split('  ');
        const username = parts[0];
        if (username in user_messages) {
            user_messages[username].push(message);
        } else {
            user_messages[username] = [message];
        }
    }

    const nested_messages = Object.values(user_messages);

    return {
        messages: nested_messages,
        rejected_count: rejected_count,
        success_count: success_count
    };
}
