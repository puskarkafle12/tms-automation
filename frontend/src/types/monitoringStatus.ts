export type MonitorPhase = 'stopped' | 'waiting_hours' | 'waiting_session' | 'active' | 'armed';

export interface RemoteGrabberStatus {
  session_id: string;
  client_id: string;
  stock_symbol: string;
  scan_count: number;
  phase: MonitorPhase | string;
  status_message: string;
  started_at: string | null;
}
