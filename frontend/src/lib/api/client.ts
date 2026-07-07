// Core API client - shared request infrastructure
// Auto-generated from api.ts split

import type { TokenResponse } from "../types";

const API_BASE = import.meta.env.VITE_API_BASE || "/api";

const toRecord = (headers?: HeadersInit): Record<string, string> => {
  if (!headers) return {};
  if (headers instanceof Headers) {
    return Object.fromEntries(headers.entries());
  }
  if (Array.isArray(headers)) {
    return Object.fromEntries(headers);
  }
  return headers as Record<string, string>;
};

async function request<T>(
  path: string,
  options: RequestInit = {},
  token?: string | null
): Promise<T> {
  const mergedHeaders: Record<string, string> = {
    ...toRecord(options.headers),
    "Content-Type": "application/json",
  };
  if (token) {
    mergedHeaders["Authorization"] = `Bearer ${token}`;
  }
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: mergedHeaders,
    cache: "no-store", // 禁用缓存，确保获取最新数据
  });
  if (!res.ok) {
    // 尝试解析 JSON 错误响应
    let errorMessage = "请求失败";
    let errorCode: string | undefined;
    try {
      const errorData = await res.json();
      if (errorData && typeof errorData === "object") {
        const detail = errorData.detail;
        if (typeof detail === "string") {
          errorMessage = detail;
        } else if (Array.isArray(detail)) {
          // FastAPI validation error format: [{loc, msg, type}]
          errorMessage = detail.map((d: any) => d.msg || JSON.stringify(d)).join('; ');
        } else if (detail && typeof detail === "object") {
          errorMessage = JSON.stringify(detail);
        } else {
          errorMessage = errorData.message || JSON.stringify(errorData);
        }
        errorCode = errorData.code;
      } else {
        errorMessage = JSON.stringify(errorData);
      }
    } catch {
      // 如果不是 JSON，使用文本
      try {
        errorMessage = await res.text() || "请求失败";
      } catch {
        // 忽略
      }
    }

    // 如果是认证失败 (401) 且请求携带了 token，清除 token 并跳转到登录页
    // 注意：登录相关请求（不带 token）不应触发跳转
    if (res.status === 401 && token) {
      if (typeof window !== "undefined") {
        const currentToken = localStorage.getItem("tg-assistant-token");
        if (currentToken === token) {
          localStorage.removeItem("tg-assistant-token");
          window.location.href = "/";
        }
      }
    }

    const err: any = new Error(errorMessage);
    err.status = res.status;
    if (errorCode) {
      err.code = errorCode;
    }
    throw err;
  }
  if (res.status === 204) {
    return {} as T;
  }
  return res.json();
}
