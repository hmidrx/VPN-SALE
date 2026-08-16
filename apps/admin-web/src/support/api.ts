import { getAccessToken } from "../auth/token-store";
import type {
  SupportConversationDetail,
  SupportConversationPage,
  SupportMessagePage,
  SupportSlaEscalation,
  SupportStatus,
} from "./types";

declare const process: { env: { NEXT_PUBLIC_API_BASE_URL?: string } };

const base = `${process.env.NEXT_PUBLIC_API_BASE_URL ?? ""}/api/v1/admin/support-runtime`;

function headers(idempotencyKey?: string): Headers {
  const result = new Headers();
  const accessToken = getAccessToken();
  if (accessToken) result.set("authorization", `Bearer ${accessToken}`);
  if (idempotencyKey) result.set("Idempotency-Key", idempotencyKey);
  result.set("content-type", "application/json");
  return result;
}

async function call<T>(path: string, init: RequestInit = {}, idempotencyKey?: string): Promise<T> {
  const response = await fetch(`${base}${path}`, {
    ...init,
    headers: headers(idempotencyKey),
    credentials: "include",
    cache: "no-store",
  });
  if (!response.ok) {
    if (response.status === 400) throw new Error("صفحه درخواستی معتبر نیست؛ اطلاعات را تازه کنید.");
    if (response.status === 401) throw new Error("نشست مدیریت معتبر نیست. دوباره وارد شوید.");
    if (response.status === 403) throw new Error("مجوز لازم برای این عملیات را ندارید.");
    if (response.status === 404) throw new Error("تیکت یا هشدار SLA پیدا نشد.");
    if (response.status === 409) throw new Error("وضعیت تیکت تغییر کرده است؛ اطلاعات را تازه کنید.");
    throw new Error("عملیات پشتیبانی انجام نشد.");
  }
  return response.json() as Promise<T>;
}

function queryString(values: Record<string, string | number | undefined>): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined && value !== "") query.set(key, String(value));
  }
  const encoded = query.toString();
  return encoded ? `?${encoded}` : "";
}

export function supportIdempotencyKey(): string {
  return crypto.randomUUID();
}

export function listSupportConversations(
  status?: SupportStatus,
  cursor?: string,
  limit = 50,
): Promise<SupportConversationPage> {
  return call<SupportConversationPage>(
    `/conversations-page${queryString({ status_filter: status, cursor, limit })}`,
  );
}

export function getSupportConversation(
  reference: string,
  cursor?: string,
  limit = 50,
): Promise<SupportConversationDetail> {
  return call<SupportConversationDetail>(
    `/conversations/${encodeURIComponent(reference)}/paged${queryString({ cursor, limit })}`,
  );
}

export function getInternalNotes(
  reference: string,
  cursor?: string,
  limit = 50,
): Promise<SupportMessagePage> {
  return call<SupportMessagePage>(
    `/conversations/${encodeURIComponent(reference)}/internal-notes-page${queryString({ cursor, limit })}`,
  );
}

export function getConversationSlaEscalations(
  reference: string,
): Promise<{ items: SupportSlaEscalation[] }> {
  return call<{ items: SupportSlaEscalation[] }>(
    `/conversations/${encodeURIComponent(reference)}/sla/escalations`,
  );
}

export function listOpenSlaEscalations(): Promise<{ items: SupportSlaEscalation[] }> {
  return call<{ items: SupportSlaEscalation[] }>("/sla/escalations?status_filter=OPEN&limit=100");
}

export function manuallyEscalateSupportConversation(
  reference: string,
  reason: string,
  expectedVersion: number,
): Promise<SupportSlaEscalation> {
  return call<SupportSlaEscalation>(
    `/conversations/${encodeURIComponent(reference)}/escalate`,
    {
      method: "POST",
      body: JSON.stringify({ reason, expected_version: expectedVersion }),
    },
  );
}

export function acknowledgeSupportSlaEscalation(
  reference: string,
  note?: string,
): Promise<SupportSlaEscalation> {
  return call<SupportSlaEscalation>(
    `/sla/escalations/${encodeURIComponent(reference)}/acknowledge`,
    { method: "POST", body: JSON.stringify({ note: note?.trim() || null }) },
  );
}

export async function claimSupportConversation(
  reference: string,
  expectedVersion: number,
): Promise<SupportConversationDetail> {
  await call<unknown>(
    `/conversations/${encodeURIComponent(reference)}/claim`,
    { method: "POST", body: JSON.stringify({ expected_version: expectedVersion }) },
  );
  return getSupportConversation(reference);
}

export async function replySupportConversation(
  reference: string,
  body: string,
  expectedVersion: number,
  idempotencyKey: string,
): Promise<SupportConversationDetail> {
  await call<unknown>(
    `/conversations/${encodeURIComponent(reference)}/reply`,
    {
      method: "POST",
      body: JSON.stringify({ body, expected_version: expectedVersion }),
    },
    idempotencyKey,
  );
  return getSupportConversation(reference);
}

export async function addSupportInternalNote(
  reference: string,
  body: string,
  expectedVersion: number,
  idempotencyKey: string,
): Promise<SupportMessagePage> {
  await call<unknown>(
    `/conversations/${encodeURIComponent(reference)}/internal-notes`,
    {
      method: "POST",
      body: JSON.stringify({ body, expected_version: expectedVersion }),
    },
    idempotencyKey,
  );
  return getInternalNotes(reference);
}

export async function changeSupportStatus(
  reference: string,
  status: SupportStatus,
  reason: string,
  expectedVersion: number,
): Promise<SupportConversationDetail> {
  await call<unknown>(
    `/conversations/${encodeURIComponent(reference)}/status`,
    {
      method: "POST",
      body: JSON.stringify({ status, reason, expected_version: expectedVersion }),
    },
  );
  return getSupportConversation(reference);
}