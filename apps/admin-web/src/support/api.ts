import { getAccessToken } from "../auth/token-store";
import type {
  SupportAttachment,
  SupportCannedResponse,
  SupportConversationDetail,
  SupportConversationPage,
  SupportMacro,
  SupportMacroPreview,
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

function binaryHeaders(contentType: string, idempotencyKey: string): Headers {
  const result = new Headers();
  const accessToken = getAccessToken();
  if (accessToken) result.set("authorization", `Bearer ${accessToken}`);
  result.set("Idempotency-Key", idempotencyKey);
  result.set("content-type", contentType);
  return result;
}

function errorForStatus(status: number): Error {
  if (status === 400) return new Error("صفحه درخواستی معتبر نیست؛ اطلاعات را تازه کنید.");
  if (status === 401) return new Error("نشست مدیریت معتبر نیست. دوباره وارد شوید.");
  if (status === 403) return new Error("مجوز لازم برای این عملیات را ندارید.");
  if (status === 404) return new Error("تیکت، پیوست، پاسخ آماده، ماکرو یا هشدار SLA پیدا نشد.");
  if (status === 409) return new Error("وضعیت تیکت یا منبع پشتیبانی تغییر کرده است؛ اطلاعات را تازه کنید.");
  if (status === 413) return new Error("حجم تصویر از سقف مجاز بیشتر است.");
  if (status === 415) return new Error("فقط تصویر JPEG، PNG یا WebP قابل ارسال است.");
  if (status === 422) return new Error("مقادیر واردشده برای عملیات پشتیبانی معتبر نیستند.");
  return new Error("عملیات پشتیبانی انجام نشد.");
}

async function call<T>(path: string, init: RequestInit = {}, idempotencyKey?: string): Promise<T> {
  const response = await fetch(`${base}${path}`, {
    ...init,
    headers: headers(idempotencyKey),
    credentials: "include",
    cache: "no-store",
  });
  if (!response.ok) throw errorForStatus(response.status);
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

export function listSupportAttachments(
  reference: string,
): Promise<{ items: SupportAttachment[] }> {
  return call<{ items: SupportAttachment[] }>(
    `/conversations/${encodeURIComponent(reference)}/attachments`,
  );
}

export async function uploadSupportAttachment(
  reference: string,
  file: File,
  expectedVersion: number,
  idempotencyKey: string,
): Promise<SupportAttachment> {
  const response = await fetch(
    `${base}/conversations/${encodeURIComponent(reference)}/attachments${queryString({ expected_version: expectedVersion })}`,
    {
      method: "POST",
      headers: binaryHeaders(file.type, idempotencyKey),
      credentials: "include",
      cache: "no-store",
      body: file,
    },
  );
  if (!response.ok) throw errorForStatus(response.status);
  return response.json() as Promise<SupportAttachment>;
}

export async function downloadSupportAttachment(
  reference: string,
  assetReference: string,
): Promise<Blob> {
  const response = await fetch(
    `${base}/conversations/${encodeURIComponent(reference)}/attachments/${encodeURIComponent(assetReference)}`,
    {
      headers: headers(),
      credentials: "include",
      cache: "no-store",
    },
  );
  if (!response.ok) throw errorForStatus(response.status);
  return response.blob();
}

export function listSupportCannedResponses(
  reference: string,
  locale = "fa",
): Promise<{ items: SupportCannedResponse[] }> {
  return call<{ items: SupportCannedResponse[] }>(
    `/canned-responses${queryString({ reference, locale })}`,
  );
}

export function renderSupportCannedResponse(
  reference: string,
  code: string,
  values: Record<string, string>,
  locale = "fa",
): Promise<{ code: string; version: number; body: string }> {
  return call<{ code: string; version: number; body: string }>(
    `/conversations/${encodeURIComponent(reference)}/canned-responses/${encodeURIComponent(code)}/render`,
    {
      method: "POST",
      body: JSON.stringify({ locale, values }),
    },
  );
}

export function listSupportMacros(): Promise<{ items: SupportMacro[] }> {
  return call<{ items: SupportMacro[] }>("/macros");
}

export function previewSupportMacro(
  reference: string,
  code: string,
  expectedVersion: number,
): Promise<SupportMacroPreview> {
  return call<SupportMacroPreview>(
    `/conversations/${encodeURIComponent(reference)}/macros/${encodeURIComponent(code)}/preview`,
    {
      method: "POST",
      body: JSON.stringify({ expected_version: expectedVersion }),
    },
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
