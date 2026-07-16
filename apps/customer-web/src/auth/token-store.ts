let accessToken: string | null = null;
let csrfToken: string | null = null;
let sessionId: string | null = null;
export function setAccessToken(value: string | null): void { accessToken = value; }
export function getAccessToken(): string | null { return accessToken; }
export function setCsrfToken(value: string | null): void { csrfToken = value; }
export function getCsrfToken(): string | null { return csrfToken; }
export function setSessionId(value: string | null): void { sessionId = value; }
export function getSessionId(): string | null { return sessionId; }
export function applyAuthMemory(input: { access_token?: string | null; csrf_token?: string | null; session_id?: string | null }): void { if (input.access_token) setAccessToken(input.access_token); if (input.csrf_token) setCsrfToken(input.csrf_token); if (input.session_id) setSessionId(input.session_id); }
export function clearAuthMemory(): void { accessToken = null; csrfToken = null; sessionId = null; }
