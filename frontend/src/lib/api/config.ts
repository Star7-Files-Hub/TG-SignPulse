// config API module
// Auto-generated from api.ts split

import { request, API_BASE } from './client';

// ============ 配置管理 ============

export const listConfigTasks = (token: string) =>
  request<{ sign_tasks: string[]; monitor_tasks: string[]; total: number }>("/config/tasks", {}, token);

export const exportSignTask = async (token: string, taskName: string, accountName?: string) => {
  const params = new URLSearchParams();
  if (accountName) params.append("account_name", accountName);
  const url = `${API_BASE}/config/export/sign/${taskName}${params.toString() ? `?${params.toString()}` : ""}`;
  const res = await fetch(url, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    let errorMessage = "Export failed";
    try {
      const errorData = await res.json();
      errorMessage = errorData.detail || errorData.message || JSON.stringify(errorData);
    } catch {
      errorMessage = await res.text() || "Export failed";
    }
    throw new Error(errorMessage);
  }
  return res.text();
};

export const importSignTask = (
  token: string,
  configJson: string,
  taskName?: string,
  accountName?: string
) =>
  request<{ success: boolean; task_name: string; message: string }>("/config/import/sign", {
    method: "POST",
    body: JSON.stringify({ config_json: configJson, task_name: taskName, account_name: accountName }),
  }, token);

export const exportAllConfigs = async (token: string) => {
  const res = await fetch(`${API_BASE}/config/export/all`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    let errorMessage = "Export failed";
    try {
      const errorData = await res.json();
      errorMessage = errorData.detail || errorData.message || JSON.stringify(errorData);
    } catch {
      errorMessage = await res.text() || "Export failed";
    }
    throw new Error(errorMessage);
  }
  return res.text();
};

export const importAllConfigs = (token: string, configJson: string, overwrite = false) =>
  request<{
    signs_imported: number;
    signs_skipped: number;
    monitors_imported: number;
    monitors_skipped: number;
    settings_imported: number;
    errors: string[];
    message: string;
  }>("/config/import/all", {
    method: "POST",
    body: JSON.stringify({ config_json: configJson, overwrite }),
  }, token);

export const deleteSignConfig = (token: string, taskName: string, accountName?: string) => {
  const params = new URLSearchParams();
  if (accountName) params.append("account_name", accountName);
  const url = `/config/sign/${taskName}${params.toString() ? `?${params.toString()}` : ""}`;
  return request<{ success: boolean; message: string }>(url, {
    method: "DELETE",
  }, token);
};

// ============ AI 配置 ============

export interface AIConfig {
  has_config: boolean;
  base_url?: string;
  model?: string;
  api_key_masked?: string;
}

export interface ChangeUsernameResponse {
  success: boolean;
  message: string;
  access_token?: string;
}

export interface AITestResult {
  success: boolean;
  message: string;
  model_used?: string;
}

export const getAIConfig = (token: string) =>
  request<AIConfig>("/config/ai", {}, token);

export const saveAIConfig = (
  token: string,
  config: { api_key?: string; base_url?: string; model?: string }
) =>
  request<{ success: boolean; message: string }>("/config/ai", {
    method: "POST",
    body: JSON.stringify(config),
  }, token);

export const testAIConnection = (token: string) =>
  request<AITestResult>("/config/ai/test", {
    method: "POST",
  }, token);

export const deleteAIConfig = (token: string) =>
  request<{ success: boolean; message: string }>("/config/ai", {
    method: "DELETE",
  }, token);

// ============ 全局设置 ============

export interface GlobalSettings {
  sign_interval?: number | null;  // null 表示随机 1-120 秒
  log_retention_days?: number;    // 日志保留天数，默认 7
  data_dir?: string | null;
  global_proxy?: string | null;
  tg_global_concurrency?: number | null;
  telegram_bot_notify_enabled?: boolean;
  telegram_bot_login_notify_enabled?: boolean;
  telegram_bot_task_failure_enabled?: boolean;
  telegram_bot_token?: string | null;
  telegram_bot_chat_id?: string | null;
  telegram_bot_message_thread_id?: number | null;
  auto_block_private_chat?: boolean;
  timezone?: string;
}

export const getGlobalSettings = (token: string) =>
  request<GlobalSettings>("/config/settings", {}, token);

export const saveGlobalSettings = (token: string, settings: GlobalSettings) =>
  request<{ success: boolean; message: string }>("/config/settings", {
    method: "POST",
    body: JSON.stringify(settings),
  }, token);

// ============ Telegram API 配置 ============

export interface TelegramConfig {
  api_id: string;
  api_hash: string;
  is_custom: boolean;
  default_api_id: string;
  default_api_hash: string;
}

export const getTelegramConfig = (token: string) =>
  request<TelegramConfig>("/config/telegram", {}, token);

export const saveTelegramConfig = (
  token: string,
  config: { api_id: string; api_hash: string }
) =>
  request<{ success: boolean; message: string }>("/config/telegram", {
    method: "POST",
    body: JSON.stringify(config),
  }, token);

export const resetTelegramConfig = (token: string) =>
  request<{ success: boolean; message: string }>("/config/telegram", {
    method: "DELETE",
  }, token);

// ============ 控制台日志 ============

export interface LoginAuditLog {
  id: number;
  username: string;
  ip_address?: string | null;
  user_agent?: string | null;
  detail?: string | null;
  success: boolean;
  created_at: string;
}

export interface TaskHistoryLog {
  id: number;
  account_name: string;
  task_name: string;
  message: string;
  summary?: string | null;
  bot_message?: string | null;
  success: boolean;
  created_at: string;
  flow_line_count: number;
}

export interface TaskHistoryLogDetail extends TaskHistoryLog {
  flow_logs: string[];
  flow_truncated: boolean;
  last_target_message?: string | null;
}

export const getLoginAuditLogs = (
  token: string,
  options?: {
    limit?: number;
    date?: string;
  }
) => {
  const params = new URLSearchParams();
  if (options?.limit) params.append("limit", String(options.limit));
  if (options?.date) params.append("date", options.date);
  const query = params.toString();
  return request<LoginAuditLog[]>(`/logs/login${query ? `?${query}` : ""}`, {}, token);
};

export const clearLoginAuditLogs = (token: string) =>
  request<{ success: boolean; cleared: number; message: string }>(
    "/logs/login/clear",
    { method: "POST" },
    token
  );

export const deleteLoginAuditLog = (token: string, logId: number) =>
  request<{ success: boolean; message: string }>(
    `/logs/login/${logId}`,
    { method: "DELETE" },
    token
  );

export const getTaskHistoryLogs = (
  token: string,
  options?: {
    limit?: number;
    account_name?: string;
    date?: string;
  }
) => {
  const params = new URLSearchParams();
  if (options?.limit) params.append("limit", String(options.limit));
  if (options?.account_name) params.append("account_name", options.account_name);
  if (options?.date) params.append("date", options.date);
  const query = params.toString();
  return request<TaskHistoryLog[]>(`/logs/tasks${query ? `?${query}` : ""}`, {}, token);
};

export const getTaskHistoryLogDetail = (
  token: string,
  options: {
    account_name: string;
    task_name: string;
    created_at: string;
  }
) => {
  const params = new URLSearchParams();
  params.append("account_name", options.account_name);
  params.append("task_name", options.task_name);
  params.append("created_at", options.created_at);
  return request<TaskHistoryLogDetail>(`/logs/tasks/item?${params.toString()}`, {}, token);
};

export const clearTaskHistoryLogs = (token: string) =>
  request<{ success: boolean; cleared: number; message: string }>(
    "/logs/tasks/clear",
    { method: "POST" },
    token
  );

export const deleteTaskHistoryLog = (
  token: string,
  options: {
    account_name: string;
    task_name: string;
    created_at: string;
  }
) => {
  const params = new URLSearchParams();
  params.append("account_name", options.account_name);
  params.append("task_name", options.task_name);
  params.append("created_at", options.created_at);
  return request<{ success: boolean; message: string }>(
    `/logs/tasks/item?${params.toString()}`,
    { method: "DELETE" },
    token
  );
};


// ============ 用户设置 ============

export const changePassword = (token: string, oldPassword: string, newPassword: string) =>
  request<{ success: boolean; message: string }>("/user/password", {
    method: "PUT",
    body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
  }, token);

export const getTOTPStatus = (token: string) =>
  request<{ enabled: boolean; secret?: string }>("/user/totp/status", {}, token);

export const setupTOTP = (token: string) =>
  request<{ enabled: boolean; secret: string }>("/user/totp/setup", {
    method: "POST",
  }, token);

export const fetchTOTPQRCode = async (token: string) => {
  const res = await fetch(`${API_BASE}/user/totp/qrcode`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!res.ok) {
    let errorMessage = "QR code fetch failed";
    try {
      const errorData = await res.json();
      errorMessage = errorData.detail || errorData.message || JSON.stringify(errorData);
    } catch {
      errorMessage = await res.text() || errorMessage;
    }
    throw new Error(errorMessage);
  }
  const blob = await res.blob();
  return window.URL.createObjectURL(blob);
};

export const enableTOTP = (token: string, totpCode: string) =>
  request<{ success: boolean; message: string }>("/user/totp/enable", {
    method: "POST",
    body: JSON.stringify({ totp_code: totpCode }),
  }, token);

export const disableTOTP = (token: string, totpCode: string) =>
  request<{ success: boolean; message: string }>("/user/totp/disable", {
    method: "POST",
    body: JSON.stringify({ totp_code: totpCode }),
  }, token);

export const changeUsername = (token: string, newUsername: string, password: string) =>
  request<ChangeUsernameResponse>("/user/username", {
    method: "PUT",
    body: JSON.stringify({ new_username: newUsername, password: password }),
  }, token);


// ============ 账号日志 ============

export interface AccountLog {
  id: number;
  account_name: string;
  task_name: string;
  message: string;
  summary?: string;
  bot_message?: string;
  success: boolean;
  created_at: string;
}

export const getAccountLogs = (token: string, accountName: string, limit: number = 100) =>
  request<AccountLog[]>(`/accounts/${accountName}/logs?limit=${limit}`, {}, token);

export const getRecentAccountLogs = (token: string, limit: number = 50) =>
  request<AccountLog[]>(`/accounts/logs/recent?limit=${limit}`, {}, token);

export const clearRecentAccountLogs = (token: string) =>
  request<{ success: boolean; cleared: number; message: string; code?: string }>(
    "/accounts/logs/clear",
    { method: "POST" },
    token
  );

export const clearAccountLogs = (token: string, accountName: string) =>
  request<{ success: boolean; cleared: number; message: string; code?: string }>(
    `/accounts/${accountName}/logs/clear`,
    { method: "POST" },
    token
  );

export const exportAccountLogs = async (token: string, accountName: string) => {
  const res = await fetch(`${API_BASE}/accounts/${accountName}/logs/export`, {
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });
  if (!res.ok) throw new Error("Export failed");
  const blob = await res.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `logs_${accountName}.txt`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
};

