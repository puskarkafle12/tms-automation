import axios from 'axios';
import { getApiUrl } from '../utils/api';
import type { ApiTimestamp } from './time.api';

export interface MarketStatus {
  server_time: ApiTimestamp;
  today_npt: string;
  nepal_time: string;
  nepal_time_formatted: string;
  nepal_date_formatted: string;
  nepal_time_display: string;
  timezone: string;
  market_hours_label?: string;
  market_poll_hours_label?: string;
  next_market_poll_at?: ApiTimestamp;
  is_trading_day: boolean;
  is_pre_open: boolean;
  is_continuous_session: boolean;
  market_hours_open: boolean;
  market_polling_window?: boolean;
  market_live_poll_interval_seconds?: number;
  market_status_source?: string;
  dna_status_source?: string;
  market_phase: 'open' | 'pre_open' | 'closed' | 'checking';
  tms_session_active: boolean;
  tms_session_message: string;
  dna_status?: string | null;
  market_live: boolean;
  market_live_from_api: boolean | null;
  exchange_market_phase?: 'open' | 'pre_open' | 'closed' | null;
  exchange_current_sessions?: string[];
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
