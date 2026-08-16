"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";

import {
  addSupportInternalNote,
  changeSupportStatus,
  claimSupportConversation,
  downloadSupportAttachment,
  getInternalNotes,
  getSupportConversation,
  listSupportAttachments,
  listSupportConversations,
  replySupportConversation,
  supportIdempotencyKey,
} from "./api";
import styles from "./SupportConsole.module.css";
import type {
  SupportAttachment,
  SupportConversationDetail,
  SupportConversationSummary,
  SupportMessage,
  SupportStatus,
} from "./types";

const statusLabels: Record<SupportStatus, string> = {
  NEW: "جدید",
  OPEN: "باز",
  ASSIGNED: "ارجاع‌شده",
  IN_PROGRESS: "در حال بررسی",
  WAITING_FOR_CUSTOMER: "منتظر مشتری",
  WAITING_FOR_SUPPORT: "منتظر پشتیبانی",
  ESCALATED: "ارجاع ویژه",
  RESOLVED: "حل‌شده",
  CLOSED: "بسته",
  REOPENED: "بازگشایی‌شده",
  SPAM: "اسپم",
  ARCHIVED: "بایگانی",
};

const statusOptions = Object.keys(statusLabels) as SupportStatus[];

const legalTransitions: Record<SupportStatus, readonly SupportStatus[]> = {
  NEW: ["OPEN", "ASSIGNED", "SPAM", "CLOSED"],
  OPEN: ["ASSIGNED", "IN_PROGRESS", "WAITING_FOR_CUSTOMER", "RESOLVED", "ESCALATED", "CLOSED", "SPAM"],
  ASSIGNED: ["IN_PROGRESS", "WAITING_FOR_CUSTOMER", "RESOLVED", "ESCALATED", "CLOSED"],
  IN_PROGRESS: ["WAITING_FOR_CUSTOMER", "WAITING_FOR_SUPPORT", "RESOLVED", "ESCALATED", "CLOSED"],
  WAITING_FOR_CUSTOMER: ["IN_PROGRESS", "RESOLVED", "ESCALATED", "CLOSED"],
  WAITING_FOR_SUPPORT: ["IN_PROGRESS", "WAITING_FOR_CUSTOMER", "RESOLVED", "ESCALATED", "CLOSED"],
  ESCALATED: ["IN_PROGRESS", "WAITING_FOR_CUSTOMER", "RESOLVED", "CLOSED"],
  RESOLVED: ["CLOSED", "REOPENED"],
  CLOSED: ["REOPENED", "ARCHIVED"],
  REOPENED: ["IN_PROGRESS", "WAITING_FOR_SUPPORT", "RESOLVED", "ESCALATED"],
  SPAM: ["ARCHIVED"],
  ARCHIVED: [],
};

const replyBlockedStatuses = new Set<SupportStatus>(["RESOLVED", "CLOSED", "SPAM", "ARCHIVED"]);

function faDate(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("fa-IR", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(date);
}

function senderLabel(message: SupportMessage): string {
  if (message.message_type === "INTERNAL_NOTE") return "یادداشت داخلی";
  return message.sender_type === "CUSTOMER" ? "مشتری" : "پشتیبانی";
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value.toLocaleString("fa-IR")} بایت`;
  return `${(value / 1024).toLocaleString("fa-IR", { maximumFractionDigits: 1 })} کیلوبایت`;
}

function mergeMessages(older: SupportMessage[], newer: SupportMessage[]): SupportMessage[] {
  const bySequence = new Map<number, SupportMessage>();
  for (const message of [...older, ...newer]) bySequence.set(message.sequence, message);
  return Array.from(bySequence.values()).sort((left, right) => left.sequence - right.sequence);
}

function appendConversations(
  current: SupportConversationSummary[],
  next: SupportConversationSummary[],
): SupportConversationSummary[] {
  const references = new Set(current.map((item) => item.reference));
  return [...current, ...next.filter((item) => !references.has(item.reference))];
}

export function SupportConsole(): React.ReactElement {
  const [items, setItems] = useState<SupportConversationSummary[]>([]);
  const [inboxNextCursor, setInboxNextCursor] = useState<string | null>(null);
  const [selectedReference, setSelectedReference] = useState<string | null>(null);
  const [detail, setDetail] = useState<SupportConversationDetail | null>(null);
  const [attachments, setAttachments] = useState<SupportAttachment[]>([]);
  const [notes, setNotes] = useState<SupportMessage[]>([]);
  const [notesNextCursor, setNotesNextCursor] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<SupportStatus | "">("");
  const [replyBody, setReplyBody] = useState("");
  const [replyKey, setReplyKey] = useState(() => supportIdempotencyKey());
  const [noteBody, setNoteBody] = useState("");
  const [noteKey, setNoteKey] = useState(() => supportIdempotencyKey());
  const [targetStatus, setTargetStatus] = useState<SupportStatus>("OPEN");
  const [statusReason, setStatusReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState<"inbox" | "messages" | "notes" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refreshInbox = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await listSupportConversations(statusFilter || undefined);
      setItems(result.items);
      setInboxNextCursor(result.next_cursor);
    } catch (cause) {
      setItems([]);
      setInboxNextCursor(null);
      setError(cause instanceof Error ? cause.message : "دریافت تیکت‌ها انجام نشد.");
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    void refreshInbox();
  }, [refreshInbox]);

  const openTicket = useCallback(async (reference: string, preserveDraft = false) => {
    setSelectedReference(reference);
    setError(null);
    if (!preserveDraft) {
      setReplyBody("");
      setReplyKey(supportIdempotencyKey());
      setNoteBody("");
      setNoteKey(supportIdempotencyKey());
      setStatusReason("");
    }
    try {
      const conversation = await getSupportConversation(reference);
      setDetail(conversation);
      const available = legalTransitions[conversation.status];
      if (available.length > 0) setTargetStatus(available[0]);
      try {
        const attachmentPage = await listSupportAttachments(reference);
        setAttachments(attachmentPage.items);
      } catch {
        setAttachments([]);
      }
      try {
        const internal = await getInternalNotes(reference);
        setNotes(internal.items);
        setNotesNextCursor(internal.next_cursor);
      } catch {
        setNotes([]);
        setNotesNextCursor(null);
      }
    } catch (cause) {
      setDetail(null);
      setAttachments([]);
      setNotes([]);
      setNotesNextCursor(null);
      setError(cause instanceof Error ? cause.message : "دریافت تیکت انجام نشد.");
    }
  }, []);

  const visibleItems = useMemo(() => items, [items]);
  const attachmentsBySequence = useMemo(() => {
    const grouped = new Map<number, SupportAttachment[]>();
    for (const attachment of attachments) {
      const current = grouped.get(attachment.message_sequence) ?? [];
      current.push(attachment);
      grouped.set(attachment.message_sequence, current);
    }
    return grouped;
  }, [attachments]);
  const allowedTargetStatuses = detail ? legalTransitions[detail.status] : [];
  const replyAllowed = detail ? !replyBlockedStatuses.has(detail.status) : false;
  const noteAllowed = detail?.status !== "ARCHIVED";

  async function loadMoreInbox(): Promise<void> {
    if (!inboxNextCursor || loadingMore || loading) return;
    setLoadingMore("inbox");
    setError(null);
    try {
      const result = await listSupportConversations(statusFilter || undefined, inboxNextCursor);
      setItems((current) => appendConversations(current, result.items));
      setInboxNextCursor(result.next_cursor);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "دریافت تیکت‌های قدیمی‌تر انجام نشد.");
    } finally {
      setLoadingMore(null);
    }
  }

  async function loadOlderMessages(): Promise<void> {
    if (!detail?.messages_next_cursor || loadingMore) return;
    const reference = detail.reference;
    const cursor = detail.messages_next_cursor;
    setLoadingMore("messages");
    setError(null);
    try {
      const older = await getSupportConversation(reference, cursor);
      setDetail((current) => {
        if (!current || current.reference !== reference) return current;
        return {
          ...current,
          messages: mergeMessages(older.messages, current.messages),
          messages_next_cursor: older.messages_next_cursor,
        };
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "دریافت پیام‌های قدیمی‌تر انجام نشد.");
    } finally {
      setLoadingMore(null);
    }
  }

  async function loadOlderNotes(): Promise<void> {
    if (!detail || !notesNextCursor || loadingMore) return;
    const reference = detail.reference;
    const cursor = notesNextCursor;
    setLoadingMore("notes");
    setError(null);
    try {
      const older = await getInternalNotes(reference, cursor);
      setNotes((current) => mergeMessages(older.items, current));
      setNotesNextCursor(older.next_cursor);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "دریافت یادداشت‌های قدیمی‌تر انجام نشد.");
    } finally {
      setLoadingMore(null);
    }
  }

  async function downloadAttachment(attachment: SupportAttachment): Promise<void> {
    if (!detail || busy) return;
    setBusy(true);
    setError(null);
    try {
      const blob = await downloadSupportAttachment(detail.reference, attachment.asset_reference);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = attachment.filename;
      anchor.rel = "noopener";
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "دریافت تصویر پیوست انجام نشد.");
    } finally {
      setBusy(false);
    }
  }

  async function afterMutation(next: SupportConversationDetail): Promise<void> {
    setDetail(next);
    setSelectedReference(next.reference);
    const available = legalTransitions[next.status];
    if (available.length > 0) setTargetStatus(available[0]);
    await refreshInbox();
  }

  async function claim(): Promise<void> {
    if (!detail || busy || detail.assigned) return;
    setBusy(true);
    setError(null);
    try {
      await afterMutation(await claimSupportConversation(detail.reference, detail.version));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Claim انجام نشد.");
      await openTicket(detail.reference, true);
    } finally {
      setBusy(false);
    }
  }

  async function sendReply(): Promise<void> {
    if (!detail || busy || !replyAllowed || !replyBody.trim()) return;
    setBusy(true);
    setError(null);
    const body = replyBody.trim();
    try {
      const next = await replySupportConversation(detail.reference, body, detail.version, replyKey);
      setReplyBody("");
      setReplyKey(supportIdempotencyKey());
      await afterMutation(next);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "ارسال پاسخ انجام نشد.");
      await openTicket(detail.reference, true);
    } finally {
      setBusy(false);
    }
  }

  async function sendInternalNote(): Promise<void> {
    if (!detail || busy || !noteAllowed || !noteBody.trim()) return;
    setBusy(true);
    setError(null);
    const body = noteBody.trim();
    try {
      await addSupportInternalNote(detail.reference, body, detail.version, noteKey);
      setNoteBody("");
      setNoteKey(supportIdempotencyKey());
      await openTicket(detail.reference, true);
      await refreshInbox();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "ثبت یادداشت انجام نشد.");
      await openTicket(detail.reference, true);
    } finally {
      setBusy(false);
    }
  }

  async function setStatus(): Promise<void> {
    if (
      !detail ||
      busy ||
      !allowedTargetStatuses.includes(targetStatus) ||
      statusReason.trim().length < 3
    ) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const next = await changeSupportStatus(
        detail.reference,
        targetStatus,
        statusReason.trim(),
        detail.version,
      );
      setStatusReason("");
      await afterMutation(next);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "تغییر وضعیت انجام نشد.");
      await openTicket(detail.reference, true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main dir="rtl" className={`support-console support-runtime-console ${styles.console}`}>
      <header className="support-runtime-header">
        <div>
          <h1>کنسول پشتیبانی</h1>
          <p>Inbox واقعی تیکت‌های مشتری با claim، پاسخ عمومی، تصویر پیوست، یادداشت داخلی و تاریخچه صفحه‌بندی‌شده.</p>
        </div>
        <button type="button" onClick={() => void refreshInbox()} disabled={loading || busy}>
          {loading ? "در حال دریافت…" : "تازه‌سازی"}
        </button>
      </header>

      {error ? <div role="alert" className="support-runtime-error">{error}</div> : null}

      <div className="support-runtime-layout">
        <aside className="support-runtime-inbox" aria-label="فهرست تیکت‌ها">
          <label>
            وضعیت
            <select
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value as SupportStatus | "")}
            >
              <option value="">همه وضعیت‌ها</option>
              {statusOptions.map((status) => (
                <option value={status} key={status}>{statusLabels[status]}</option>
              ))}
            </select>
          </label>

          {loading ? <p>در حال دریافت تیکت‌ها…</p> : null}
          {!loading && visibleItems.length === 0 ? <p>تیکتی در این فیلتر وجود ندارد.</p> : null}
          <div className="support-runtime-ticket-list">
            {visibleItems.map((item) => (
              <button
                type="button"
                key={item.reference}
                className={selectedReference === item.reference ? "is-active" : undefined}
                onClick={() => void openTicket(item.reference)}
              >
                <strong>{item.subject}</strong>
                <span>{statusLabels[item.status]} · {item.priority}</span>
                <small>{item.reference} · {faDate(item.updated_at)}</small>
              </button>
            ))}
          </div>
          {inboxNextCursor ? (
            <button
              type="button"
              onClick={() => void loadMoreInbox()}
              disabled={loadingMore !== null || loading}
            >
              {loadingMore === "inbox" ? "در حال دریافت…" : "نمایش تیکت‌های قدیمی‌تر"}
            </button>
          ) : null}
        </aside>

        <section className="support-runtime-detail" aria-label="جزئیات مکالمه">
          {!detail ? (
            <div className="support-runtime-empty">
              <h2>یک تیکت را انتخاب کنید</h2>
              <p>متن مشتری و عملیات پشتیبانی بعد از انتخاب تیکت نمایش داده می‌شود.</p>
            </div>
          ) : (
            <>
              <div className="support-runtime-ticket-head">
                <div>
                  <h2>{detail.subject}</h2>
                  <p>
                    {detail.reference} · {statusLabels[detail.status]} · نسخه {detail.version.toLocaleString("fa-IR")}
                  </p>
                  <p>
                    SLA پاسخ اول: {faDate(detail.first_response_deadline)} · حل: {faDate(detail.resolution_deadline)}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => void claim()}
                  disabled={busy || detail.assigned}
                >
                  {detail.assigned_to_me
                    ? "در اختیار شما"
                    : detail.assigned
                      ? "در اختیار اپراتور دیگر"
                      : "Claim تیکت"}
                </button>
              </div>

              <div className="support-runtime-messages" aria-label="پیام‌های عمومی">
                {detail.messages_next_cursor ? (
                  <button
                    type="button"
                    onClick={() => void loadOlderMessages()}
                    disabled={loadingMore !== null}
                  >
                    {loadingMore === "messages" ? "در حال دریافت…" : "نمایش پیام‌های قدیمی‌تر"}
                  </button>
                ) : null}
                {detail.messages.map((message) => (
                  <article key={`${message.sequence}-${message.created_at}`}>
                    <header>
                      <strong>{senderLabel(message)}</strong>
                      <span>#{message.sequence.toLocaleString("fa-IR")} · {faDate(message.created_at)}</span>
                    </header>
                    <p>{message.body}</p>
                    {(attachmentsBySequence.get(message.sequence) ?? []).map((attachment) => (
                      <button
                        type="button"
                        key={attachment.asset_reference}
                        onClick={() => void downloadAttachment(attachment)}
                        disabled={busy}
                      >
                        📎 دانلود تصویر · {formatBytes(attachment.byte_size)}
                      </button>
                    ))}
                  </article>
                ))}
              </div>

              <section className="support-runtime-actions">
                <h3>پاسخ به مشتری</h3>
                {!replyAllowed ? <p className="muted">در وضعیت فعلی ارسال پاسخ عمومی مجاز نیست.</p> : null}
                <textarea
                  aria-label="پاسخ عمومی"
                  value={replyBody}
                  onChange={(event) => {
                    setReplyBody(event.target.value);
                    setReplyKey(supportIdempotencyKey());
                  }}
                  maxLength={4000}
                  rows={5}
                  disabled={busy || !replyAllowed}
                />
                <button
                  type="button"
                  onClick={() => void sendReply()}
                  disabled={busy || !replyAllowed || !replyBody.trim()}
                >
                  ارسال پاسخ عمومی
                </button>
              </section>

              <section className="support-runtime-actions support-runtime-internal">
                <h3>یادداشت داخلی</h3>
                <div className="support-runtime-notes">
                  {notesNextCursor ? (
                    <button
                      type="button"
                      onClick={() => void loadOlderNotes()}
                      disabled={loadingMore !== null}
                    >
                      {loadingMore === "notes" ? "در حال دریافت…" : "نمایش یادداشت‌های قدیمی‌تر"}
                    </button>
                  ) : null}
                  {notes.length === 0 ? <p>یادداشت داخلی قابل نمایش نیست یا هنوز ثبت نشده است.</p> : null}
                  {notes.map((note) => (
                    <article key={`${note.sequence}-${note.created_at}`}>
                      <strong>{faDate(note.created_at)}</strong>
                      <p>{note.body}</p>
                    </article>
                  ))}
                </div>
                <textarea
                  aria-label="یادداشت داخلی"
                  value={noteBody}
                  onChange={(event) => {
                    setNoteBody(event.target.value);
                    setNoteKey(supportIdempotencyKey());
                  }}
                  maxLength={4000}
                  rows={3}
                  disabled={busy || !noteAllowed}
                />
                <button
                  type="button"
                  onClick={() => void sendInternalNote()}
                  disabled={busy || !noteAllowed || !noteBody.trim()}
                >
                  افزودن یادداشت داخلی
                </button>
              </section>

              <section className="support-runtime-actions">
                <h3>تغییر وضعیت</h3>
                {allowedTargetStatuses.length === 0 ? (
                  <p className="muted">برای این وضعیت انتقال دیگری مجاز نیست.</p>
                ) : (
                  <div className="support-runtime-status-row">
                    <select
                      aria-label="وضعیت جدید"
                      value={targetStatus}
                      onChange={(event) => setTargetStatus(event.target.value as SupportStatus)}
                      disabled={busy}
                    >
                      {allowedTargetStatuses.map((status) => (
                        <option value={status} key={status}>{statusLabels[status]}</option>
                      ))}
                    </select>
                    <input
                      aria-label="دلیل تغییر وضعیت"
                      value={statusReason}
                      onChange={(event) => setStatusReason(event.target.value)}
                      maxLength={500}
                      placeholder="دلیل تغییر وضعیت"
                      disabled={busy}
                    />
                    <button
                      type="button"
                      onClick={() => void setStatus()}
                      disabled={busy || statusReason.trim().length < 3}
                    >
                      اعمال وضعیت
                    </button>
                  </div>
                )}
              </section>
            </>
          )}
        </section>
      </div>
    </main>
  );
}