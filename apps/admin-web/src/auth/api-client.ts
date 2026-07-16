declare const process: { env: { NEXT_PUBLIC_API_BASE_URL?: string } };
import { clearAuthMemory, getAccessToken, getCsrfToken, setAccessToken, setCsrfToken } from "./token-store";
import type { AdminProfile, AdminSession, LoginResponse } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";
let refreshInFlight: Promise<LoginResponse> | null = null;

type Json = Record<string, unknown>;

async function request<T>(path: string, options: RequestInit & { csrf?: boolean } = {}, retry = true): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("content-type", "application/json");
  const token = getAccessToken();
  if (token) headers.set("authorization", `Bearer ${token}`);
  if (options.csrf) {
    const csrf = getCsrfToken();
    if (csrf) headers.set("x-csrf-token", csrf);
  }
  const response = await fetch(`${API_BASE}/api/v1/admin/auth${path}`, { ...options, headers, credentials: "include" });
  if (response.status === 401 && retry && path !== "/refresh") {
    const refreshed = await refreshOnce();
    if (refreshed.access_token) return request<T>(path, options, false);
  }
  if (!response.ok) throw new Error(`admin_auth_${response.status}`);
  return response.json() as Promise<T>;
}

export async function login(email: string, password: string): Promise<LoginResponse> {
  const result = await request<LoginResponse>("/login", { method: "POST", body: JSON.stringify({ email, password }) }, false);
  if (result.access_token) setAccessToken(result.access_token);
  if (result.csrf_token) setCsrfToken(result.csrf_token);
  return result;
}
export async function verifyMfa(challenge: string, code: string): Promise<LoginResponse> { const result = await request<LoginResponse>("/mfa/verify", { method: "POST", body: JSON.stringify({ challenge, code }) }, false); if (result.access_token) setAccessToken(result.access_token); if (result.csrf_token) setCsrfToken(result.csrf_token); return result; }
export async function refreshOnce(): Promise<LoginResponse> { refreshInFlight ??= request<LoginResponse>("/refresh", { method: "POST", body: JSON.stringify({}), csrf: true }, false).finally(() => { refreshInFlight = null; }); const result = await refreshInFlight; if (result.access_token) setAccessToken(result.access_token); if (result.csrf_token) setCsrfToken(result.csrf_token); return result; }
export async function logout(): Promise<void> { await request("/logout", { method: "POST", body: JSON.stringify({}), csrf: true }, false).catch(() => undefined); clearAuthMemory(); }
export const getProfile = (): Promise<AdminProfile> => request<AdminProfile>("/me");
export const getSessions = (): Promise<AdminSession[]> => request<AdminSession[]>("/sessions");
export const revokeSession = (sessionId: string): Promise<Json> => request<Json>(`/sessions/${sessionId}/revoke`, { method: "POST", body: JSON.stringify({}), csrf: true });
export const revokeOtherSessions = (): Promise<Json> => request<Json>("/sessions/revoke-other", { method: "POST", body: JSON.stringify({}), csrf: true });
export const revokeAllSessions = (): Promise<Json> => request<Json>("/sessions/revoke-all", { method: "POST", body: JSON.stringify({}), csrf: true });
export const changePassword = (current_password: string, new_password: string): Promise<Json> => request<Json>("/password/change", { method: "POST", body: JSON.stringify({ current_password, new_password }), csrf: true });
export const beginTotp = (): Promise<{ credential_id: string; otpauth_uri: string }> => request("/totp/begin", { method: "POST", body: JSON.stringify({}) });
export const confirmTotp = (credential_id: string, code: string): Promise<{ recovery_codes: string[] }> => request("/totp/confirm", { method: "POST", body: JSON.stringify({ credential_id, code }), csrf: true });
export const regenerateRecoveryCodes = (current_password: string, code: string): Promise<{ recovery_codes: string[] }> => request("/recovery-codes/regenerate", { method: "POST", body: JSON.stringify({ current_password, code }), csrf: true });
export const disableTotp = (current_password: string, code: string): Promise<Json> => request("/totp/disable", { method: "POST", body: JSON.stringify({ current_password, code }), csrf: true });
