const TOKEN_KEY = "tg-assistant-token";
const LEGACY_TOKEN_KEY = "tg-signer-token";

export const getToken = (): string | null => {
  if (typeof window === "undefined") return null;
  // Migration: check old key and migrate to new key
  const legacyToken = localStorage.getItem(LEGACY_TOKEN_KEY);
  if (legacyToken) {
    localStorage.setItem(TOKEN_KEY, legacyToken);
    localStorage.removeItem(LEGACY_TOKEN_KEY);
    return legacyToken;
  }
  return localStorage.getItem(TOKEN_KEY);
};

export const setToken = (token: string) => {
  if (typeof window === "undefined") return;
  localStorage.setItem(TOKEN_KEY, token);
};

export const clearToken = () => {
  if (typeof window === "undefined") return;
  localStorage.removeItem(TOKEN_KEY);
};

export const logout = () => {
  clearToken();
  if (typeof window !== "undefined") {
    // 强制刷新到登录页
    window.location.href = "/";
  }
};

