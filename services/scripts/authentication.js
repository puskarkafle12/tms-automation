import { headers } from "./headers.js";  // Import function

export function login(user) {
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
export async function logout() {
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
