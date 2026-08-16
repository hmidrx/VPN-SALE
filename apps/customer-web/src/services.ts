import { correlationId } from "./auth/api-client";
import { getAccessToken } from "./auth/token-store";
import { loadCustomerConfig } from "./config/public-config";

export type ServiceEntitlement = {
  traffic_quota_bytes: number | null;
  duration_days: number | null;
  device_limit: number | null;
  location_label: string | null;
  quality_label: string | null;
};
export type ServiceUsage = {
  used_bytes: number;
  total_bytes: number | null;
  remaining_bytes: number | null;
  last_synced_at: string;
  unlimited: boolean;
  stale: boolean;
};
export type ServiceSummary = {
  service_reference: string;
  display_name: string;
  lifecycle: string;
  lifecycle_label: string;
  created_at: string;
  starts_at: string | null;
  activated_at: string | null;
  expires_at: string | null;
  delivery_ready: boolean;
  required_attachment_count: number;
  verified_attachment_count: number;
  provisioning_progress: number;
  safe_operational_message: string;
  entitlement: ServiceEntitlement;
  usage: ServiceUsage | null;
};
export type OperationEligibility = {
  operation_type: string;
  eligible: boolean;
  billable: boolean;
  requires_approval: boolean;
  safe_reason_codes: string[];
};
export type ServiceDetail = {
  summary: ServiceSummary;
  service_health: string;
  eligible_operations: OperationEligibility[];
  delivery: { ready: boolean; formats: string[] };
  latest_activity: { event: string; label: string; occurred_at: string }[];
};
export type DeliverySummary = {
  service_reference: string;
  status: string;
  delivery_ready: boolean;
  connections: { uri: string }[];
  formats: string[];
};
export type SubscriptionStatus = {
  service_reference: string;
  status: string;
  stable_urls: Record<string, string>;
  token_visible_once: string | null;
};

export class ServiceRequestError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ServiceRequestError";
  }
}

const config = loadCustomerConfig();

type ServiceRequestOptions = {
  method?: "GET" | "POST";
  signal?: AbortSignal;
  headers?: HeadersInit;
};

function headers(extra?: HeadersInit): Headers {
  const value = new Headers(extra);
  value.set("x-request-id", correlationId());
  const token = getAccessToken();
  if (token) value.set("authorization", `Bearer ${token}`);
  return value;
}

async function request<T>(
  path: string,
  options: ServiceRequestOptions = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${config.apiBaseUrl}${path}`, {
      method: options.method ?? "GET",
      headers: headers(options.headers),
      credentials: "include",
      cache: "no-store",
      signal: options.signal,
    });
  } catch (caught) {
    if (caught instanceof Error && caught.name === "AbortError") throw caught;
    throw new ServiceRequestError(0, "services_network");
  }
  if (!response.ok) {
    throw new ServiceRequestError(response.status, `services_${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function listServices(signal?: AbortSignal): Promise<ServiceSummary[]> {
  return request("/api/v1/customer/services", { signal });
}
export function getService(
  reference: string,
  signal?: AbortSignal,
): Promise<ServiceDetail> {
  return request(`/api/v1/customer/services/${encodeURIComponent(reference)}`, {
    signal,
  });
}
export function getOperationEligibility(
  reference: string,
  signal?: AbortSignal,
): Promise<OperationEligibility[]> {
  return request(
    `/api/v1/customer/service-operations/${encodeURIComponent(reference)}/eligibility`,
    { signal },
  );
}
export function getServiceDelivery(
  reference: string,
  signal?: AbortSignal,
): Promise<DeliverySummary> {
  return request(
    `/api/v1/customer/delivery/services/${encodeURIComponent(reference)}`,
    { signal },
  );
}
export function issueServiceSubscription(
  reference: string,
): Promise<SubscriptionStatus> {
  return request(
    `/api/v1/customer/delivery/services/${encodeURIComponent(reference)}/subscription`,
    { method: "POST" },
  );
}
export function rotateServiceSubscription(
  reference: string,
): Promise<SubscriptionStatus> {
  return request(
    `/api/v1/customer/delivery/services/${encodeURIComponent(reference)}/subscription/rotate`,
    { method: "POST" },
  );
}
export function revokeServiceSubscription(
  reference: string,
): Promise<SubscriptionStatus> {
  return request(
    `/api/v1/customer/delivery/services/${encodeURIComponent(reference)}/subscription/revoke`,
    { method: "POST" },
  );
}

const subscriptionPathPattern =
  /^\/subscriptions\/[A-Za-z0-9_-]{43,128}(?:\/(?:links|mihomo|clash|sing-box))?$/;

export function resolveSubscriptionUrl(
  path: string,
  browserOrigin?: string,
): string {
  if (!subscriptionPathPattern.test(path)) {
    throw new Error("unsafe_subscription_path");
  }
  const fallbackOrigin =
    browserOrigin ??
    (typeof window !== "undefined" ? window.location.origin : null);
  let apiUrl: URL;
  try {
    if (config.apiBaseUrl) {
      apiUrl = fallbackOrigin
        ? new URL(config.apiBaseUrl, fallbackOrigin)
        : new URL(config.apiBaseUrl);
    } else {
      if (!fallbackOrigin) throw new Error("missing_browser_origin");
      apiUrl = new URL(fallbackOrigin);
    }
  } catch {
    throw new Error("unsafe_subscription_origin");
  }
  if (apiUrl.protocol !== "https:" && apiUrl.protocol !== "http:") {
    throw new Error("unsafe_subscription_origin");
  }
  return new URL(path, `${apiUrl.origin}/`).toString();
}

export async function getConnectionQr(
  payload: string,
  signal?: AbortSignal,
): Promise<Blob> {
  let response: Response;
  try {
    response = await fetch(
      `${config.apiBaseUrl}/api/v1/customer/delivery/qr`,
      {
        method: "GET",
        headers: headers({ payload }),
        credentials: "include",
        cache: "no-store",
        signal,
      },
    );
  } catch (caught) {
    if (caught instanceof Error && caught.name === "AbortError") throw caught;
    throw new ServiceRequestError(0, "services_network");
  }
  if (!response.ok) {
    throw new ServiceRequestError(response.status, `services_${response.status}`);
  }
  if (!response.headers.get("content-type")?.startsWith("image/png")) {
    throw new ServiceRequestError(502, "services_invalid_qr");
  }
  return response.blob();
}
