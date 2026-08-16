"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";

import {
  acknowledgeSupportSlaEscalation,
  getConversationSlaEscalations,
  manuallyEscalateSupportConversation,
} from "./api";
import type { SupportConversationDetail, SupportSlaEscalation } from "./types";

const terminal = new Set(["RESOLVED", "CLOSED", "SPAM", "ARCHIVED"]);

const kindLabels: Record<SupportSlaEscalation["kind"], string> = {
  FIRST_RESPONSE: "پاسخ اول",
  NEXT_RESPONSE: "پاسخ بعدی",
  RESOLUTION: "حل نهایی",
  MANUAL: "ارجاع دستی",
};

const phaseLabels: Record<SupportSlaEscalation["phase"], string> = {
  AT_RISK: "در آستانه نقض SLA",
  BREACHED: "SLA نقض شده",
  MANUAL: "ارجاع دستی",
};

function faDate(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("fa-IR", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(date);
}

export function SupportSlaPanel({
  detail,
}: {
  detail: SupportConversationDetail;
}): React.ReactElement {
  const [items, setItems] = useState<SupportSlaEscalation[]>([]);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const result = await getConversationSlaEscalations(detail.reference);
      setItems(result.items);
      setError(null);
    } catch (cause) {
      setItems([]);
      setError(cause instanceof Error ? cause.message : "دریافت وضعیت SLA انجام نشد.");
    }
  }, [detail.reference]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const openItems = useMemo(() => items.filter((item) => item.status === "OPEN"), [items]);
  const canEscalate = !terminal.has(detail.status);

  async function escalate(): Promise<void> {
    if (!canEscalate || busy || reason.trim().length < 3) return;
    setBusy(true);
    setError(null);
    try {
      await manuallyEscalateSupportConversation(detail.reference, reason.trim(), detail.version);
      setReason("");
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "ارجاع SLA انجام نشد.");
    } finally {
      setBusy(false);
    }
  }

  async function acknowledge(reference: string): Promise<void> {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await acknowledgeSupportSlaEscalation(reference);
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "تأیید هشدار SLA انجام نشد.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="support-runtime-actions support-runtime-sla" aria-label="عملیات SLA">
      <h3>SLA و ارجاع عملیاتی</h3>
      <p className="muted">
        {openItems.length > 0
          ? `${openItems.length.toLocaleString("fa-IR")} هشدار باز نیازمند بررسی است.`
          : "هشدار SLA بازی برای این تیکت وجود ندارد."}
      </p>

      <div className="support-runtime-notes">
        {items.slice(0, 8).map((item) => (
          <article key={item.reference}>
            <strong>
              {phaseLabels[item.phase]} · {kindLabels[item.kind]}
            </strong>
            <p>
              {item.reference} · مشاهده: {faDate(item.observed_at)}
              {item.deadline_at ? ` · مهلت: ${faDate(item.deadline_at)}` : ""}
            </p>
            {item.status === "OPEN" ? (
              <button
                type="button"
                onClick={() => void acknowledge(item.reference)}
                disabled={busy}
              >
                ثبت بررسی هشدار
              </button>
            ) : (
              <small>بررسی شده در {faDate(item.acknowledged_at)}</small>
            )}
          </article>
        ))}
      </div>

      {error ? <p role="alert" className="support-runtime-error">{error}</p> : null}

      <div className="support-runtime-status-row">
        <input
          aria-label="دلیل ارجاع دستی"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          maxLength={500}
          placeholder="دلیل ارجاع دستی به مدیر"
          disabled={busy || !canEscalate}
        />
        <button
          type="button"
          onClick={() => void escalate()}
          disabled={busy || !canEscalate || reason.trim().length < 3}
        >
          ارجاع دستی
        </button>
      </div>
    </section>
  );
}
