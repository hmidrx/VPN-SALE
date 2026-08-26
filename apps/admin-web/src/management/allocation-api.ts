import { refreshOnce } from "../auth/api-client";
import { getAccessToken, getCsrfToken } from "../auth/token-store";

declare const process: { env: { NEXT_PUBLIC_API_BASE_URL?: string } };

const ROOT = `${process.env.NEXT_PUBLIC_API_BASE_URL ?? ""}/api/v1/admin/allocation`;

export type AllocationPool = {
  id: string;
  name: string;
  status: string;
  created_at: string;
  target_count: number;
};

export type AllocationTarget = {
  id: string;
  pool_id: string;
  panel_id: string;
  node_id: string | null;
  inbound_id: string;
  provider_kind: string;
  required_protocol: string;
  role: string;
  priority: number;
  weight: number;
  max_capacity: number;
  safety_reserve: number;
  status: string;
  certification_minimum: string;
  diagnostics: {
    inventory_observed_at: string;
    inventory_max_age_seconds: number;
    healthy: boolean;
    maintenance: boolean;
    write_mode: string;
    supports_shared_identity: boolean;
    tags: string[];
    provider_version: string;
    contract_digest: string;
  };
};

export type AllocationPolicy = {
  id: string;
  name: string;
  status: string;
  current_version_id: string | null;
  created_at: string;
  optimistic_version: number;
};

export type AllocationPolicyVersion = {
  id: string;
  policy_id: string;
  version_number: number;
  status: string;
  strategy: string;
  success_policy: string;
  identity_strategy: string;
  required_target_count: number;
  pool_ids: string[];
  required_tags: string[];
  product_version_ids: string[];
  plan_references: string[];
  locations: string[];
  required_protocols: string[];
  published_at: string | null;
  policy_optimistic_version: number;
};

export type AllocationSimulation = {
  eligible: string[];
  rejected_reason_codes: string[];
  selected_targets: Array<{
    target_id: string;
    panel_id: string;
    inbound_id: string;
    provider_kind: string;
  }>;
  rejected: Array<{ target_id: string | null; reason_code: string }>;
  policy_id: string | null;
  policy_version_id: string | null;
  performs_reservation: boolean;
  performs_provider_mutation: boolean;
};

export class AllocationApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
  ) {
    super(code);
  }
}

async function parseError(response: Response): Promise<AllocationApiError> {
  let code = `ALLOCATION_HTTP_${response.status}`;
  try {
    const payload = (await response.json()) as { detail?: { code?: string } };
    if (payload.detail?.code) code = payload.detail.code;
  } catch {
    // Raw reverse-proxy and provider responses are intentionally hidden.
  }
  return new AllocationApiError(response.status, code);
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
  if (!response.ok) throw await parseError(response);
  return response.json() as Promise<T>;
}

const mutate = <T>(path: string, method: "POST" | "PATCH", body?: unknown): Promise<T> =>
  request<T>(path, {
    method,
    body: body === undefined ? undefined : JSON.stringify(body),
    mutation: true,
  });

export const allocationApi = {
  pools: (): Promise<AllocationPool[]> => request("/pools"),
  createPool: (body: unknown): Promise<AllocationPool> => mutate("/pools", "POST", body),
  updatePool: (id: string, body: unknown): Promise<AllocationPool> =>
    mutate(`/pools/${encodeURIComponent(id)}`, "PATCH", body),
  targets: (poolId?: string): Promise<AllocationTarget[]> =>
    request(`/targets${poolId ? `?pool_id=${encodeURIComponent(poolId)}` : ""}`),
  createTarget: (body: unknown): Promise<AllocationTarget> =>
    mutate("/targets", "POST", body),
  updateTarget: (id: string, body: unknown): Promise<AllocationTarget> =>
    mutate(`/targets/${encodeURIComponent(id)}`, "PATCH", body),
  policies: (): Promise<AllocationPolicy[]> => request("/policies"),
  createPolicy: (body: unknown): Promise<AllocationPolicy> =>
    mutate("/policies", "POST", body),
  versions: (policyId: string): Promise<AllocationPolicyVersion[]> =>
    request(`/policies/${encodeURIComponent(policyId)}/versions`),
  createVersion: (policyId: string, body: unknown): Promise<AllocationPolicyVersion> =>
    mutate(`/policies/${encodeURIComponent(policyId)}/versions`, "POST", body),
  validateVersion: (
    policyId: string,
    versionId: string,
    expectedPolicyVersion: number,
  ): Promise<AllocationPolicyVersion> =>
    mutate(
      `/policies/${encodeURIComponent(policyId)}/versions/${encodeURIComponent(versionId)}/validate`,
      "POST",
      { expected_policy_version: expectedPolicyVersion },
    ),
  publishVersion: (
    policyId: string,
    versionId: string,
    expectedPolicyVersion: number,
  ): Promise<AllocationPolicyVersion> =>
    mutate(
      `/policies/${encodeURIComponent(policyId)}/versions/${encodeURIComponent(versionId)}/publish`,
      "POST",
      { expected_policy_version: expectedPolicyVersion },
    ),
  simulate: (body: unknown): Promise<AllocationSimulation> =>
    mutate("/simulate", "POST", body),
};
