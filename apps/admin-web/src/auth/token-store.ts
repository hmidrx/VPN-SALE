let accessToken: string | null = null;
let csrfToken: string | null = null;
export function setAccessToken(value: string | null): void { accessToken = value; }
export function getAccessToken(): string | null { return accessToken; }
export function setCsrfToken(value: string | null): void { csrfToken = value; }
export function getCsrfToken(): string | null { return csrfToken; }
export function clearAuthMemory(): void { accessToken = null; csrfToken = null; }
export function assertNoPersistentTokenStorage(): boolean { return !globalThis.localStorage?.getItem("access_token") && !globalThis.sessionStorage?.getItem("access_token"); }
