import axios from 'axios';
import { getApiUrl } from '../utils/api';

export interface ApiTimestamp {
  utc: string;
  npt: string;
  display: string;
  date: string;
  time: string;
  timezone: string;
}

export interface ServerTimePayload {
  now: ApiTimestamp;
  today_npt: string;
  timezone: string;
}

let cachedServerTime: ServerTimePayload | null = null;
let cachedAtMs = 0;
const CACHE_MS = 4000;

export const getCachedServerTime = () => cachedServerTime;

export const fetchServerTime = async (force = false): Promise<ServerTimePayload> => {
  if (!force && cachedServerTime && Date.now() - cachedAtMs < CACHE_MS) {
    return cachedServerTime;
  }
  const response = await axios.get<ServerTimePayload>(`${getApiUrl()}/api/time/`, {
    timeout: 8000,
  });
  cachedServerTime = response.data;
  cachedAtMs = Date.now();
  return response.data;
};

export const serverUtcToMs = (timestamp?: ApiTimestamp | null): number | null => {
  if (!timestamp?.utc) {
    return null;
  }
  const parsed = Date.parse(timestamp.utc);
  return Number.isFinite(parsed) ? parsed : null;
};
