import type { ApiErrorCode, CustomerAuthState } from "./types";
export type CustomerAuthEvent = "DETECT_TELEGRAM" | "NO_TELEGRAM" | "UNSUPPORTED" | "AUTH_START" | "AUTH_OK" | "REFRESH_START" | "LOGOUT" | "EXPIRE" | "NETWORK_FAIL" | "SERVICE_FAIL" | "RATE_LIMIT" | "UNAUTHORIZED" | "BLOCK" | "SUSPEND" | "DEACTIVATE";
const transitions: Partial<Record<CustomerAuthState, Partial<Record<CustomerAuthEvent, CustomerAuthState>>>> = {
  INITIALIZING: { DETECT_TELEGRAM: "TELEGRAM_DETECTED", NO_TELEGRAM: "TELEGRAM_UNAVAILABLE", UNSUPPORTED: "UNSUPPORTED_CLIENT", NETWORK_FAIL: "NETWORK_ERROR" },
  TELEGRAM_DETECTED: { AUTH_START: "AUTHENTICATING", NO_TELEGRAM: "TELEGRAM_UNAVAILABLE" },
  AUTHENTICATING: { AUTH_OK: "AUTHENTICATED", UNAUTHORIZED: "UNAUTHORIZED", RATE_LIMIT: "RATE_LIMITED", SERVICE_FAIL: "SERVICE_UNAVAILABLE", NETWORK_FAIL: "NETWORK_ERROR", BLOCK: "BLOCKED", SUSPEND: "SUSPENDED", DEACTIVATE: "DEACTIVATED" },
  AUTHENTICATED: { REFRESH_START: "REFRESHING", LOGOUT: "UNAUTHORIZED", EXPIRE: "EXPIRED", BLOCK: "BLOCKED", SUSPEND: "SUSPENDED", DEACTIVATE: "DEACTIVATED" },
  REFRESHING: { AUTH_OK: "AUTHENTICATED", UNAUTHORIZED: "EXPIRED", NETWORK_FAIL: "NETWORK_ERROR", SERVICE_FAIL: "SERVICE_UNAVAILABLE" },
};
export function transition(state: CustomerAuthState, event: CustomerAuthEvent): CustomerAuthState { return transitions[state]?.[event] ?? state; }
export function stateFromError(code: ApiErrorCode, status?: number): CustomerAuthState { if (status === 429 || code === "rate_limited") return "RATE_LIMITED"; if (status && status >= 500) return "SERVICE_UNAVAILABLE"; if (code === "network_error") return "NETWORK_ERROR"; if (code === "expired") return "EXPIRED"; if (code === "blocked") return "BLOCKED"; if (code === "suspended") return "SUSPENDED"; if (code === "deactivated") return "DEACTIVATED"; return "UNAUTHORIZED"; }
export function isProtectedState(state: CustomerAuthState): boolean { return state === "AUTHENTICATED" || state === "REFRESHING"; }
