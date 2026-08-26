import { refreshOnce } from "../auth/api-client";
import { getAccessToken, getCsrfToken } from "../auth/token-store";

declare const process: { env: { NEXT_PUBLIC_API_BASE_URL?: string } };
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";
const ROOT = `${API_BASE}/api/v1/admin/providers`;

export type ProviderCredentialSummary = {
  configured: boolean;
  credential_kind: string | null;
  key_version: string | null;
  updated_at: string | null;
};

export type ProviderConnectionSummary = {
  status: string;
  detected_version: string | null;
  contract_digest: string | null;
  latency_ms: number | null;
  safe_error_code: string | null;
  tested_at: string;
};

export type ProviderPanel = {
  id: string;
  public_reference: string;
  display_name: string;
  provider_kind: string;
  provider_version: string;
  endpoint_origin: string;
  base_path: string;
  status: string;
  tls_policy: Record<string, unknown>;
  endpoint_policy: Record<string, unknown>;
  optimistic_version: number;
  credential: ProviderCredentialSummary;
  last_connection_test: ProviderConnectionSummary | null;
  created_at: string;
  updated_at: string;
};

export type ProviderInbound = {
  remote_identifier: string;
  status: string | null;
  sanitized_payload: {
    remark?: string;
    tag?: string;
    protocol?: string;
    port?: number;
    enabled?: boolean;
    node_id?: number | null;
    tls_flow_capable?: boolean;
  };
  observed_at: string;
  sync_reference: string | null;
};

export type ProviderCapability = {
  provider_kind: string;
  provider_version: string;
  contract_digest: string;
  release_commit: string;
  authentication_preference: string[];
  required_bearer_scope: string;
  operations: string[];
  writes_enabled_by_default: boolean;
};

export type ProviderSyncResult = {
  sync_reference: string;
  status: string;
  inbound_count: number;
  detected_version: string | null;
  safe_error_code: string | null;
  completed_at: string;
};

export class ProviderApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
  ) {
    super(code);
  }
}

async function errorOf(response: Response): Promise<ProviderApiError> {
  let code = `PROVIDER_HTTP_${response.status}`;
  try {
    const value = (await response.json()) as { detail?: { code?: string } };
    if (value.detail?.code) code = value.detail.code;
  } catch {
    // The UI intentionally does not surface raw upstream or proxy responses.
  }
  return new ProviderApiError(response.status, code);
}

async function request<T>(
  path: string,
  init: RequestInit & { mutation?: boolean; retry?: boolean } = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("accept", "application/json");
  if (init.body) headers.set("content-type", "application/json");
  const access = getAccessToken();
  if (access) headers.set("authorization", `Bearer ${access}`);
  if (init.mutation) {
    const csrf = getCsrfToken();
    if (csrf) headers.set("x-csrf-token", csrf);
  }
  const response = await fetch(`${ROOT}${path}`, {
    ...init,
    headers,
    credentials: "include",
    cache: "no-store",
  });
  if (response.status === 401 && init.retry !== false) {
    await refreshOnce();
    return request<T>(path, { ...init, retry: false });
  }
  if (!response.ok) throw await errorOf(response);
  return response.json() as Promise<T>;
}

export const providerApi = {
  panels: (): Promise<{ items: ProviderPanel[] }> => request("/panels"),
  panel: (reference: string): Promise<ProviderPanel> =>
    request(`/panels/${encodeURIComponent(reference)}`),
  create: (body: Record<string, unknown>): Promise<ProviderPanel> =>
    request("/panels", { method: "POST", body: JSON.stringify(body), mutation: true }),
  update: (reference: string, body: Record<string, unknown>): Promise<ProviderPanel> =>
    request(`/panels/${encodeURIComponent(reference)}`, {
      method: "PATCH",
      body: JSON.stringify(body),
      mutation: true,
    }),
  replaceCredential: (
    reference: string,
    body: Record<string, unknown>,
  ): Promise<ProviderCredentialSummary> =>
    request(`/panels/${encodeURIComponent(reference)}/credential`, {
      method: "PUT",
      body: JSON.stringify(body),
      mutation: true,
    }),
  test: (reference: string): Promise<ProviderConnectionSummary> =>
    request(`/panels/${encodeURIComponent(reference)}/test-connection`, {
      method: "POST",
      mutation: true,
    }),
  sync: (reference: string): Promise<ProviderSyncResult> =>
    request(`/panels/${encodeURIComponent(reference)}/sync`, {
      method: "POST",
      mutation: true,
    }),
  capabilities: (reference: string): Promise<ProviderCapability> =>
    request(`/panels/${encodeURIComponent(reference)}/capabilities`),
  inbounds: (reference: string): Promise<ProviderInbound[]> =>
    request(`/panels/${encodeURIComponent(reference)}/inbounds`),
};
