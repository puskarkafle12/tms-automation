import { headers } from "./headers.js";  // Import headers variable
import { get_client_id } from "./get_details.js";  // Import function to get client ID
import { apply_share } from "./apply_share.js";  // Import function for applying share
import { check_status } from "./check_status.js";  // Import function to check status
import { logout } from "./authentication.js";  
export async function bulk_apply() {
    // Assuming users is already defined or loaded in the JavaScript environment
    let messages=[]
    let output_message;
    let users = JSON.parse(localStorage.getItem("users")) || [];
    console.log(users)
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
            messages.push(user['username'] + "error occurred while applying, please check the account password and other details");
            continue;
        }

        messages.push(output_message + "\n");
        await logout();
    }

    if (output_message === -1) {
        messages.push("no issues found to apply" + "\n");
    }

    const user_messages = {};
    for (const message of messages) {
        const parts = message.split(' ');
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
    };
}
