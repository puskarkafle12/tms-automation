import axios from 'axios';
const apiUrl = process.env.REACT_APP_API_URL;

const BASE_URL = apiUrl+'/frontend-login'; // Replace with your actual API endpoint for frontend login

export const authService = {
  login: async (username: string, password: string) => {
    try {
      const response = await axios.post(BASE_URL, {
        username,
        password,
      }, {
        headers: {
          'Content-Type': 'application/json',
        },
      });

      console.log('Login successful (simulated):', response.data);

      // Handle successful login logic
      const { message, user_id, access_token } = response.data; // Destructure response data

      if (message === 'Login successful') {
        // Store user ID and access token (replace with your preferred storage mechanism)
        localStorage.setItem('userId', user_id);
        localStorage.setItem('accessToken', access_token);

        // Handle successful login (e.g., redirect to protected content)
        console.log('Login successful! User ID:', user_id);

        return true; // Indicate successful login (replace with actual return value)
      } else {
        console.error('Login failed:', response.data.message); // Handle failed login based on response message
        return false; // Indicate failed login
      }
    } catch (error) {
      console.error('Login error:', error);
      throw error; // Re-throw the error for handling in the component
    }
  },
};
