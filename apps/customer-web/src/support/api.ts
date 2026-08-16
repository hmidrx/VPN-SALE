import { correlationId } from "../auth/api-client";
import { getAccessToken, getCsrfToken } from "../auth/token-store";
import { loadCustomerConfig } from "../config/public-config";

type Fetcher = typeof fetch;
const config = loadCustomerConfig();

export type SupportTicketSummary = {
  reference: string;
  subject: string;
  status: string;
  created_at: string;
  updated_at: string;
};

export type SupportMessage = {
  sequence: number;
  sender_type: string;
  message_type: string;
  body: string;
  created_at: string;
};

export type SupportTicket = SupportTicketSummary & { messages: SupportMessage[] };

export class SupportApiError extends Error {
  constructor(public readonly status: number, public readonly code: string) {
    super(code);
  }
}

function headers(mutating = false, idempotencyKey?: string): Headers {
  const value = new Headers();
  value.set("content-type", "application/json");
  value.set("x-request-id", correlationId());
  const access = getAccessToken();
  if (access) value.set("authorization", `Bearer ${access}`);
  if (mutating) {
    const csrf = getCsrfToken();
    if (csrf) value.set("x-csrf-token", csrf);
  }
  if (idempotencyKey) value.set("idempotency-key", idempotencyKey);
  return value;
}

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("invalid_support_response");
  return value as Record<string, unknown>;
}

function string(value: unknown, field: string): string {
  if (typeof value !== "string") throw new Error(`invalid_${field}`);
  return value;
}

function date(value: unknown, field: string): string {
  const out = string(value, field);
  if (Number.isNaN(Date.parse(out))) throw new Error(`invalid_${field}`);
  return out;
}

function summary(value: unknown): SupportTicketSummary {
  const item = object(value);
  return {
    reference: string(item.reference, "reference"),
    subject: string(item.subject, "subject"),
    status: string(item.status, "status"),
    created_at: date(item.created_at, "created_at"),
    updated_at: date(item.updated_at, "updated_at"),
  };
}

function message(value: unknown): SupportMessage {
  const item = object(value);
  if (typeof item.sequence !== "number" || !Number.isInteger(item.sequence) || item.sequence < 1) {
    throw new Error("invalid_sequence");
  }
  return {
    sequence: item.sequence,
    sender_type: string(item.sender_type, "sender_type"),
    message_type: string(item.message_type, "message_type"),
    body: string(item.body, "body"),
    created_at: date(item.created_at, "created_at"),
  };
}

function ticket(value: unknown): SupportTicket {
  const item = object(value);
  const base = summary(item);
  if (!Array.isArray(item.messages)) throw new Error("invalid_messages");
  return { ...base, messages: item.messages.map(message) };
}

async function parseError(response: Response): Promise<never> {
  let code = response.status === 401 ? "AUTH_REQUIRED" : response.status === 403 ? "CSRF_FAILED" : response.status === 404 ? "NOT_FOUND" : response.status === 409 ? "CONFLICT" : response.status === 422 ? "VALIDATION" : response.status >= 500 ? "UNAVAILABLE" : "SUPPORT_ERROR";
  const payload = await response.json().catch(() => null) as { detail?: string } | null;
  if (typeof payload?.detail === "string") code = payload.detail;
  throw new SupportApiError(response.status, code);
}

async function request<T>(path: string, validate: (value: unknown) => T, init: RequestInit = {}, fetcher: Fetcher = fetch): Promise<T> {
  const response = await fetcher(`${config.apiBaseUrl}/api/v1/customer/support${path}`, {
    ...init,
    headers: init.headers ?? headers(),
    credentials: "include",
    cache: "no-store",
  });
  if (!response.ok) await parseError(response);
  return validate(await response.json());
}

export async function listSupportTickets(signal?: AbortSignal, fetcher: Fetcher = fetch): Promise<SupportTicketSummary[]> {
  return request("/tickets", (value) => {
    const payload = object(value);
    if (!Array.isArray(payload.items)) throw new Error("invalid_items");
    return payload.items.map(summary);
  }, { signal }, fetcher);
}

export const getSupportTicket = (reference: string, signal?: AbortSignal, fetcher: Fetcher = fetch): Promise<SupportTicket> =>
  request(`/tickets/${encodeURIComponent(reference)}`, ticket, { signal }, fetcher);

function idempotencyKey(prefix: string): string {
  const random = globalThis.crypto?.randomUUID?.() ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  return `${prefix}-${random}`;
}

export const createSupportTicket = (subject: string, body: string, fetcher: Fetcher = fetch): Promise<SupportTicket> =>
  request("/tickets", ticket, {
    method: "POST",
    headers: headers(true, idempotencyKey("web-ticket")),
    body: JSON.stringify({ subject, message: body }),
  }, fetcher);

export const replySupportTicket = (reference: string, body: string, fetcher: Fetcher = fetch): Promise<SupportTicket> =>
  request(`/tickets/${encodeURIComponent(reference)}/reply`, ticket, {
    method: "POST",
    headers: headers(true, idempotencyKey("web-reply")),
    body: JSON.stringify({ message: body }),
  }, fetcher);
