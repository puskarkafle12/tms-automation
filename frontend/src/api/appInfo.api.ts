import axios from 'axios';
import type { ApiTimestamp } from './time.api';

export interface AppBuildInfo {
  deployed_at?: ApiTimestamp | string | null;
  git_commit?: string | null;
  source_version?: string | null;
}

export async function fetchAppBuildInfo(): Promise<AppBuildInfo> {
  const { data } = await axios.get<AppBuildInfo>('/app-info/');
  return data;
}
