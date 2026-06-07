import axios from 'axios';
import { getApiUrl } from '../utils/api';

export interface MarketStatus {
  nepal_time: string;
  nepal_time_formatted: string;
  nepal_date_formatted: string;
  timezone: string;
  is_trading_day: boolean;
  is_pre_open: boolean;
  is_continuous_session: boolean;
  market_hours_open: boolean;
  market_phase: 'open' | 'pre_open' | 'closed' | 'closed_weekend';
  tms_session_active: boolean;
  tms_session_message: string;
  market_live: boolean;
  market_live_from_api: boolean | null;
  client_id: string | null;
  broker_no: string | null;
}

export const fetchMarketStatus = async (): Promise<MarketStatus> => {
  try {
    const response = await axios.get<MarketStatus>(`${getApiUrl()}/market-status/`, {
      timeout: 8000,
    });
    return response.data;
  } catch {
    throw new Error('Market status unavailable');
  }
};
