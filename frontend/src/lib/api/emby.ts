// emby API module
// Auto-generated from api.ts split

import { request, API_BASE } from './client';

// ============ Emby 保号 ============

export interface EmbyAccount {
  server_url: string;
  username: string;
  password: string;
  user_agent?: string;
}

export interface EmbyTask {
  id: string;
  name: string;
  accounts: EmbyAccount[];
  watch_minutes: number;
  mark_watched: boolean;
  time_range: string;
  enabled: boolean;
  last_run?: string | null;
  last_result?: string | null;
}

export const listEmbyTasks = (token: string) =>
  request<EmbyTask[]>("/emby", {}, token);

export const createEmbyTask = (token: string, data: Partial<EmbyTask>) =>
  request<EmbyTask>("/emby", { method: "POST", body: JSON.stringify(data) }, token);

export const updateEmbyTask = (token: string, id: string, data: Partial<EmbyTask>) =>
  request<EmbyTask>(`/emby/${id}`, { method: "PUT", body: JSON.stringify(data) }, token);

export const deleteEmbyTask = (token: string, id: string) =>
  request<{ ok: boolean }>(`/emby/${id}`, { method: "DELETE" }, token);

export const runEmbyTask = (token: string, id: string) =>
  request<{ ok: boolean; account: string; item: string; duration: number; success: boolean; error: string }[]>(
    `/emby/${id}/run`, { method: "POST" }, token);

export const getEmbyLogs = (token: string, limit: number = 50) =>
  request<any[]>(`/emby/logs?limit=${limit}`, {}, token);

export const getAllLogs = (token: string, params: { level?: string; module?: string; search?: string; limit?: number }) => {
  const qs = new URLSearchParams({ limit: String(params.limit || 200) })
  if (params.level) qs.set('level', params.level)
  if (params.module) qs.set('module', params.module)
  if (params.search) qs.set('search', params.search)
  return request<{ total: number; logs: any[] }>(`/logs/all?${qs}`, {}, token)
}

