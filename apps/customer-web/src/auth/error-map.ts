import { clearAuthMemory } from "./token-store";
import type { ApiErrorCode, CustomerAuthState } from "./types";
import { stateFromError } from "./state-machine";
export class CustomerApiError extends Error { constructor(readonly status: number, readonly code: ApiErrorCode, readonly retryAfter?: number) { super(`customer_api_${status}`); } }
export function mapApiError(error: unknown): CustomerAuthState { if (error instanceof CustomerApiError) return stateFromError(error.code, error.status); return "NETWORK_ERROR"; }
export function clearOnAuthFailure(error: unknown): void { if (error instanceof CustomerApiError && [401, 403].includes(error.status)) clearAuthMemory(); }
