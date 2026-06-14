import axios from 'axios';

export interface TmsAccount {
  client_id: string;
  display_name?: string | null;
  broker_no: string;
  password?: string;
  auto_login: boolean;
  session_status: string;
  session_message: string | null;
  last_updated: string | null;
}

export interface TmsAccountListResponse {
  accounts: TmsAccount[];
  logged_in_count: number;
  partial?: boolean;
  notice?: string;
}

export interface TmsAccountPayload {
  client_id: string;
  broker_no: string;
  password: string;
  auto_login: boolean;
}

export interface TmsAccountUpdatePayload {
  broker_no?: string;
  password?: string;
  auto_login?: boolean;
}

export interface LoggedInSession {
  client_id: string;
  display_name?: string | null;
  broker_no: string;
  status: string;
  message: string | null;
  last_updated: string | null;
}

export interface ScheduledOrder {
  order_id?: number;
  client_id: string;
  security_details?: Record<string, unknown>;
  script_name: string;
  price: number;
  qty: number;
  status?: string;
  order_type: string;
  last_updated?: string | null;
}

const DEFAULT_API_URL = window.location.origin;

export const getApiUrl = () => {
  const stored = localStorage.getItem('apiUrl')?.trim();
  if (!stored) {
    return DEFAULT_API_URL;
  }
  return stored.replace(/\/$/, '');
};

const sessionToAccount = (session: LoggedInSession): TmsAccount => ({
  client_id: session.client_id,
  display_name: session.display_name,
  broker_no: session.broker_no || '—',
  password: '',
  auto_login: true,
  session_status: session.status,
  session_message: session.message,
  last_updated: session.last_updated,
});

export const listLoggedInSessions = async (): Promise<LoggedInSession[]> => {
  const response = await axios.get<{
    logged_in_client_ids: string[];
    sessions?: LoggedInSession[];
  }>(`${getApiUrl()}/logged_in_clients/`);
  if (response.data.sessions?.length) {
    return response.data.sessions;
  }
  return (response.data.logged_in_client_ids || []).map((clientId) => ({
    client_id: clientId,
    broker_no: '—',
    status: 'logged_in',
    message: null,
    last_updated: null,
  }));
};

export const listTmsAccounts = async (): Promise<TmsAccountListResponse> => {
  try {
    const response = await axios.get<TmsAccountListResponse>(`${getApiUrl()}/tms-accounts/`);
    return response.data;
  } catch (error) {
    if (!axios.isAxiosError(error) || error.response?.status !== 404) {
      throw error;
    }

    const sessions = await listLoggedInSessions();
    const accounts = sessions.map(sessionToAccount);
    return {
      accounts,
      logged_in_count: accounts.length,
      partial: true,
      notice: 'TMS accounts API is unavailable. Restart the backend, then refresh. Showing logged-in sessions only.',
    };
  }
};

export const createTmsAccount = async (payload: TmsAccountPayload) => {
  const response = await axios.post(`${getApiUrl()}/tms-accounts/`, payload);
  return response.data;
};

export const updateTmsAccount = async (clientId: string, payload: TmsAccountUpdatePayload) => {
  const response = await axios.put(`${getApiUrl()}/tms-accounts/${encodeURIComponent(clientId)}`, payload);
  return response.data;
};

export const deleteTmsAccount = async (clientId: string) => {
  const response = await axios.delete(`${getApiUrl()}/tms-accounts/${encodeURIComponent(clientId)}`);
  return response.data;
};

export const listScheduledOrders = async (): Promise<ScheduledOrder[]> => {
  const response = await axios.get<{ scheduled_orders: ScheduledOrder[] }>(`${getApiUrl()}/scheduled_orders/`);
  return response.data.scheduled_orders || [];
};

export const createScheduledOrder = async (payload: ScheduledOrder) => {
  const response = await axios.post(`${getApiUrl()}/scheduled_orders/`, {
    client_id: payload.client_id,
    security_details: payload.security_details || {},
    script_name: payload.script_name,
    price: Number(payload.price),
    qty: Number(payload.qty),
    order_type: payload.order_type,
    status: payload.status || 'pending',
  });
  return response.data;
};

export const clearScheduledOrders = async () => {
  const response = await axios.delete(`${getApiUrl()}/scheduled_orders/`);
  return response.data;
};

export const loginTmsAccount = async (clientId: string) => {
  const response = await axios.post(`${getApiUrl()}/tms-accounts/${encodeURIComponent(clientId)}/login`);
  return response.data;
};

export const loginTmsWithCredentials = async (payload: {
  username: string;
  password: string;
  broker_no: string;
}) => {
  const response = await axios.post(`${getApiUrl()}/login/`, {
    username: payload.username,
    password: payload.password,
    broker_no: payload.broker_no,
    stock_symbol: '',
    request_per_sec: 5,
  });
  return response.data;
};
