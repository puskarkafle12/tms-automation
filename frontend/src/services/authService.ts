import axios from 'axios';
import { extractApiErrorMessage } from '../utils/apiError';
import { getApiUrl } from '../utils/api';

export type AuthUser = {
  id: number; username: string; role: 'user' | 'admin' | 'superuser'; permissions: string[];
  configured_permissions?: string[]; managed_by_user_id?: number | null; is_active: boolean;
  created_at?: string | null; updated_at?: string | null; last_login_at?: string | null;
  workspace_summary?: { tms_accounts: number; scheduled_orders: number; order_logs: number; backtest_runs: number };
};

const storeSession = (accessToken: string, user: AuthUser) => {
  localStorage.setItem('userId', String(user.id));
  localStorage.setItem('accessToken', accessToken);
  localStorage.setItem('authUser', JSON.stringify(user));
  axios.defaults.headers.common.Authorization = `Bearer ${accessToken}`;
};

const existingToken = localStorage.getItem('accessToken');
if (existingToken) axios.defaults.headers.common.Authorization = `Bearer ${existingToken}`;

export const authService = {
  login: async (username: string, password: string) => {
    try {
      const cleanUsername = username.trim();
      const cleanPassword = password;
      const response = await axios.post(`${getApiUrl()}/api/auth/login`, {
        username: cleanUsername,
        password: cleanPassword,
      }, {
        headers: {
          'Content-Type': 'application/json',
        },
      });

      const { message, access_token, user } = response.data as { message: string; access_token: string; user: AuthUser };

      if (message === 'Login successful') {
        storeSession(access_token, user);
        return user;
      }

      throw new Error(response.data?.detail || response.data?.message || 'Login failed');
    } catch (error) {
      throw new Error(extractApiErrorMessage(error));
    }
  },
  captcha: async () => (await axios.get(`${getApiUrl()}/api/auth/captcha`)).data as { captcha_id: string; image_data_url: string; prompt: string; expires_in_seconds: number },
  signup: async (username: string, password: string, captchaId: string, captchaAnswer: string) => {
    try {
      const response = await axios.post(`${getApiUrl()}/api/auth/signup`, {
        username: username.trim(), password, captcha_id: captchaId, captcha_answer: captchaAnswer.trim(),
      });
      const { access_token, user } = response.data as { access_token: string; user: AuthUser };
      storeSession(access_token, user);
      return user;
    } catch (error) { throw new Error(extractApiErrorMessage(error)); }
  },
  me: async () => {
    const response = await axios.get(`${getApiUrl()}/api/auth/me`);
    const user = response.data.user as AuthUser;
    localStorage.setItem('authUser', JSON.stringify(user));
    return user;
  },
  storedUser: (): AuthUser | null => {
    try { return JSON.parse(localStorage.getItem('authUser') || 'null') as AuthUser | null; } catch { return null; }
  },
  logout: async () => {
    try { await axios.post(`${getApiUrl()}/api/auth/logout`); } catch { /* clear locally even if expired */ }
    delete axios.defaults.headers.common.Authorization;
    localStorage.removeItem('accessToken'); localStorage.removeItem('userId'); localStorage.removeItem('authUser');
  },
};
