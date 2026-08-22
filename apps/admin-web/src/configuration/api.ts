import { refreshOnce } from "../auth/api-client";
import { getAccessToken, getCsrfToken } from "../auth/token-store";
import type { ValidationIssue } from "./types";

declare const process: { env: { NEXT_PUBLIC_API_BASE_URL?: string } };
const BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

export type LocalizedText = { fa: string; en: string };
export type ThemeMode = {
  page_color: string;
  surface_color: string;
  text_primary_color: string;
  text_secondary_color?: string;
  border_color?: string;
  primary_color: string;
  focus_ring_color: string;
};
export type ConfigurationSnapshot = {
  schema_version: 1;
  brand: {
    store_name: LocalizedText;
    short_name: string;
    tagline: LocalizedText;
    support_username: string;
    support_url: string;
    website_url: string;
    mini_app_url: string;
    logo_asset_reference: string;
    logo_alt_text: string;
  };
  theme: {
    light: ThemeMode;
    dark: ThemeMode;
    radius: "sm" | "md" | "lg";
    font_family: string;
    motion: string;
  };
  content_templates: Record<string, LocalizedText>;
  feature_flags: Record<string, Record<string, unknown>>;
  customer_navigation: readonly Record<string, unknown>[];
  telegram_menu: readonly Record<string, unknown>[];
  maintenance: Record<string, boolean>;
};
export type ConfigurationDraft = { reference: string; version: number; status?: string; snapshot: ConfigurationSnapshot };
export type ConfigurationDashboard = { active_version: number; etag: string; schema_version: number; namespaces: string[]; snapshot: ConfigurationSnapshot };

export class ConfigurationApiError extends Error {
  constructor(public status: number, public code: string, public correlationId?: string) { super(code); }
}
async function parseError(response: Response): Promise<ConfigurationApiError> {
  const body = await response.json().catch(() => null) as { detail?: { code?: string; correlation_id?: string } } | null;
  return new ConfigurationApiError(response.status, body?.detail?.code ?? `configuration_api_${response.status}`, body?.detail?.correlation_id ?? response.headers.get("x-correlation-id") ?? undefined);
}
async function request<T>(path: string, init: RequestInit & { csrf?: boolean; retry?: boolean } = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("accept", "application/json");
  if (init.body && !(init.body instanceof FormData)) headers.set("content-type", "application/json");
  const token = getAccessToken();
  if (token) headers.set("authorization", `Bearer ${token}`);
  if (init.csrf) { const csrf = getCsrfToken(); if (csrf) headers.set("x-csrf-token", csrf); }
  const response = await fetch(`${BASE}/api/v1/admin/configuration${path}`, { ...init, headers, credentials: "include", cache: "no-store" });
  if (response.status === 401 && init.retry !== false) {
    await refreshOnce();
    return request<T>(path, { ...init, retry: false });
  }
  if (!response.ok) throw await parseError(response);
  return response.json() as Promise<T>;
}
export type UploadedBrandLogo = { reference: string; url: string; alt_text: string; width: number; height: number };

export const configurationApi = {
  dashboard: () => request<ConfigurationDashboard>("/dashboard"),
  uploadLogo: (file: File, altText: string) => { const body = new FormData(); body.set("file", file); body.set("alt_text", altText); return request<UploadedBrandLogo>("/media/logo", { method: "POST", body, csrf: true }); },
  createDraft: () => request<ConfigurationDraft>("/drafts", { method: "POST", body: JSON.stringify({ clone_active: true }), csrf: true }),
  getDraft: (reference: string) => request<ConfigurationDraft>(`/drafts/${encodeURIComponent(reference)}`),
  updateSection: (reference: string, section: string, value: unknown, expectedVersion: number) => request<{ reference: string; version: number; validation_ok: boolean; issues: ValidationIssue[] }>(`/drafts/${encodeURIComponent(reference)}/sections`, { method: "PATCH", body: JSON.stringify({ section, value, expected_version: expectedVersion }), csrf: true }),
  validate: (reference: string) => request<{ ok: boolean; issues: ValidationIssue[] }>(`/drafts/${encodeURIComponent(reference)}/validate`, { method: "POST", body: JSON.stringify({}), csrf: true }),
  publish: (reference: string) => request<{ release_reference: string; version: number; etag: string }>(`/drafts/${encodeURIComponent(reference)}/publish`, { method: "POST", body: JSON.stringify({}), csrf: true }),
};
