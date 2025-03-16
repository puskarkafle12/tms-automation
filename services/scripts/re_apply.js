import { headers } from "./headers.js";  // Import function

export async function re_apply(user,details) {
    const bank_id = await get_bank_id(headers);
    details.bankId=bank_id
    const json_data = {
        appliedKitta: details.kitta,
        companyShareId: details.companyId,
        customerId: details[0].id,
        boid: details.dematNo.slice(-8),
        crnNumber: user.crnNumber,
        bankId: details.bankId,
        accountNumber: details[0].accountNumber,
        demat: details.dematNo,
        accountBranchId: details[0].accountBranchId,
        transactionPIN: user.pin,
        accountTypeId:details[0].accountTypeId
    };

    const response1 = await fetch('https://webbackend.cdsc.com.np/api/meroShare/applicantForm/reapply/' + details.companyId, {
        method: 'GET',
        headers: headers,
    });

    if (response1.status !== 200) {
        throw new Error('Bad request: in reapply get form id' + response1.status);
    }

    const form_id = (await response1.json()).applicantFormId;

    const response2 = await fetch('https://webbackend.cdsc.com.np/api/meroShare/applicantForm/share/reapply/' + form_id, {
        method: 'POST',
        headers: headers,
        body: JSON.stringify(json_data),
    });

    if (response2.status !== 201) {
            throw new Error('Bad request: ' + response2.status);
    }

    const data = await response2.json();
    return data;
}