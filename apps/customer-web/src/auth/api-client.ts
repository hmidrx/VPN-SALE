import { loadCustomerConfig } from "../config/public-config";
import { clearOnAuthFailure, CustomerApiError } from "./error-map";
import { applyAuthMemory, clearAuthMemory, getAccessToken, getCsrfToken } from "./token-store";
import type { AuthResponse, CustomerProfile, CustomerSession } from "./types";
type Json = Record<string, unknown>;
type Fetcher = typeof fetch;
const config = loadCustomerConfig();
let refreshInFlight: Promise<AuthResponse> | null = null;
export function correlationId(): string { return `cust-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`; }
function headers(input?: HeadersInit, csrf = false): Headers { const h = new Headers(input); h.set("content-type", "application/json"); h.set("x-request-id", correlationId()); const token = getAccessToken(); if (token) h.set("authorization", `Bearer ${token}`); const csrfToken = getCsrfToken(); if (csrf && csrfToken) h.set("x-csrf-token", csrfToken); return h; }
async function parseError(response: Response): Promise<never> { const retry = response.headers.get("retry-after"); throw new CustomerApiError(response.status, response.status === 429 ? "rate_limited" : response.status >= 500 ? "service_unavailable" : response.status === 403 ? "csrf_failed" : "unauthorized", retry ? Number(retry) : undefined); }
async function request<T>(path: string, options: RequestInit & { csrf?: boolean } = {}, retry = true, fetcher: Fetcher = fetch): Promise<T> { const response = await fetcher(`${config.apiBaseUrl}/api/v1/customer/auth${path}`, { ...options, headers: headers(options.headers, options.csrf), credentials: "include" }); if (response.status === 401 && retry && path !== "/refresh") { try { await refreshOnce(fetcher); return request<T>(path, options, false, fetcher); } catch (error) { clearOnAuthFailure(error); throw error; } } if (!response.ok) await parseError(response); return response.json() as Promise<T>; }
export async function telegramLogin(initData: string, fetcher: Fetcher = fetch): Promise<AuthResponse> { const result = await request<AuthResponse>("/telegram-mini-app", { method: "POST", body: JSON.stringify({ init_data: initData }) }, false, fetcher); applyAuthMemory(result); return result; }
export async function refreshOnce(fetcher: Fetcher = fetch): Promise<AuthResponse> { refreshInFlight ??= request<AuthResponse>("/refresh", { method: "POST", body: JSON.stringify({}), csrf: true }, false, fetcher).finally(() => { refreshInFlight = null; }); try { const result = await refreshInFlight; applyAuthMemory(result); return result; } catch (error) { clearAuthMemory(); throw error; } }
export async function ensureCsrf(fetcher: Fetcher = fetch): Promise<AuthResponse> { const result = await request<AuthResponse>("/csrf", {}, true, fetcher); applyAuthMemory(result); return result; }
export async function logout(fetcher: Fetcher = fetch): Promise<void> { await request<Json>("/logout", { method: "POST", body: JSON.stringify({}), csrf: true }, false, fetcher).catch(() => undefined); clearAuthMemory(); }
export const getProfile = (fetcher?: Fetcher): Promise<CustomerProfile> => request<CustomerProfile>("/me", {}, true, fetcher);
export const getSessions = (fetcher?: Fetcher): Promise<CustomerSession[]> => request<CustomerSession[]>("/sessions", {}, true, fetcher);
export const revokeSession = (sessionId: string, fetcher?: Fetcher): Promise<Json> => request<Json>(`/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE", body: JSON.stringify({}), csrf: true }, true, fetcher);
export const revokeOtherSessions = (fetcher?: Fetcher): Promise<Json> => request<Json>("/sessions/revoke-others", { method: "POST", body: JSON.stringify({}), csrf: true }, true, fetcher);
export async function revokeAllSessions(fetcher?: Fetcher): Promise<Json> { const out = await request<Json>("/sessions/revoke-all", { method: "POST", body: JSON.stringify({}), csrf: true }, true, fetcher); clearAuthMemory(); return out; }
