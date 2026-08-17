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

export type SupportAttachment = {
  asset_reference: string;
  filename: string;
  content_type: string;
  byte_size: number;
  created_at: string;
};

export type SupportMessage = {
  sequence: number;
  sender_type: string;
  message_type: string;
  body: string;
  created_at: string;
  attachments: SupportAttachment[];
};

export type SupportTicket = SupportTicketSummary & { messages: SupportMessage[] };

export type SupportCsatState = {
  eligible: boolean;
  submitted: boolean;
  score: number | null;
};

export type SupportUnreadItem = {
  reference: string;
  unread_count: number;
};

export type SupportUnreadSummary = {
  total_unread: number;
  tickets_with_unread: number;
  items: SupportUnreadItem[];
};

export class SupportApiError extends Error {
  constructor(public readonly status: number, public readonly code: string) {
    super(code);
  }
}

function headers(
  mutating = false,
  idempotencyKey?: string,
  contentType: string | null = "application/json",
): Headers {
  const value = new Headers();
  if (contentType) value.set("content-type", contentType);
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

function integer(value: unknown, field: string, minimum = 0): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < minimum) {
    throw new Error(`invalid_${field}`);
  }
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

function attachment(value: unknown): SupportAttachment {
  const item = object(value);
  if (typeof item.byte_size !== "number" || !Number.isFinite(item.byte_size) || item.byte_size < 0) {
    throw new Error("invalid_byte_size");
  }
  return {
    asset_reference: string(item.asset_reference, "asset_reference"),
    filename: string(item.filename, "filename"),
    content_type: string(item.content_type, "content_type"),
    byte_size: item.byte_size,
    created_at: date(item.created_at, "created_at"),
  };
}

function message(value: unknown): SupportMessage {
  const item = object(value);
  if (typeof item.sequence !== "number" || !Number.isInteger(item.sequence) || item.sequence < 1) {
    throw new Error("invalid_sequence");
  }
  if (!Array.isArray(item.attachments)) throw new Error("invalid_attachments");
  return {
    sequence: item.sequence,
    sender_type: string(item.sender_type, "sender_type"),
    message_type: string(item.message_type, "message_type"),
    body: string(item.body, "body"),
    created_at: date(item.created_at, "created_at"),
    attachments: item.attachments.map(attachment),
  };
}

function ticket(value: unknown): SupportTicket {
  const item = object(value);
  const base = summary(item);
  if (!Array.isArray(item.messages)) throw new Error("invalid_messages");
  return { ...base, messages: item.messages.map(message) };
}

function csatState(value: unknown): SupportCsatState {
  const item = object(value);
  if (typeof item.eligible !== "boolean" || typeof item.submitted !== "boolean") {
    throw new Error("invalid_csat_state");
  }
  if (item.score !== null && (typeof item.score !== "number" || !Number.isInteger(item.score) || item.score < 1 || item.score > 5)) {
    throw new Error("invalid_csat_score");
  }
  return {
    eligible: item.eligible,
    submitted: item.submitted,
    score: item.score as number | null,
  };
}

function unreadSummary(value: unknown): SupportUnreadSummary {
  const item = object(value);
  if (!Array.isArray(item.items)) throw new Error("invalid_unread_items");
  const items = item.items.map((value): SupportUnreadItem => {
    const row = object(value);
    return {
      reference: string(row.reference, "unread_reference"),
      unread_count: integer(row.unread_count, "unread_count"),
    };
  });
  const total = integer(item.total_unread, "total_unread");
  const tickets = integer(item.tickets_with_unread, "tickets_with_unread");
  if (items.reduce((sum, row) => sum + row.unread_count, 0) !== total) {
    throw new Error("invalid_unread_total");
  }
  if (items.length !== tickets) throw new Error("invalid_unread_ticket_count");
  return { total_unread: total, tickets_with_unread: tickets, items };
}

function markReadResult(value: unknown): { unread_count: number } {
  const item = object(value);
  return { unread_count: integer(item.unread_count, "unread_count") };
}

async function parseError(response: Response): Promise<never> {
  let code = response.status === 401 ? "AUTH_REQUIRED" : response.status === 403 ? "CSRF_FAILED" : response.status === 404 ? "NOT_FOUND" : response.status === 409 ? "CONFLICT" : response.status === 413 ? "TOO_LARGE" : response.status === 415 ? "UNSUPPORTED_TYPE" : response.status === 422 ? "VALIDATION" : response.status >= 500 ? "UNAVAILABLE" : "SUPPORT_ERROR";
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

export const uploadSupportImage = (
  reference: string,
  file: File,
  fetcher: Fetcher = fetch,
): Promise<SupportAttachment> =>
  request(`/tickets/${encodeURIComponent(reference)}/attachments`, attachment, {
    method: "POST",
    headers: headers(true, idempotencyKey("web-image"), file.type),
    body: file,
  }, fetcher);

export async function fetchSupportAttachmentBlob(
  reference: string,
  assetReference: string,
  signal?: AbortSignal,
  fetcher: Fetcher = fetch,
): Promise<Blob> {
  const response = await fetcher(
    `${config.apiBaseUrl}/api/v1/customer/support/tickets/${encodeURIComponent(reference)}/attachments/${encodeURIComponent(assetReference)}`,
    {
      method: "GET",
      headers: headers(false, undefined, null),
      credentials: "include",
      cache: "no-store",
      signal,
    },
  );
  if (!response.ok) await parseError(response);
  return response.blob();
}

export const getSupportCsat = (
  reference: string,
  signal?: AbortSignal,
  fetcher: Fetcher = fetch,
): Promise<SupportCsatState> =>
  request(`/tickets/${encodeURIComponent(reference)}/csat`, csatState, { signal }, fetcher);

export const submitSupportCsat = (
  reference: string,
  score: number,
  feedback: string | null,
  fetcher: Fetcher = fetch,
): Promise<SupportCsatState> =>
  request(`/tickets/${encodeURIComponent(reference)}/csat`, csatState, {
    method: "POST",
    headers: headers(true, idempotencyKey("web-csat")),
    body: JSON.stringify({ score, feedback }),
  }, fetcher);

export const getSupportUnreadSummary = (
  signal?: AbortSignal,
  fetcher: Fetcher = fetch,
): Promise<SupportUnreadSummary> =>
  request("/unread", unreadSummary, { signal }, fetcher);

export const markSupportTicketRead = (
  reference: string,
  throughSequence: number,
  fetcher: Fetcher = fetch,
): Promise<{ unread_count: number }> =>
  request(`/tickets/${encodeURIComponent(reference)}/read`, markReadResult, {
    method: "POST",
    headers: headers(true),
    body: JSON.stringify({ through_sequence: throughSequence }),
  }, fetcher);
