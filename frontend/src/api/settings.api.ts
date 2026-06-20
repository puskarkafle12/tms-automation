import axios from 'axios';
import { getApiUrl } from '../utils/api';
import type { ExecutionMode } from '../lib/monitorSettings';

export interface PortalSettings {
  monitor_interval_seconds: number;
  default_max_data_age_seconds: number | null;
  default_execution_mode: ExecutionMode | 'shadow' | 'validate_only';
  enable_scan_staggering: boolean;
  nepse_alpha_interval_seconds: number;
  monitor_tick_seconds: number;
  max_price_fetch_concurrency: number;
}

export interface PortalSettingsLimits {
  monitor_interval_seconds: { min: number; max: number };
  default_max_data_age_seconds: { min: number; max: number };
  nepse_alpha_interval_seconds: { min: number; max: number };
  monitor_tick_seconds: { min: number; max: number };
  max_price_fetch_concurrency: { min: number; max: number };
}

export interface PortalSettingsResponse {
  settings: PortalSettings;
  limits: PortalSettingsLimits;
}

export const fetchPortalSettings = async (): Promise<PortalSettingsResponse> => {
  const response = await axios.get<PortalSettingsResponse>(`${getApiUrl()}/api/portal-settings/`, {
    timeout: 8000,
  });
  return response.data;
};

export const savePortalSettings = async (settings: Partial<PortalSettings>): Promise<PortalSettingsResponse> => {
  const response = await axios.put<PortalSettingsResponse>(`${getApiUrl()}/api/portal-settings/`, settings, {
    timeout: 8000,
  });
  return response.data;
};
