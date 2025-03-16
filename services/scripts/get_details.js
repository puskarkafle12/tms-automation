import { headers } from "./headers.js";  // Import function

export async function get_applicable_list(headers) {
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


// tested as object is passed as refrence in js 
export function updateObject(target, source) {
    for (const key in source) {
        if (source.hasOwnProperty(key)) {
            target[key] = source[key];
        }
    }
}
// tested
export async function get_client_id(code) {
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
export async function get_bank_id(headers) {
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
export async function get_bank_details(headers, bank_id) {
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
export async function get_demat_no(headers) {
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
