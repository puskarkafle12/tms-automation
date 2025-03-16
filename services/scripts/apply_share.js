
import { login } from "./authentication.js";  // Import login function
import { get_bank_id } from "./get_details.js";  // Import function to get bank ID
import { get_bank_details } from "./get_details.js";  // Import function to get bank details
import { updateObject } from "./get_details.js";  // Import updateObject function
import { get_demat_no } from "./get_details.js";  // Import function to get demat number
import { get_applicable_list } from "./get_details.js";  // Import function to get applicable share list
import { re_apply } from "./re_apply.js";  // Import function to handle reapply logic


export async function apply_share(user, headers) {
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
            const apply_share_index = parseInt(prompt("Please choose the share you want to apply"));
            details['companyId'] = applicable_share_list[apply_share_index]['id'];
        } else if (applicable_share_list.length === 0) {
            return -1;
        } else {
            details['companyId'] = applicable_share_list[0]['id'];
        }

        if ('reapply' in applicable_share_list[0]) {
            const response = await re_apply(details,user);
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


export async function apply(headers, details) {
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