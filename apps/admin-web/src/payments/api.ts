import { refreshOnce } from "../auth/api-client";
import { getAccessToken, getCsrfToken } from "../auth/token-store";
import type {
  AdapterCapability,
  MethodHealth,
  Page,
  PaymentAttempt,
  PaymentIntent,
  PaymentMethod,
  Settlement,
  Verification,
  Webhook,
} from "./types";
import { validatePage } from "./validation";
declare const process: { env: { NEXT_PUBLIC_API_BASE_URL?: string } };
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";
type Query = Record<string, string | number | boolean | null | undefined>;
export class PaymentApiError extends Error {
  status: number;
  code: string;
  correlationId?: string;
  retryAfter?: string | null;
  constructor(
    status: number,
    code: string,
    correlationId?: string,
    retryAfter?: string | null,
  ) {
    super(code);
    this.status = status;
    this.code = code;
    this.correlationId = correlationId;
    this.retryAfter = retryAfter;
  }
}
export function serializePaymentQuery(q: Query = {}): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(q)) {
    if (v !== undefined && v !== null && String(v) !== "")
      p.set(k, String(v).slice(0, 160));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}
async function parseError(r: Response): Promise<PaymentApiError> {
  let body: unknown = null;
  try {
    body = await r.json();
  } catch {
    body = null;
  }
  const d =
    typeof body === "object" && body && "detail" in body
      ? (body as { detail?: Record<string, unknown> }).detail
      : undefined;
  return new PaymentApiError(
    r.status,
    String(d?.code ?? `payment_${r.status}`),
    typeof d?.correlation_id === "string"
      ? d.correlation_id
      : (r.headers.get("x-correlation-id") ?? undefined),
    r.headers.get("retry-after") /* Retry-After */,
  );
}
async function request<T>(
  path: string,
  init: RequestInit & { csrf?: boolean; retry?: boolean } = {},
): Promise<T> {
  const h = new Headers(init.headers);
  h.set("accept", "application/json");
  if (init.body) h.set("content-type", "application/json");
  const token = getAccessToken();
  if (token) h.set("authorization", `Bearer ${token}`);
  if (init.csrf) {
    const csrf = getCsrfToken();
    if (csrf) h.set("x-csrf-token", csrf);
  }
  const res = await fetch(`${API_BASE}/api/v1/admin/payments${path}`, {
    ...init,
    headers: h,
    credentials: "include",
    cache: "no-store",
  });
  if (res.status === 401 && init.retry !== false) {
    await refreshOnce();
    return request<T>(path, { ...init, retry: false });
  }
  if (!res.ok) throw await parseError(res);
  return res.json() as Promise<T>;
}
const page = <T>(p: string, q?: Query) =>
  request<Page<T>>(`${p}${serializePaymentQuery(q)}`).then(validatePage<T>);
export const paymentApi = {
  overview: () => request<Record<string, unknown>>("/overview"),
  methods: (q?: Query) =>
    request<PaymentMethod[] | Page<PaymentMethod>>(
      `/methods${serializePaymentQuery(q)}`,
    ).then((r) =>
      Array.isArray(r) ? { items: r, next_cursor: null } : validatePage(r),
    ),
  method: (ref: string) =>
    request<PaymentMethod>(`/methods/${encodeURIComponent(ref)}`),
  createMethod: (body: Record<string, unknown>) =>
    request<PaymentMethod>("/methods", {
      method: "POST",
      body: JSON.stringify(body),
      csrf: true,
    }),
  updateMethod: (ref: string, body: Record<string, unknown>) =>
    request<PaymentMethod>(`/methods/${encodeURIComponent(ref)}`, {
      method: "PATCH",
      body: JSON.stringify(body),
      csrf: true,
    }),
  lifecycle: (ref: string, action: string, body: Record<string, unknown>) =>
    request<PaymentMethod>(`/methods/${encodeURIComponent(ref)}/${action}`, {
      method: "POST",
      body: JSON.stringify(body),
      csrf: true,
    }),
  methodHealth: (ref: string) =>
    request<MethodHealth>(`/methods/${encodeURIComponent(ref)}/health`),
  adapters: () => request<AdapterCapability[]>("/adapters"),
  intents: (q?: Query) => page<PaymentIntent>("/intents", q),
  intent: (ref: string) =>
    request<PaymentIntent>(`/intents/${encodeURIComponent(ref)}`),
  attempt: (ref: string) =>
    request<PaymentAttempt>(`/attempts/${encodeURIComponent(ref)}`),
  verification: (ref: string) =>
    request<Verification>(`/verifications/${encodeURIComponent(ref)}`),
  settlement: (ref: string) =>
    request<Settlement>(`/settlements/${encodeURIComponent(ref)}`),
  webhooks: (q?: Query) => page<Webhook>("/webhooks", q),
  webhook: (ref: string) =>
    request<Webhook>(`/webhooks/${encodeURIComponent(ref)}`),
  retryWebhook: (ref: string, body: Record<string, unknown>) =>
    request<Webhook>(`/webhooks/${encodeURIComponent(ref)}/retry`, {
      method: "POST",
      body: JSON.stringify(body),
      csrf: true,
    }),
  refunds: (q?: Query) => page("/refunds", q),
  refundEligibility: (ref: string) =>
    request(`/refunds/eligibility/${encodeURIComponent(ref)}`),
  createRefund: (body: Record<string, unknown>) =>
    request("/refunds", {
      method: "POST",
      body: JSON.stringify(body),
      csrf: true,
    }),
  approveRefund: (ref: string, body: Record<string, unknown>) =>
    request(`/refunds/${encodeURIComponent(ref)}/approve`, {
      method: "POST",
      body: JSON.stringify(body),
      csrf: true,
    }),
  rejectRefund: (ref: string, body: Record<string, unknown>) =>
    request(`/refunds/${encodeURIComponent(ref)}/reject`, {
      method: "POST",
      body: JSON.stringify(body),
      csrf: true,
    }),
  retryRefund: (ref: string) =>
    request(`/refunds/${encodeURIComponent(ref)}/retry`, {
      method: "POST",
      body: "{}",
      csrf: true,
    }),
  reconciliationOverview: () => request("/reconciliation/overview"),
  reconciliationDryRun: () =>
    request("/reconciliation/dry-run", {
      method: "POST",
      body: "{}",
      csrf: true,
    }),
  repairPlan: (body: Record<string, unknown>) =>
    request("/reconciliation/repair-plan", {
      method: "POST",
      body: JSON.stringify(body),
      csrf: true,
    }),
  lateSettlements: (q?: Query) => page("/late-settlements", q),
  unappliedPayments: (q?: Query) => page("/unapplied-payments", q),
  recoverWebhook: (ref: string, body: Record<string, unknown>) =>
    request(`/webhooks/${encodeURIComponent(ref)}/recover`, {
      method: "POST",
      body: JSON.stringify(body),
      csrf: true,
    }),
  queryWebhookProvider: (ref: string) =>
    request(`/webhooks/${encodeURIComponent(ref)}/query-provider`, {
      method: "POST",
      body: "{}",
      csrf: true,
    }),
};
