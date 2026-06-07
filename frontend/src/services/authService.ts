import axios from 'axios';
import { extractApiErrorMessage } from '../utils/apiError';

const getApiUrl = () => localStorage.getItem('apiUrl') || window.location.origin;

export const authService = {
  login: async (username: string, password: string) => {
    try {
      const cleanUsername = username.trim();
      const cleanPassword = password.trim();
      const response = await axios.post(`${getApiUrl()}/frontend-login`, {
        username: cleanUsername,
        password: cleanPassword,
      }, {
        headers: {
          'Content-Type': 'application/json',
        },
      });

      const { message, user_id, access_token } = response.data;

      if (message === 'Login successful') {
        localStorage.setItem('userId', String(user_id));
        localStorage.setItem('accessToken', access_token);
        return true;
      }

      throw new Error(response.data?.detail || response.data?.message || 'Login failed');
    } catch (error) {
      throw new Error(extractApiErrorMessage(error));
    }
  },
};
