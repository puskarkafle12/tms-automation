

// tested ok
export async function check_status(limit) {
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