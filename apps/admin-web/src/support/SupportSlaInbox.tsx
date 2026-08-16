"use client";

import React, { useCallback, useEffect, useState } from "react";

import { acknowledgeSupportSlaEscalation, listOpenSlaEscalations } from "./api";
import styles from "./SupportSlaInbox.module.css";
import type { SupportSlaEscalation } from "./types";

const kindLabels: Record<SupportSlaEscalation["kind"], string> = {
  FIRST_RESPONSE: "پاسخ اول",
  NEXT_RESPONSE: "پاسخ بعدی",
  RESOLUTION: "حل نهایی",
  MANUAL: "ارجاع دستی",
};

const phaseLabels: Record<SupportSlaEscalation["phase"], string> = {
  AT_RISK: "در آستانه نقض",
  BREACHED: "نقض SLA",
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

export function SupportSlaInbox(): React.ReactElement {
  const [items, setItems] = useState<SupportSlaEscalation[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyReference, setBusyReference] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await listOpenSlaEscalations();
      setItems(result.items);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "دریافت هشدارهای SLA انجام نشد.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function acknowledge(reference: string): Promise<void> {
    if (busyReference) return;
    setBusyReference(reference);
    setError(null);
    try {
      await acknowledgeSupportSlaEscalation(reference);
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "ثبت بررسی هشدار SLA انجام نشد.");
    } finally {
      setBusyReference(null);
    }
  }

  return (
    <section dir="rtl" className={styles.inbox} aria-label="هشدارهای SLA پشتیبانی">
      <header className="support-runtime-header">
        <div>
          <h2>هشدارهای SLA</h2>
          <p>تیکت‌های در آستانه نقض یا عبورکرده از SLA که نیازمند بررسی عملیاتی هستند.</p>
        </div>
        <button
          type="button"
          onClick={() => void refresh()}
          disabled={loading || Boolean(busyReference)}
        >
          {loading ? "در حال دریافت…" : "تازه‌سازی هشدارها"}
        </button>
      </header>

      {error ? <div role="alert" className="support-runtime-error">{error}</div> : null}
      {!loading && items.length === 0 ? <p>هشدار SLA بازی وجود ندارد.</p> : null}

      <div className={styles.grid}>
        {items.slice(0, 20).map((item) => (
          <article className={styles.card} key={item.reference}>
            <strong>{phaseLabels[item.phase]} · {kindLabels[item.kind]}</strong>
            <span>{item.ticket_reference} · اولویت {item.priority}</span>
            <small>
              مشاهده: {faDate(item.observed_at)}
              {item.deadline_at ? ` · مهلت: ${faDate(item.deadline_at)}` : ""}
            </small>
            <button
              type="button"
              onClick={() => void acknowledge(item.reference)}
              disabled={Boolean(busyReference)}
            >
              {busyReference === item.reference ? "در حال ثبت…" : "ثبت بررسی"}
            </button>
          </article>
        ))}
      </div>
    </section>
  );
}
