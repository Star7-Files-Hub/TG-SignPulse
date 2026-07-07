// monitors API module
// Auto-generated from api.ts split

import { request, API_BASE } from './client';

// ============ 独立监听器 (Monitors) ============

export interface ForwardTarget { account: string; forward_chat_id: number; }

export interface Monitor {
  id: string;
  name: string;
  account_names: string[];
  forward_targets?: ForwardTarget[];
  source_chat_id?: number | null;
  chat_ids: number[];
  keywords: string[];
  match_mode: string;
  action: string;
  forward_chat_id?: number | null;
  forward_thread_id?: number | null;
  dedup_seconds?: number;
  fuzzy_threshold?: number;
  fuzzy_cooldown_minutes?: number;
  smart_dedup?: boolean;
  forward_with_button?: boolean;
  smart_dedup_pattern?: string;
  extract_pattern?: string | null;
  grab_text_template?: string;
  red_packet_delay?: number;
  button_names?: string[];
  auto_reply_list?: string[];
  auto_reply_delay?: number;
  enabled: boolean;
}

export const listMonitors = (token: string) =>
  request<Monitor[]>("/monitors", {}, token);

export const createMonitor = (token: string, data: Partial<Monitor>) =>
  request<Monitor>("/monitors", { method: "POST", body: JSON.stringify(data) }, token);

export const updateMonitor = (token: string, id: string, data: Partial<Monitor>) =>
  request<Monitor>(`/monitors/${id}`, { method: "PUT", body: JSON.stringify(data) }, token);

export const deleteMonitor = (token: string, id: string) =>
  request<{ ok: boolean }>(`/monitors/${id}`, { method: "DELETE" }, token);

export const toggleMonitor = (token: string, id: string) =>
  request<{ ok: boolean; enabled: boolean }>(`/monitors/${id}/toggle`, { method: "PUT" }, token);

export const getMonitorLogs = (token: string, limit: number = 200, since: string = '') =>
  request<{ time: string; monitor_id: string; monitor_name: string; event_type: string; message: string; chat_title: string; msg_preview: string }[]>(
    `/monitors/logs?limit=${limit}${since ? `&since=${encodeURIComponent(since)}` : ''}`, {}, token);

