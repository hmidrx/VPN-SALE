"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";

import {
  addSupportInternalNote,
  changeSupportStatus,
  claimSupportConversation,
  getInternalNotes,
  getSupportConversation,
  listSupportConversations,
  replySupportConversation,
  supportIdempotencyKey,
} from "./api";
import type {
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

export function SupportConsole(): React.ReactElement {
  const [items, setItems] = useState<SupportConversationSummary[]>([]);
  const [selectedReference, setSelectedReference] = useState<string | null>(null);
  const [detail, setDetail] = useState<SupportConversationDetail | null>(null);
  const [notes, setNotes] = useState<SupportMessage[]>([]);
  const [statusFilter, setStatusFilter] = useState<SupportStatus | "">("");
  const [replyBody, setReplyBody] = useState("");
  const [noteBody, setNoteBody] = useState("");
  const [targetStatus, setTargetStatus] = useState<SupportStatus>("IN_PROGRESS");
  const [statusReason, setStatusReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refreshInbox = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await listSupportConversations(statusFilter || undefined);
      setItems(result.items);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "دریافت تیکت‌ها انجام نشد.");
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    void refreshInbox();
  }, [refreshInbox]);

  const openTicket = useCallback(async (reference: string) => {
    setSelectedReference(reference);
    setError(null);
    try {
      const conversation = await getSupportConversation(reference);
      setDetail(conversation);
      setTargetStatus(conversation.status === "NEW" ? "OPEN" : "IN_PROGRESS");
      try {
        const internal = await getInternalNotes(reference);
        setNotes(internal.items);
      } catch {
        setNotes([]);
      }
    } catch (cause) {
      setDetail(null);
      setNotes([]);
      setError(cause instanceof Error ? cause.message : "دریافت تیکت انجام نشد.");
    }
  }, []);

  const visibleItems = useMemo(() => items, [items]);

  async function afterMutation(next: SupportConversationDetail): Promise<void> {
    setDetail(next);
    setSelectedReference(next.reference);
    await refreshInbox();
  }

  async function claim(): Promise<void> {
    if (!detail || busy) return;
    setBusy(true);
    setError(null);
    try {
      await afterMutation(await claimSupportConversation(detail.reference, detail.version));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Claim انجام نشد.");
      await openTicket(detail.reference);
    } finally {
      setBusy(false);
    }
  }

  async function sendReply(): Promise<void> {
    if (!detail || busy || !replyBody.trim()) return;
    setBusy(true);
    setError(null);
    const body = replyBody.trim();
    try {
      const next = await replySupportConversation(
        detail.reference,
        body,
        detail.version,
        supportIdempotencyKey(),
      );
      setReplyBody("");
      await afterMutation(next);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "ارسال پاسخ انجام نشد.");
      await openTicket(detail.reference);
    } finally {
      setBusy(false);
    }
  }

  async function sendInternalNote(): Promise<void> {
    if (!detail || busy || !noteBody.trim()) return;
    setBusy(true);
    setError(null);
    const body = noteBody.trim();
    try {
      await addSupportInternalNote(
        detail.reference,
        body,
        detail.version,
        supportIdempotencyKey(),
      );
      setNoteBody("");
      await openTicket(detail.reference);
      await refreshInbox();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "ثبت یادداشت انجام نشد.");
      await openTicket(detail.reference);
    } finally {
      setBusy(false);
    }
  }

  async function setStatus(): Promise<void> {
    if (!detail || busy || statusReason.trim().length < 3) return;
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
      await openTicket(detail.reference);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main dir="rtl" className="support-console support-runtime-console">
      <header className="support-runtime-header">
        <div>
          <h1>کنسول پشتیبانی</h1>
          <p>Inbox واقعی تیکت‌های مشتری با claim، پاسخ عمومی، یادداشت داخلی و کنترل وضعیت.</p>
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
                  disabled={busy || detail.assigned_to_me}
                >
                  {detail.assigned_to_me ? "در اختیار شما" : detail.assigned ? "Claim توسط اپراتور دیگر" : "Claim تیکت"}
                </button>
              </div>

              <div className="support-runtime-messages" aria-label="پیام‌های عمومی">
                {detail.messages.map((message) => (
                  <article key={`${message.sequence}-${message.created_at}`}>
                    <header>
                      <strong>{senderLabel(message)}</strong>
                      <span>#{message.sequence.toLocaleString("fa-IR")} · {faDate(message.created_at)}</span>
                    </header>
                    <p>{message.body}</p>
                  </article>
                ))}
              </div>

              <section className="support-runtime-actions">
                <h3>پاسخ به مشتری</h3>
                <textarea
                  aria-label="پاسخ عمومی"
                  value={replyBody}
                  onChange={(event) => setReplyBody(event.target.value)}
                  maxLength={4000}
                  rows={5}
                  disabled={busy}
                />
                <button
                  type="button"
                  onClick={() => void sendReply()}
                  disabled={busy || !replyBody.trim()}
                >
                  ارسال پاسخ عمومی
                </button>
              </section>

              <section className="support-runtime-actions support-runtime-internal">
                <h3>یادداشت داخلی</h3>
                <div className="support-runtime-notes">
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
                  onChange={(event) => setNoteBody(event.target.value)}
                  maxLength={4000}
                  rows={3}
                  disabled={busy}
                />
                <button
                  type="button"
                  onClick={() => void sendInternalNote()}
                  disabled={busy || !noteBody.trim()}
                >
                  افزودن یادداشت داخلی
                </button>
              </section>

              <section className="support-runtime-actions">
                <h3>تغییر وضعیت</h3>
                <div className="support-runtime-status-row">
                  <select
                    aria-label="وضعیت جدید"
                    value={targetStatus}
                    onChange={(event) => setTargetStatus(event.target.value as SupportStatus)}
                    disabled={busy}
                  >
                    {statusOptions.map((status) => (
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
              </section>
            </>
          )}
        </section>
      </div>
    </main>
  );
}
