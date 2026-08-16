"use client";

import React from "react";
import {
  getConnectionQr,
  getServiceDelivery,
  issueServiceSubscription,
  resolveSubscriptionUrl,
  revokeServiceSubscription,
  rotateServiceSubscription,
  ServiceRequestError,
  type SubscriptionStatus,
} from "../services";

const subscriptionFormats = [
  ["base64", "لینک اشتراک"],
  ["links", "لینک‌های مستقیم"],
  ["mihomo", "Mihomo"],
  ["clash", "Clash"],
  ["sing_box", "sing-box"],
] as const;

type SecretLinks = Partial<Record<(typeof subscriptionFormats)[number][0], string>>;
type BusyAction = "connection" | "qr" | "issue" | "rotate" | "revoke" | null;

function normalizeIssuedUrls(result: SubscriptionStatus): SecretLinks {
  const safe: SecretLinks = {};
  for (const [key] of subscriptionFormats) {
    const value = result.stable_urls[key];
    if (value) safe[key] = resolveSubscriptionUrl(value);
  }
  if (Object.keys(safe).length === 0) throw new Error("subscription_urls_missing");
  return safe;
}

export function ServiceConnectionPanel({
  serviceReference,
}: {
  serviceReference: string;
}): React.ReactElement {
  const [connection, setConnection] = React.useState<string | null>(null);
  const [links, setLinks] = React.useState<SecretLinks | null>(null);
  const [existingSubscription, setExistingSubscription] = React.useState(false);
  const [busy, setBusy] = React.useState<BusyAction>(null);
  const [message, setMessage] = React.useState("");
  const [error, setError] = React.useState("");
  const [ambiguousMutation, setAmbiguousMutation] = React.useState(false);
  const [confirmRotate, setConfirmRotate] = React.useState(false);
  const [confirmRevoke, setConfirmRevoke] = React.useState(false);
  const [qrUrl, setQrUrl] = React.useState<string | null>(null);
  const qrObjectUrl = React.useRef<string | null>(null);

  React.useEffect(
    () => () => {
      if (qrObjectUrl.current) URL.revokeObjectURL(qrObjectUrl.current);
    },
    [],
  );

  const replaceQr = (next: string | null) => {
    if (qrObjectUrl.current) URL.revokeObjectURL(qrObjectUrl.current);
    qrObjectUrl.current = next;
    setQrUrl(next);
  };

  const resetFeedback = () => {
    setMessage("");
    setError("");
  };

  const copy = async (value: string, label: string) => {
    resetFeedback();
    try {
      await navigator.clipboard.writeText(value);
      setMessage(`${label} کپی شد.`);
    } catch {
      setError("کپی خودکار ممکن نشد. می‌توانید مقدار را انتخاب و دستی کپی کنید.");
    }
  };

  const handleReadError = () => {
    setError("دریافت اطلاعات اتصال ممکن نشد. وضعیت سرویس را دوباره بررسی کنید.");
  };

  const handleMutationError = (caught: unknown) => {
    const ambiguous =
      !(caught instanceof ServiceRequestError) || caught.status === 0;
    if (ambiguous) {
      setAmbiguousMutation(true);
      setError(
        "پاسخ قابل اتکایی برای نتیجه عملیات در دسترس نیست. برای جلوگیری از ساخت یا لغو تکراری، عملیات اشتراک در این صفحه متوقف شد؛ صفحه را دوباره باز کنید و وضعیت را بررسی کنید.",
      );
      return;
    }
    setError("عملیات اشتراک انجام نشد و پاسخ قطعی خطا از سرور دریافت شد.");
  };

  const revealConnection = async () => {
    if (busy) return;
    resetFeedback();
    setBusy("connection");
    try {
      const result = await getServiceDelivery(serviceReference);
      const uri = result.connections[0]?.uri?.trim();
      if (
        result.service_reference !== serviceReference ||
        result.status !== "ACTIVE" ||
        result.delivery_ready !== true ||
        result.connections.length !== 1 ||
        !uri
      ) {
        throw new Error("delivery_not_ready");
      }
      setConnection(uri);
      replaceQr(null);
      setMessage("کانفیگ فقط در همین صفحه نمایش داده شده است.");
    } catch {
      handleReadError();
    } finally {
      setBusy(null);
    }
  };

  const revealQr = async () => {
    if (!connection || busy) return;
    resetFeedback();
    setBusy("qr");
    try {
      const blob = await getConnectionQr(connection);
      const objectUrl = URL.createObjectURL(blob);
      replaceQr(objectUrl);
      setMessage("QR از همان کانفیگ نمایش‌داده‌شده ساخته شد.");
    } catch {
      handleReadError();
    } finally {
      setBusy(null);
    }
  };

  const issue = async () => {
    if (busy || ambiguousMutation) return;
    resetFeedback();
    setBusy("issue");
    try {
      const result = await issueServiceSubscription(serviceReference);
      if (result.service_reference !== serviceReference || result.status !== "ACTIVE") {
        throw new Error("subscription_not_active");
      }
      if (Object.keys(result.stable_urls).length === 0) {
        setLinks(null);
        setExistingSubscription(true);
        setMessage(
          "یک اشتراک فعال از قبل وجود دارد، اما متن لینک قبلی قابل بازیابی نیست. برای دریافت لینک تازه، چرخش را آگاهانه تأیید کنید.",
        );
      } else {
        setLinks(normalizeIssuedUrls(result));
        setExistingSubscription(false);
        setMessage(
          "لینک تازه فقط در همین صفحه نگه داشته می‌شود. قبل از خروج آن را در برنامه موردنظر وارد یا کپی کنید.",
        );
      }
    } catch (caught) {
      handleMutationError(caught);
    } finally {
      setBusy(null);
    }
  };

  const rotate = async () => {
    if (busy || ambiguousMutation || !confirmRotate) return;
    resetFeedback();
    setBusy("rotate");
    try {
      const result = await rotateServiceSubscription(serviceReference);
      if (result.service_reference !== serviceReference || result.status !== "ACTIVE") {
        throw new Error("subscription_not_active");
      }
      setLinks(normalizeIssuedUrls(result));
      setExistingSubscription(false);
      setConfirmRotate(false);
      setConfirmRevoke(false);
      setMessage(
        "لینک جدید ساخته شد. لینک قبلی ممکن است فقط برای مدت کوتاهی هنگام گذار معتبر بماند؛ لینک جدید را جایگزین کنید.",
      );
    } catch (caught) {
      handleMutationError(caught);
    } finally {
      setBusy(null);
    }
  };

  const revoke = async () => {
    if (busy || ambiguousMutation || !confirmRevoke) return;
    resetFeedback();
    setBusy("revoke");
    try {
      const result = await revokeServiceSubscription(serviceReference);
      if (result.service_reference !== serviceReference || result.status !== "REVOKED") {
        throw new Error("subscription_not_revoked");
      }
      setLinks(null);
      setExistingSubscription(false);
      setConfirmRotate(false);
      setConfirmRevoke(false);
      setMessage("اشتراک لغو شد و لینک‌های نمایش‌داده‌شده از این صفحه پاک شدند.");
    } catch (caught) {
      handleMutationError(caught);
    } finally {
      setBusy(null);
    }
  };

  const clearSecrets = () => {
    setConnection(null);
    setLinks(null);
    replaceQr(null);
    setMessage("اطلاعات حساس از این صفحه پاک شد.");
    setError("");
  };

  const mutationDisabled = busy !== null || ambiguousMutation;

  return (
    <div className="service-connection-panel">
      <header>
        <h2>اتصال امن</h2>
        <p>
          کانفیگ یا لینک اشتراک فقط با درخواست صریح شما دریافت می‌شود و در
          حافظه دائمی مرورگر ذخیره نمی‌شود.
        </p>
      </header>

      {message && (
        <p className="operation-banner" role="status">
          {message}
        </p>
      )}
      {error && (
        <p className="operation-banner" role="alert">
          {error}
        </p>
      )}

      <section>
        <h3>کانفیگ مستقیم</h3>
        <p>برای نمایش URI واقعی، این دکمه را آگاهانه انتخاب کنید.</p>
        {!connection ? (
          <div className="panel-actions">
            <button
              type="button"
              onClick={() => void revealConnection()}
              disabled={busy !== null}
            >
              {busy === "connection" ? "در حال دریافت…" : "نمایش کانفیگ مستقیم"}
            </button>
          </div>
        ) : (
          <div className="operation-grid">
            <div>
              <strong>کانفیگ مستقیم</strong>
              <code dir="ltr">{connection}</code>
              <div className="panel-actions">
                <button type="button" onClick={() => void copy(connection, "کانفیگ")}>
                  کپی کانفیگ
                </button>
                <button
                  type="button"
                  onClick={() => void revealQr()}
                  disabled={busy !== null}
                >
                  {busy === "qr" ? "در حال ساخت QR…" : "نمایش QR"}
                </button>
              </div>
            </div>
          </div>
        )}
        {qrUrl && (
          <figure>
            <img src={qrUrl} alt="QR کانفیگ اتصال این سرویس" width="220" height="220" />
            <figcaption>این QR همان کانفیگ مستقیم نمایش‌داده‌شده را در خود دارد.</figcaption>
          </figure>
        )}
      </section>

      <section>
        <h3>اشتراک</h3>
        {!links && !existingSubscription && (
          <div className="panel-actions">
            <button
              type="button"
              onClick={() => void issue()}
              disabled={mutationDisabled}
            >
              {busy === "issue" ? "در حال دریافت…" : "دریافت لینک اشتراک"}
            </button>
          </div>
        )}

        {links && (
          <div className="operation-grid">
            {subscriptionFormats.map(([key, label]) => {
              const value = links[key];
              if (!value) return null;
              return (
                <div key={key}>
                  <strong>{label}</strong>
                  <code dir="ltr">{value}</code>
                  <button type="button" onClick={() => void copy(value, label)}>
                    کپی
                  </button>
                </div>
              );
            })}
          </div>
        )}

        {(links || existingSubscription) && !ambiguousMutation && (
          <div className="panel-actions">
            {!confirmRotate ? (
              <button
                type="button"
                onClick={() => {
                  setConfirmRotate(true);
                  setConfirmRevoke(false);
                  resetFeedback();
                }}
                disabled={busy !== null}
              >
                ساخت لینک اشتراک جدید
              </button>
            ) : (
              <>
                <button type="button" onClick={() => void rotate()} disabled={busy !== null}>
                  {busy === "rotate" ? "در حال چرخش…" : "تأیید ساخت لینک جدید"}
                </button>
                <button type="button" onClick={() => setConfirmRotate(false)} disabled={busy !== null}>
                  انصراف
                </button>
              </>
            )}

            {!confirmRevoke ? (
              <button
                type="button"
                onClick={() => {
                  setConfirmRevoke(true);
                  setConfirmRotate(false);
                  resetFeedback();
                }}
                disabled={busy !== null}
              >
                لغو لینک اشتراک
              </button>
            ) : (
              <>
                <button type="button" onClick={() => void revoke()} disabled={busy !== null}>
                  {busy === "revoke" ? "در حال لغو…" : "تأیید لغو اشتراک"}
                </button>
                <button type="button" onClick={() => setConfirmRevoke(false)} disabled={busy !== null}>
                  انصراف
                </button>
              </>
            )}
          </div>
        )}
      </section>

      {(connection || links || qrUrl) && (
        <div className="panel-actions">
          <button type="button" onClick={clearSecrets}>
            پاک‌کردن اطلاعات حساس از صفحه
          </button>
        </div>
      )}

      <small>
        این صفحه عملیات issue/rotate/revoke را در خطای شبکه خودکار تکرار نمی‌کند؛
        نتیجه نامشخص باید ابتدا با بازکردن دوباره صفحه بررسی شود.
      </small>
    </div>
  );
}
