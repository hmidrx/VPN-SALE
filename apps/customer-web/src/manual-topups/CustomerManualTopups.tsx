"use client";

import React from "react";
import {
  cancelManualTopup,
  createManualTopup,
  getManualTopup,
  listManualTopups,
  logicalKey,
  privateReceiptObjectUrl,
  uploadReceipt,
} from "./api";
import { statusLabels, toman, tomanToRial } from "./format";
import type { ManualTopup, ManualTopupStatus } from "./types";

const presets = [100_000, 250_000, 500_000, 1_000_000, 2_000_000];
const formatToman = (value: number): string =>
  new Intl.NumberFormat("fa-IR").format(value);
const shortReference = (value: string): string =>
  value.length > 10 ? `${value.slice(0, 4)}…${value.slice(-4)}` : value;
const date = (value: string): string =>
  new Date(value).toLocaleString("fa-IR", {
    dateStyle: "medium",
    timeStyle: "short",
  });
const statusTone: Record<ManualTopupStatus, string> = {
  AWAITING_SUPPORT: "info",
  AWAITING_RECEIPT: "warn",
  UNDER_REVIEW: "info",
  NEEDS_RESUBMISSION: "warn",
  APPROVED: "success",
  REJECTED: "danger",
  CANCELLED: "muted",
  EXPIRED: "muted",
};
const nextSteps: Record<ManualTopupStatus, string> = {
  AWAITING_SUPPORT: "اطلاعات کارت را از پشتیبانی دریافت کنید.",
  AWAITING_RECEIPT: "تصویر فیش واریز را همین‌جا ارسال کنید.",
  UNDER_REVIEW: "فیش شما دریافت شد؛ نتیجه بررسی اطلاع‌رسانی می‌شود.",
  NEEDS_RESUBMISSION: "یک تصویر واضح و کامل از فیش دوباره ارسال کنید.",
  APPROVED: "موجودی کیف پول شما افزایش یافت.",
  REJECTED: "پیام بررسی را ببینید و در صورت نیاز درخواست تازه بسازید.",
  CANCELLED: "این درخواست لغو شده است.",
  EXPIRED: "مهلت این درخواست پایان یافته است.",
};

function UploadIcon(): React.ReactElement {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M5 14v4a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-4" />
    </svg>
  );
}

export function CustomerManualTopups({
  enabled,
  reference,
}: {
  enabled: boolean;
  reference?: string;
}): React.ReactElement {
  if (!enabled)
    return (
      <section className="manual-state">
        <h1>افزایش موجودی</h1>
        <p>در حال حاضر روش پرداخت فعالی در دسترس نیست.</p>
      </section>
    );
  return reference ? <ManualDetail reference={reference} /> : <ManualHome />;
}

function ManualHome(): React.ReactElement {
  const [amount, setAmount] = React.useState(formatToman(100_000));
  const [items, setItems] = React.useState<ManualTopup[]>([]);
  const [busy, setBusy] = React.useState(false);
  const [historyState, setHistoryState] = React.useState<
    "loading" | "ready" | "error"
  >("loading");
  const [error, setError] = React.useState("");
  const key = React.useRef<string>(undefined);
  const numericAmount = React.useMemo(() => {
    try {
      return tomanToRial(amount) / 10;
    } catch {
      return 0;
    }
  }, [amount]);
  const loadHistory = React.useCallback(() => {
    const controller = new AbortController();
    setHistoryState("loading");
    void listManualTopups(controller.signal)
      .then((x) => {
        setItems(x.items);
        setHistoryState("ready");
      })
      .catch(() => setHistoryState("error"));
    return controller;
  }, []);
  React.useEffect(() => {
    const controller = loadHistory();
    return () => controller.abort();
  }, [loadHistory]);
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setError("");
    let rial: number;
    try {
      rial = tomanToRial(amount);
    } catch {
      setError("مبلغ باید حداقل ۱۰۰٬۰۰۰ تومان باشد.");
      return;
    }
    setBusy(true);
    key.current ??= logicalKey();
    const controller = new AbortController();
    try {
      const created = await createManualTopup(
        rial,
        key.current,
        controller.signal,
      );
      location.assign(
        `/wallet/top-up/manual/${encodeURIComponent(created.reference)}`,
      );
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "انجام درخواست ممکن نشد.",
      );
      setBusy(false);
    }
  };
  return (
    <main className="manual-page">
      <header className="manual-hero">
        <span className="manual-hero-icon">＋</span>
        <div>
          <p className="eyebrow">کیف پول</p>
          <h1>افزایش موجودی کارت‌به‌کارت</h1>
          <p>مبلغ را انتخاب کنید؛ سپس فیش واریز را امن ارسال کنید.</p>
        </div>
      </header>
      <form
        className="manual-card manual-create"
        onSubmit={(event) => void submit(event)}
        noValidate
      >
        <fieldset disabled={busy}>
          <legend>مبلغ افزایش موجودی</legend>
          <label htmlFor="manual-amount">مبلغ به تومان</label>
          <div className={`manual-amount-input ${error ? "is-invalid" : ""}`}>
            <input
              id="manual-amount"
              inputMode="numeric"
              value={amount}
              onChange={(event) => {
                setAmount(event.target.value);
                setError("");
              }}
              aria-describedby="manual-min manual-error"
              aria-invalid={Boolean(error)}
            />
            <span>تومان</span>
          </div>
          <small id="manual-min">حداقل مبلغ ۱۰۰٬۰۰۰ تومان</small>
          <div className="manual-presets" aria-label="مبلغ‌های پیشنهادی">
            {presets.map((value) => (
              <button
                type="button"
                key={value}
                aria-pressed={numericAmount === value}
                onClick={() => setAmount(formatToman(value))}
              >
                {formatToman(value)} <small>تومان</small>
              </button>
            ))}
          </div>
          <section className="manual-method" aria-label="اطلاعات پرداخت">
            <span aria-hidden="true">◈</span>
            <div>
              <strong>کارت‌به‌کارت</strong>
              <p>دریافت اطلاعات کارت از پشتیبانی</p>
            </div>
            <i aria-hidden="true">✓</i>
          </section>
          {error && (
            <p className="manual-alert" id="manual-error" role="alert">
              {error}
            </p>
          )}
          <button className="manual-primary" disabled={busy}>
            {busy ? "در حال ثبت درخواست…" : "ادامه و ایجاد درخواست"}
          </button>
        </fieldset>
      </form>
      <History items={items} state={historyState} refresh={loadHistory} />
    </main>
  );
}

function History({
  items,
  state,
  refresh,
}: {
  items: ManualTopup[];
  state: "loading" | "ready" | "error";
  refresh: () => AbortController;
}): React.ReactElement {
  return (
    <section
      className="manual-history-section"
      aria-labelledby="manual-history"
    >
      <header>
        <div>
          <p className="eyebrow">پیگیری سریع</p>
          <h2 id="manual-history">درخواست‌های اخیر</h2>
        </div>
        <button
          type="button"
          className="manual-refresh"
          disabled={state === "loading"}
          onClick={() => refresh()}
          aria-label="به‌روزرسانی درخواست‌ها"
        >
          ↻
        </button>
      </header>
      {state === "loading" && (
        <div className="manual-list-state" role="status">
          <span className="manual-spinner" />
          در حال دریافت درخواست‌ها…
        </div>
      )}
      {state === "error" && (
        <div className="manual-list-state is-error" role="alert">
          <strong>دریافت درخواست‌ها ممکن نشد</strong>
          <button type="button" onClick={() => refresh()}>
            تلاش دوباره
          </button>
        </div>
      )}
      {state === "ready" && items.length === 0 && (
        <div className="manual-list-state">
          <span className="manual-empty-icon">◇</span>
          <strong>هنوز درخواستی ندارید</strong>
          <p>نخستین درخواست شما پس از ثبت اینجا دیده می‌شود.</p>
        </div>
      )}
      {state === "ready" && items.length > 0 && (
        <div className="manual-history">
          {items.map((item) => (
            <a
              href={`/wallet/top-up/manual/${encodeURIComponent(item.reference)}`}
              key={item.reference}
            >
              <div>
                <strong>{toman(item.requested_amount_rial)}</strong>
                <span className={`manual-status ${statusTone[item.status]}`}>
                  {statusLabels[item.status]}
                </span>
              </div>
              <div>
                <time>{date(item.created_at)}</time>
                <bdi>پیگیری {shortReference(item.reference)}</bdi>
                <i aria-hidden="true">‹</i>
              </div>
            </a>
          ))}
        </div>
      )}
    </section>
  );
}

function useReceipt(reference: string, has: boolean): string | undefined {
  const [url, setUrl] = React.useState<string>();
  React.useEffect(() => {
    if (!has) return;
    const controller = new AbortController();
    let current: string | undefined;
    void privateReceiptObjectUrl(reference, controller.signal)
      .then((value) => {
        current = value;
        setUrl(value);
      })
      .catch(() => undefined);
    return () => {
      controller.abort();
      if (current) URL.revokeObjectURL(current);
    };
  }, [reference, has]);
  return url;
}

function ManualDetail({
  reference,
}: {
  reference: string;
}): React.ReactElement {
  const [data, setData] = React.useState<ManualTopup>();
  const [file, setFile] = React.useState<File>();
  const [preview, setPreview] = React.useState<string>();
  const [progress, setProgress] = React.useState(0);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const key = React.useRef<string>(undefined);
  const load = React.useCallback(
    () =>
      getManualTopup(reference)
        .then(setData)
        .catch(() => setError("دریافت درخواست ممکن نشد.")),
    [reference],
  );
  React.useEffect(() => {
    void load();
  }, [load]);
  React.useEffect(
    () => () => {
      if (preview) URL.revokeObjectURL(preview);
    },
    [preview],
  );
  const receipt = useReceipt(
    reference,
    Boolean(data?.current_receipt_reference),
  );
  const pick = (next?: File) => {
    if (preview) URL.revokeObjectURL(preview);
    setError("");
    if (!next) {
      setFile(undefined);
      setPreview(undefined);
      return;
    }
    if (
      !["image/jpeg", "image/png", "image/webp"].includes(next.type) ||
      next.size > 5 * 1024 * 1024
    ) {
      setError("فقط تصویر JPEG، PNG یا WebP تا ۵ مگابایت پذیرفته می‌شود.");
      return;
    }
    setFile(next);
    setPreview(URL.createObjectURL(next));
    key.current = logicalKey();
  };
  const submit = async () => {
    if (!file || busy) return;
    setBusy(true);
    const controller = new AbortController();
    try {
      await uploadReceipt(
        reference,
        file,
        (key.current ??= logicalKey()),
        setProgress,
        controller.signal,
      );
      pick();
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "بارگذاری انجام نشد.");
    } finally {
      setBusy(false);
    }
  };
  if (!data)
    return (
      <div className="manual-page">
        <div className="manual-list-state" role="status">
          <span className="manual-spinner" />
          {error || "در حال دریافت درخواست…"}
        </div>
      </div>
    );
  const cancellable = ["AWAITING_SUPPORT", "AWAITING_RECEIPT"].includes(
      data.status,
    ),
    uploadable = [
      "AWAITING_SUPPORT",
      "AWAITING_RECEIPT",
      "NEEDS_RESUBMISSION",
    ].includes(data.status);
  return (
    <main className="manual-page manual-detail">
      <a className="manual-back" href="/wallet/top-up">
        → بازگشت به افزایش موجودی
      </a>
      <header className="manual-status-hero">
        <div className={`manual-status-orb ${statusTone[data.status]}`}>
          {data.status === "APPROVED"
            ? "✓"
            : data.status === "REJECTED"
              ? "×"
              : "◌"}
        </div>
        <div>
          <span className={`manual-status ${statusTone[data.status]}`}>
            {statusLabels[data.status]}
          </span>
          <h1>{nextSteps[data.status]}</h1>
          <bdi>پیگیری {shortReference(data.reference)}</bdi>
        </div>
      </header>
      <dl className="manual-summary">
        <div>
          <dt>مبلغ درخواست</dt>
          <dd>{toman(data.requested_amount_rial)}</dd>
        </div>
        <div>
          <dt>زمان ایجاد</dt>
          <dd>{date(data.created_at)}</dd>
        </div>
        <div>
          <dt>شناسه پیگیری</dt>
          <dd>
            <bdi>{shortReference(data.reference)}</bdi>
          </dd>
        </div>
      </dl>
      {data.customer_message && (
        <aside className="manual-message" role="status">
          <strong>پیام بررسی</strong>
          <p>{data.customer_message}</p>
        </aside>
      )}
      {data.status === "APPROVED" && (
        <section className="manual-settlement">
          <div>
            <span>مجموع افزایش موجودی</span>
            <strong>{toman(data.total_credited_rial ?? 0)}</strong>
          </div>
          <a href="/wallet/transactions">مشاهده تراکنش‌های کیف پول</a>
        </section>
      )}
      {receipt && (
        <figure className="manual-receipt">
          <img src={receipt} alt="پیش‌نمایش امن فیش واریز" />
          <figcaption>فیش ارسال‌شده</figcaption>
        </figure>
      )}
      <section className="manual-actions">
        <header>
          <p className="eyebrow">مرحله بعد</p>
          <h2>{nextSteps[data.status]}</h2>
        </header>
        {uploadable && (
          <>
            <a
              className="manual-support"
              href={`/support?manual_topup_reference=${encodeURIComponent(data.reference)}`}
            >
              دریافت اطلاعات کارت از پشتیبانی
            </a>
            <ReceiptPicker
              file={file}
              preview={preview}
              progress={progress}
              busy={busy}
              pick={pick}
              submit={submit}
            />
          </>
        )}
        {data.status === "UNDER_REVIEW" && (
          <div className="manual-review-state">
            <span>✓</span>
            <div>
              <strong>فیش با موفقیت ارسال شد</strong>
              <p>در صف بررسی است؛ نیاز به اقدام دیگری نیست.</p>
            </div>
          </div>
        )}
        {cancellable && (
          <button
            className="manual-danger"
            disabled={busy}
            onClick={() => {
              if (confirm("این درخواست لغو شود؟")) {
                setBusy(true);
                void cancelManualTopup(reference, logicalKey())
                  .then(setData)
                  .catch(() =>
                    setError("لغو انجام نشد؛ وضعیت را به‌روزرسانی کنید."),
                  )
                  .finally(() => setBusy(false));
              }
            }}
          >
            لغو درخواست
          </button>
        )}
        {data.status === "REJECTED" && (
          <a className="manual-primary" href="/wallet/top-up">
            ایجاد درخواست جدید
          </a>
        )}
      </section>
      {error && (
        <p className="manual-alert" role="alert">
          {error}
        </p>
      )}
      <section className="manual-timeline-card">
        <h2>روند درخواست</h2>
        <ol className="manual-timeline">
          {data.timeline.map((entry, index) => (
            <li key={`${entry.event}-${index}`}>
              <i />
              <div>
                <span>
                  {entry.event === "CREATED"
                    ? "ایجاد درخواست"
                    : entry.event === "RECEIPT_SUBMITTED"
                      ? "ارسال فیش"
                      : (statusLabels[entry.event as ManualTopupStatus] ??
                        "به‌روزرسانی")}
                </span>
                <time>{date(entry.at)}</time>
              </div>
            </li>
          ))}
        </ol>
      </section>
    </main>
  );
}

function ReceiptPicker({
  file,
  preview,
  progress,
  busy,
  pick,
  submit,
}: {
  file?: File;
  preview?: string;
  progress: number;
  busy: boolean;
  pick: (file?: File) => void;
  submit: () => Promise<void>;
}): React.ReactElement {
  const input = React.useRef<HTMLInputElement>(null);
  return (
    <section className={`receipt-picker ${file ? "has-file" : ""}`}>
      <div className="receipt-heading">
        <span>
          <UploadIcon />
        </span>
        <div>
          <h2>{file ? "فیش آماده ارسال است" : "ارسال فیش واریز"}</h2>
          <p>
            {file
              ? "پیش از ارسال، تصویر را بررسی کنید."
              : "تصویر واضح و کامل فیش را انتخاب کنید."}
          </p>
        </div>
      </div>
      <input
        ref={input}
        className="sr-only"
        type="file"
        accept="image/jpeg,image/png,image/webp"
        capture="environment"
        onChange={(event) => pick(event.target.files?.[0])}
      />
      {!file && (
        <button
          type="button"
          className="receipt-select"
          onClick={() => input.current?.click()}
        >
          <UploadIcon />
          انتخاب تصویر فیش
        </button>
      )}
      {preview && file && (
        <div className="receipt-preview">
          <img src={preview} alt="پیش‌نمایش تصویر انتخاب‌شده" />
          <div className="receipt-file">
            <div>
              <strong dir="ltr">{file.name}</strong>
              <small>
                {(file.size / 1024).toLocaleString("fa-IR", {
                  maximumFractionDigits: 0,
                })}{" "}
                کیلوبایت · تصویر امن
              </small>
            </div>
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                if (input.current) input.current.value = "";
                pick();
              }}
              aria-label="حذف تصویر"
            >
              حذف
            </button>
          </div>
          <button
            type="button"
            className="manual-primary"
            disabled={busy}
            onClick={() => void submit()}
          >
            {busy
              ? `در حال ارسال · ${progress.toLocaleString("fa-IR")}٪`
              : "تأیید و ارسال فیش"}
          </button>
        </div>
      )}
      {busy && (
        <progress value={progress} max={100} aria-label="پیشرفت بارگذاری" />
      )}
      <span className="sr-only" aria-live="polite">
        {busy ? `${progress.toLocaleString("fa-IR")} درصد بارگذاری شده` : ""}
      </span>
      <small className="receipt-hint">
        JPEG، PNG یا WebP · حداکثر ۵ مگابایت
      </small>
    </section>
  );
}
