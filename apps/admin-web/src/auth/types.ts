export type AuthOutcome = "AUTHENTICATED" | "MFA_REQUIRED" | "INVALID_CREDENTIALS" | "ACCOUNT_LOCKED" | "ACCOUNT_DISABLED" | "RATE_LIMITED";
export type LoginResponse = { outcome: AuthOutcome; access_token?: string | null; csrf_token?: string | null; mfa_challenge?: string | null };
export type AdminProfile = { admin_id: string; email: string; status: string; mfa_enabled: boolean; roles: string[]; effective_permissions?: string[]; current_session_id: string; password_changed_at: string | null; last_successful_login_at: string | null };
export type AdminSession = { session_id: string; current: boolean; device_label: string | null; client: string; created_at: string; last_used_at: string | null; idle_expires_at: string; absolute_expires_at: string; revoked: boolean };
