import { getAccessToken } from "../auth/token-store";
import type {
  SupportConversationDetail,
  SupportConversationSummary,
  SupportMessage,
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
    if (response.status === 401) throw new Error("نشست مدیریت معتبر نیست. دوباره وارد شوید.");
    if (response.status === 403) throw new Error("مجوز لازم برای این عملیات را ندارید.");
    if (response.status === 404) throw new Error("تیکت پیدا نشد.");
    if (response.status === 409) throw new Error("وضعیت تیکت تغییر کرده است؛ اطلاعات را تازه کنید.");
    throw new Error("عملیات پشتیبانی انجام نشد.");
  }
  return response.json() as Promise<T>;
}

export function supportIdempotencyKey(): string {
  return crypto.randomUUID();
}

export function listSupportConversations(status?: SupportStatus): Promise<{ items: SupportConversationSummary[] }> {
  const query = status ? `?status_filter=${encodeURIComponent(status)}` : "";
  return call<{ items: SupportConversationSummary[] }>(`/conversations${query}`);
}

export function getSupportConversation(reference: string): Promise<SupportConversationDetail> {
  return call<SupportConversationDetail>(`/conversations/${encodeURIComponent(reference)}`);
}

export function getInternalNotes(reference: string): Promise<{ items: SupportMessage[] }> {
  return call<{ items: SupportMessage[] }>(
    `/conversations/${encodeURIComponent(reference)}/internal-notes`,
  );
}

export function claimSupportConversation(
  reference: string,
  expectedVersion: number,
): Promise<SupportConversationDetail> {
  return call<SupportConversationDetail>(
    `/conversations/${encodeURIComponent(reference)}/claim`,
    { method: "POST", body: JSON.stringify({ expected_version: expectedVersion }) },
  );
}

export function replySupportConversation(
  reference: string,
  body: string,
  expectedVersion: number,
  idempotencyKey: string,
): Promise<SupportConversationDetail> {
  return call<SupportConversationDetail>(
    `/conversations/${encodeURIComponent(reference)}/reply`,
    {
      method: "POST",
      body: JSON.stringify({ body, expected_version: expectedVersion }),
    },
    idempotencyKey,
  );
}

export function addSupportInternalNote(
  reference: string,
  body: string,
  expectedVersion: number,
  idempotencyKey: string,
): Promise<{ items: SupportMessage[] }> {
  return call<{ items: SupportMessage[] }>(
    `/conversations/${encodeURIComponent(reference)}/internal-notes`,
    {
      method: "POST",
      body: JSON.stringify({ body, expected_version: expectedVersion }),
    },
    idempotencyKey,
  );
}

export function changeSupportStatus(
  reference: string,
  status: SupportStatus,
  reason: string,
  expectedVersion: number,
): Promise<SupportConversationDetail> {
  return call<SupportConversationDetail>(
    `/conversations/${encodeURIComponent(reference)}/status`,
    {
      method: "POST",
      body: JSON.stringify({ status, reason, expected_version: expectedVersion }),
    },
  );
}
