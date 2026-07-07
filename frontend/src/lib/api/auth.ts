// auth API module
// Auto-generated from api.ts split

import { request, API_BASE } from './client';
import type { TokenResponse } from '../types';

// ============ 认证 ============

export const login = (payload: {
  username: string;
  password: string;
  totp_code?: string;
}) =>
  request<TokenResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const getMe = (token: string) =>
  request("/auth/me", {}, token);

export const resetTOTP = (payload: { username: string; password: string }) =>
  request<{ success: boolean; message: string }>("/auth/reset-totp", {
    method: "POST",
    body: JSON.stringify(payload),
  });


// ============ 账号管理（重构版）============

export interface LoginStartRequest {
  account_name: string;
  phone_number: string;
  proxy?: string;
}

export interface LoginStartResponse {
  phone_code_hash: string;
  phone_number: string;
  account_name: string;
  message: string;
}

export interface LoginVerifyRequest {
  account_name: string;
  phone_number: string;
  phone_code: string;
  phone_code_hash: string;
  password?: string;
  proxy?: string;
}

export interface LoginVerifyResponse {
  success: boolean;
  user_id?: number;
  first_name?: string;
  username?: string;
  message: string;
}

export interface QrLoginStartRequest {
  account_name: string;
  proxy?: string;
}

export interface QrLoginStartResponse {
  login_id: string;
  qr_uri: string;
  qr_image?: string | null;
  expires_at: string;
}

export interface QrLoginStatusResponse {
  status: string;
  expires_at?: string;
  message?: string;
  account?: AccountInfo | null;
  user_id?: number;
  first_name?: string;
  username?: string;
}

export interface QrLoginCancelResponse {
  success: boolean;
  message: string;
}

export interface QrLoginPasswordRequest {
  login_id: string;
  password: string;
}

export interface QrLoginPasswordResponse {
  success: boolean;
  message: string;
  account?: AccountInfo | null;
  user_id?: number;
  first_name?: string;
  username?: string;
}

export interface AccountInfo {
  name: string;
  session_file: string;
  exists: boolean;
  size: number;
  remark?: string | null;
  proxy?: string | null;
  status?: "connected" | "invalid" | "checking" | "error" | string;
  status_message?: string | null;
  status_code?: string | null;
  status_checked_at?: string | null;
  needs_relogin?: boolean;
}

export interface AccountStatusCheckRequest {
  account_names?: string[];
  timeout_seconds?: number;
}

export interface AccountStatusItem {
  account_name: string;
  ok: boolean;
  status: "connected" | "invalid" | "error" | "not_found" | string;
  message?: string;
  code?: string;
  checked_at?: string;
  needs_relogin?: boolean;
  user_id?: number;
}

export interface AccountStatusCheckResponse {
  results: AccountStatusItem[];
}

export const startAccountLogin = (token: string, data: LoginStartRequest) =>
  request<LoginStartResponse>("/accounts/login/start", {
    method: "POST",
    body: JSON.stringify(data),
  }, token);

export const verifyAccountLogin = (token: string, data: LoginVerifyRequest) =>
  request<LoginVerifyResponse>("/accounts/login/verify", {
    method: "POST",
    body: JSON.stringify(data),
  }, token);

export const listAccounts = (token: string) =>
  request<{ accounts: AccountInfo[]; total: number }>("/accounts", {}, token);

export const checkAccountsStatus = (token: string, data: AccountStatusCheckRequest) =>
  request<AccountStatusCheckResponse>("/accounts/status/check", {
    method: "POST",
    body: JSON.stringify(data),
  }, token);

export const deleteAccount = (token: string, accountName: string) =>
  request<{ success: boolean; message: string }>(`/accounts/${accountName}`, {
    method: "DELETE",
  }, token);

export const checkAccountExists = (token: string, accountName: string) =>
  request<{ exists: boolean; account_name: string }>(`/accounts/${accountName}/exists`, {}, token);

export const updateAccount = (
  token: string,
  accountName: string,
  data: {
    new_account_name?: string | null;
    remark?: string | null;
    proxy?: string | null;
  }
) =>
  request<{ success: boolean; message: string; account?: AccountInfo | null }>(`/accounts/${accountName}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  }, token);

export const startQrLogin = (token: string, data: QrLoginStartRequest) =>
  request<QrLoginStartResponse>("/accounts/qr/start", {
    method: "POST",
    body: JSON.stringify(data),
  }, token);

export const getQrLoginStatus = (token: string, loginId: string) =>
  request<QrLoginStatusResponse>(`/accounts/qr/status?login_id=${encodeURIComponent(loginId)}`, {}, token);

export const cancelQrLogin = (token: string, loginId: string) =>
  request<QrLoginCancelResponse>("/accounts/qr/cancel", {
    method: "POST",
    body: JSON.stringify({ login_id: loginId }),
  }, token);

export const submitQrPassword = (token: string, data: QrLoginPasswordRequest) =>
  request<QrLoginPasswordResponse>("/accounts/qr/password", {
    method: "POST",
    body: JSON.stringify(data),
  }, token);

