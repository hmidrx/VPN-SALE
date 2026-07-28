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
  starts_at: string;
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
const config = loadCustomerConfig();
function headers(): Headers {
  const value = new Headers({ "x-request-id": correlationId() });
  const token = getAccessToken();
  if (token) value.set("authorization", `Bearer ${token}`);
  return value;
}
async function request<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${config.apiBaseUrl}${path}`, {
    headers: headers(), credentials: "include", cache: "no-store", signal,
  });
  if (!response.ok) throw new Error(`services_${response.status}`);
  return response.json() as Promise<T>;
}
export function listServices(signal?: AbortSignal): Promise<ServiceSummary[]> {
  return request("/api/v1/customer/services", signal);
}
export function getService(reference: string, signal?: AbortSignal): Promise<ServiceDetail> {
  return request(`/api/v1/customer/services/${encodeURIComponent(reference)}`, signal);
}
export function getOperationEligibility(reference: string, signal?: AbortSignal): Promise<OperationEligibility[]> {
  return request(`/api/v1/customer/service-operations/${encodeURIComponent(reference)}/eligibility`, signal);
}
