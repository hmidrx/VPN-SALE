"use client";

import React from "react";
import { loadCustomerConfig } from "../config/public-config";
import {
  EmptyState,
  ErrorState,
  PageHeader,
  PageShell,
  PremiumCard,
  StatusBadge,
} from "../components/customer-ui";
import {
  createSupportTicket,
  fetchSupportAttachmentBlob,
  getSupportTicket,
  listSupportTickets,
  replySupportTicket,
  SupportApiError,
  uploadSupportImage,
  type SupportAttachment,
  type SupportTicket,
  type SupportTicketSummary,
} from "./api";
import styles from "./Support.module.css";

const statusText: Record<string, string> = {
  NEW: "جدید",
  TRIAGED: "در صف بررسی",
  IN_PROGRESS: "در حال بررسی",
  WAITING_FOR_CUSTOMER: "منتظر پاسخ شما",
  WAITING_FOR_SUPPORT: "منتظر پشتیبانی",
  RESOLVED: "حل‌شده",
  CLOSED: "بسته",
  REOPENED: "بازگشایی‌شده",
};

function tone(status: string): "success" | "warning" | "danger" | "neutral" {
  if (["RESOLVED", "CLOSED"].includes(status)) return "success";
  if (status === "WAITING_FOR_CUSTOMER") return "warning";
  if (["SPAM", "ARCHIVED"].includes(status)) return "danger";
  return "neutral";
}

function faDate(value: string): string {
  try {
    return new Intl.DateTimeFormat("fa-IR", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
  } catch {
    return "—";
  }
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value.toLocaleString("fa-IR")} بایت`;
  return `${(value / 1024).toLocaleString("fa-IR", { maximumFractionDigits: 1 })} کیلوبایت`;
}

function AttachmentPreview({ reference, attachment }: { reference: string; attachment: SupportAttachment }): React.ReactElement {
  const [url, setUrl] = React.useState<string | null>(null);
  const [failed, setFailed] = React.useState(false);

  React.useEffect(() => {
    const controller = new AbortController();
    let objectUrl: string | null = null;
    setUrl(null);
    setFailed(false);
    void fetchSupportAttachmentBlob(reference, attachment.asset_reference, controller.signal)
      .then((blob) => {
        if (controller.signal.aborted) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      });
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [reference, attachment.asset_reference]);

  if (failed) return <span className={styles.fileHint}>نمایش تصویر ممکن نشد.</span>;
  if (!url) return <span className={styles.fileHint}>در حال دریافت تصویر…</span>;
  return <a className={styles.attachmentCard} href={url} target="_blank" rel="noreferrer">
    <img className={styles.attachmentImage} src={url} alt="تصویر پیوست پشتیبانی" />
    <span>{formatBytes(attachment.byte_size)}</span>
  </a>;
}

export function CustomerSupportHome(): React.ReactElement {
  const botUsername = loadCustomerConfig().botUsername;
  const [tickets, setTickets] = React.useState<SupportTicketSummary[]>([]);
  const [selected, setSelected] = React.useState<string | null>(null);
  const [detail, setDetail] = React.useState<SupportTicket | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [failed, setFailed] = React.useState(false);
  const [pending, setPending] = React.useState(false);
  const [imagePending, setImagePending] = React.useState(false);
  const [notice, setNotice] = React.useState<string | null>(null);
  const [creating, setCreating] = React.useState(false);

  const loadTickets = React.useCallback(async (): Promise<void> => {
    setLoading(true);
    setFailed(false);
    try {
      const items = await listSupportTickets();
      setTickets(items);
      if (!selected && items[0]) setSelected(items[0].reference);
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, [selected]);

  React.useEffect(() => { void loadTickets(); }, [loadTickets]);

  React.useEffect(() => {
    if (!selected) {
      setDetail(null);
      return;
    }
    const controller = new AbortController();
    setDetail(null);
    void getSupportTicket(selected, controller.signal)
      .then((value) => { if (!controller.signal.aborted) setDetail(value); })
      .catch(() => { if (!controller.signal.aborted) setNotice("دریافت گفت‌وگو ممکن نشد. دوباره تلاش کنید."); });
    return () => controller.abort();
  }, [selected]);

  async function createTicket(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (pending) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    setPending(true);
    setNotice(null);
    try {
      const created = await createSupportTicket(
        String(data.get("subject") ?? ""),
        String(data.get("message") ?? ""),
      );
      form.reset();
      setCreating(false);
      setSelected(created.reference);
      setDetail(created);
      setNotice("درخواست شما ثبت شد و در صف پشتیبانی قرار گرفت.");
      await loadTickets();
    } catch {
      setNotice("ثبت درخواست انجام نشد. متن را بررسی کنید و دوباره تلاش کنید.");
    } finally {
      setPending(false);
    }
  }

  async function reply(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!detail || pending) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    const body = String(data.get("message") ?? "");
    if (!body.trim()) return;
    setPending(true);
    setNotice(null);
    try {
      const updated = await replySupportTicket(detail.reference, body);
      form.reset();
      setDetail(updated);
      setNotice("پاسخ شما ارسال شد.");
      await loadTickets();
    } catch {
      setNotice("ارسال پاسخ انجام نشد. دوباره تلاش کنید.");
    } finally {
      setPending(false);
    }
  }

  async function uploadImage(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!detail || imagePending) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    const file = data.get("image");
    if (!(file instanceof File) || file.size === 0) {
      setNotice("ابتدا یک تصویر انتخاب کنید.");
      return;
    }
    if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
      setNotice("فقط تصویر JPEG، PNG یا WebP قابل ارسال است.");
      return;
    }
    setImagePending(true);
    setNotice(null);
    try {
      await uploadSupportImage(detail.reference, file);
      const refreshed = await getSupportTicket(detail.reference);
      form.reset();
      setDetail(refreshed);
      setNotice("تصویر با موفقیت و به‌صورت امن ارسال شد.");
      await loadTickets();
    } catch (error) {
      if (error instanceof SupportApiError && error.status === 413) {
        setNotice("حجم تصویر بیشتر از حد مجاز است.");
      } else if (error instanceof SupportApiError && error.status === 415) {
        setNotice("فرمت این تصویر پشتیبانی نمی‌شود.");
      } else {
        setNotice("ارسال تصویر انجام نشد. دوباره تلاش کنید.");
      }
    } finally {
      setImagePending(false);
    }
  }

  return <PageShell labelledBy="page-title">
    <PageHeader
      title="پشتیبانی"
      subtitle="تیکت را مستقیم از سایت ثبت و پیگیری کنید؛ تلگرام فقط یک راه ارتباطی اختیاری است."
      action={<button className="ui-button" type="button" onClick={() => setCreating((value) => !value)}>{creating ? "بستن فرم" : "درخواست جدید"}</button>}
    />

    {notice ? <p className={styles.notice} role="status">{notice}</p> : null}

    {creating ? <PremiumCard>
      <form className={styles.form} onSubmit={(event) => void createTicket(event)}>
        <h2>درخواست جدید</h2>
        <label htmlFor="support-subject">موضوع</label>
        <input id="support-subject" name="subject" minLength={3} maxLength={160} required />
        <label htmlFor="support-message">شرح درخواست</label>
        <textarea id="support-message" name="message" maxLength={4000} required />
        <div className={styles.actions}>
          <button className="ui-button" type="submit" disabled={pending}>{pending ? "در حال ثبت…" : "ثبت درخواست"}</button>
          <button type="button" onClick={() => setCreating(false)}>انصراف</button>
        </div>
      </form>
    </PremiumCard> : null}

    {loading ? <p role="status">در حال دریافت درخواست‌های پشتیبانی…</p> : failed ? <ErrorState onRetry={() => void loadTickets()} /> : tickets.length === 0 ? <EmptyState title="هنوز تیکتی ندارید" description="برای پرسش، مشکل سرویس یا پیگیری خرید، یک درخواست جدید ثبت کنید." action={<button className="ui-button" type="button" onClick={() => setCreating(true)}>ساخت اولین تیکت</button>} /> : <div className={styles.layout}>
      <aside className={styles.sidebar} aria-label="درخواست‌های پشتیبانی">
        {tickets.map((ticket) => <PremiumCard key={ticket.reference}>
          <button className={styles.ticketButton} type="button" onClick={() => setSelected(ticket.reference)} aria-current={selected === ticket.reference ? "true" : undefined}>
            <strong>{ticket.subject}</strong>
            <div className={styles.ticketMeta}>
              <StatusBadge tone={tone(ticket.status)}>{statusText[ticket.status] ?? ticket.status}</StatusBadge>
              <small>{faDate(ticket.updated_at)}</small>
            </div>
          </button>
        </PremiumCard>)}
        {botUsername ? <a href={`https://t.me/${botUsername}`} rel="noreferrer">ارتباط اختیاری از طریق تلگرام</a> : null}
      </aside>

      <section className={styles.thread} aria-live="polite">
        {!selected ? <div className={styles.emptyThread}>یک تیکت را انتخاب کنید.</div> : !detail ? <p role="status">در حال دریافت گفت‌وگو…</p> : <>
          <PremiumCard>
            <div className={styles.ticketMeta}>
              <div><h2>{detail.subject}</h2><small>{detail.reference}</small></div>
              <StatusBadge tone={tone(detail.status)}>{statusText[detail.status] ?? detail.status}</StatusBadge>
            </div>
          </PremiumCard>
          <div className={styles.messages} aria-label="گفت‌وگوی پشتیبانی">
            {detail.messages.map((item) => {
              const customer = item.sender_type === "CUSTOMER";
              return <div className={`${styles.message} ${customer ? styles.customer : styles.agent}`} key={item.sequence}>
                <strong>{customer ? "شما" : "پشتیبانی"}</strong>
                <div>{item.body}</div>
                {item.attachments.map((attachment) => <AttachmentPreview key={attachment.asset_reference} reference={detail.reference} attachment={attachment} />)}
                <small>{faDate(item.created_at)}</small>
              </div>;
            })}
          </div>
          {!(["SPAM", "ARCHIVED"].includes(detail.status)) ? <PremiumCard>
            <form className={styles.form} onSubmit={(event) => void reply(event)}>
              <label htmlFor="support-reply">پاسخ شما</label>
              <textarea id="support-reply" name="message" maxLength={4000} required />
              <button className="ui-button" type="submit" disabled={pending}>{pending ? "در حال ارسال…" : "ارسال پاسخ"}</button>
            </form>
            <form className={styles.imageForm} onSubmit={(event) => void uploadImage(event)}>
              <label htmlFor="support-image">پیوست تصویر</label>
              <input id="support-image" name="image" type="file" accept="image/jpeg,image/png,image/webp" required />
              <span className={styles.fileHint}>JPEG، PNG یا WebP؛ فایل قبل از ذخیره‌سازی پاک‌سازی و نرمال می‌شود.</span>
              <button type="submit" disabled={imagePending}>{imagePending ? "در حال ارسال تصویر…" : "ارسال تصویر"}</button>
            </form>
          </PremiumCard> : null}
        </>}
      </section>
    </div>}
  </PageShell>;
}
